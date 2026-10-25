#!/usr/bin/env python3
"""Validate a Yacht Calendar Standard feed.

Usage:
    python3 tools/validate.py feed.json
    python3 tools/validate.py path/to/sheet-csv-folder/   (Yachts.csv, Bookings.csv, ...)

Checks the fields and formats in SPEC.md, the level rules, and the update
rules that can be checked from the data itself. Prints the access level the
feed actually provides. Exit code 0 = valid, 1 = errors found.
Standard library only.
"""
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ID = re.compile(r"^.{1,64}$")
CYA_ID = re.compile(r"^[0-9a-f]{24}$")
LOCAL_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
UTC_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TZ = re.compile(r"^[A-Za-z_]+(/[A-Za-z0-9_+-]+)+$|^UTC$")
CURRENCY = re.compile(r"^[A-Z]{3}$")
LOCATION = re.compile(r"^.+, .+$")
URL = re.compile(r"^https?://")
STATUSES = {"booked", "hold", "unavailable"}
ACCESS = {"profile": {"basic", "full"}, "calendar": {"none", "busy", "status", "full"}, "rates": {"none", "seasons", "full"}}
BASIC_FIELDS = {"id", "name", "length", "guests", "cabins", "access"}
PRICE_FIELDS = ("currency", "weekly_rate_from", "vat", "apa", "terms")
YACHT_TYPES = {"motor", "sail", "catamaran", "power_catamaran", "gulet", "motor_sailer", "other"}
CABIN_TYPES = {"master", "vip", "double", "twin", "single", "bunk", "convertible"}
TERMS = {"plus_expenses", "inclusive", "all_inclusive"}
PERSONAL = re.compile(r"client|guest_name|email|phone|passport|owner_name|commission|fee_paid|price_paid", re.I)

# field -> (required, kind)
YACHT = {
    "id": (True, "id"), "name": (True, "str"), "cya_id": (False, "cya_id"),
    "previous_names": (False, "str_list"), "type": (False, "yacht_type"), "builder": (False, "str"),
    "model": (False, "str"), "year": (False, "year"), "refit": (False, "year"), "flag": (False, "str"),
    "length": (True, "pos_number"), "beam": (False, "pos_number"), "draft": (False, "pos_number"),
    "cruising_speed": (False, "number"), "max_speed": (False, "number"), "range": (False, "number"),
    "fuel_per_hour": (False, "number"), "guests": (True, "pos_int"), "cabins": (True, "int"),
    "cabin_types": (False, "cabin_types"), "crew": (False, "int"), "home_port": (False, "location"),
    "cruising_areas": (False, "str_list"), "air_conditioning": (False, "bool"), "ac_at_night": (False, "bool"),
    "diving": (False, "bool"), "amenities": (False, "str_list"), "toys": (False, "str_list"),
    "description": (False, "str"), "crew_description": (False, "str"), "photos": (False, "url_list"),
    "videos": (False, "url_list"), "brochure": (False, "url"), "updated_at": (False, "utc"),
    "access": (False, "access"),
}
AVAILABILITY = {
    "yacht_id": (True, "id"), "start": (True, "local_dt"), "end": (True, "local_dt"),
    "timezone": (True, "tz"), "status": (True, "avail_status"),
}
BOOKING = {
    "id": (True, "id"), "yacht_id": (True, "id"), "status": (True, "status"),
    "start": (True, "local_dt"), "end": (True, "local_dt"), "timezone": (True, "tz"),
    "pickup": (True, "location"), "dropoff": (True, "location"),
    "hold_expires": (False, "utc"), "updated_at": (True, "utc"),
}
SEASON = {
    "yacht_id": (True, "id"), "name": (True, "str"), "start": (True, "date"), "end": (True, "date"),
    "base_port": (True, "location"), "cruising_areas": (True, "str_list"), "relocation_ports": (False, "ports"),
    "turnaround_hours": (True, "int"), "min_nights": (False, "pos_int"), "currency": (False, "currency"),
    "weekly_rate_from": (False, "number"), "weekly_rate_to": (False, "number"),
    "vat": (False, "percent"), "apa": (False, "percent"), "terms": (False, "terms"), "holidays": (False, "str"),
}
LISTS = {"yachts": YACHT, "availability": AVAILABILITY, "bookings": BOOKING, "seasons": SEASON}


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_value(kind, v):
    """Return an error string, or None if v is valid for kind."""
    checks = {
        "id": lambda: isinstance(v, str) and ID.match(v),
        "str": lambda: isinstance(v, str) and v.strip(),
        "cya_id": lambda: isinstance(v, str) and CYA_ID.match(v),
        "pos_number": lambda: _num(v) and v > 0,
        "number": lambda: _num(v) and v >= 0,
        "int": lambda: _int(v) and v >= 0,
        "pos_int": lambda: _int(v) and v >= 1,
        "year": lambda: _int(v) and 1850 <= v <= 2100,
        "percent": lambda: _num(v) and 0 <= v <= 100,
        "bool": lambda: isinstance(v, bool),
        "yacht_type": lambda: v in YACHT_TYPES,
        "status": lambda: v in STATUSES,
        "avail_status": lambda: v in STATUSES | {"busy"},
        "access": lambda: isinstance(v, dict) and set(ACCESS) <= set(v) <= set(ACCESS) | {"months_ahead"}
        and all(v[k] in ACCESS[k] for k in ACCESS) and ("months_ahead" not in v or (_int(v["months_ahead"]) and v["months_ahead"] >= 1)),
        "terms": lambda: v in TERMS,
        "local_dt": lambda: isinstance(v, str) and LOCAL_DT.match(v),
        "utc": lambda: isinstance(v, str) and UTC_TS.match(v),
        "date": lambda: isinstance(v, str) and DATE.match(v),
        "tz": lambda: isinstance(v, str) and TZ.match(v),
        "currency": lambda: isinstance(v, str) and CURRENCY.match(v),
        "location": lambda: isinstance(v, str) and LOCATION.match(v),
        "url": lambda: isinstance(v, str) and URL.match(v),
        "str_list": lambda: isinstance(v, list) and all(isinstance(x, str) and x for x in v),
        "url_list": lambda: isinstance(v, list) and all(isinstance(x, str) and URL.match(x) for x in v),
        "cabin_types": lambda: isinstance(v, dict) and all(k in CABIN_TYPES and _int(n) and n >= 0 for k, n in v.items()),
        "ports": lambda: isinstance(v, list) and all(
            isinstance(p, dict) and set(p) <= {"port", "fee"} and LOCATION.match(str(p.get("port", "")))
            and ("fee" not in p or (_num(p["fee"]) and p["fee"] >= 0)) for p in v),
    }
    return None if checks[kind]() else f"bad {kind}: {v!r}"


def check_records(name, records, fields, errors, from_sheet):
    for i, rec in enumerate(records):
        where = f"{name}[{i}]"
        if not isinstance(rec, dict):
            errors.append(f"{where}: not an object")
            continue
        for key in rec:
            if key not in fields:
                errors.append(f"{where}: unknown field '{key}'")
            if PERSONAL.search(key):
                errors.append(f"{where}: field '{key}' looks like personal or financial data, which no level may contain")
        for key, (required, kind) in fields.items():
            if key not in rec or (from_sheet and rec[key] is None):
                if required:
                    errors.append(f"{where}: missing required '{key}'")
                continue
            v = rec[key]
            if v is None:
                errors.append(f"{where}.{key}: null; leave the field out instead")
                continue
            err = check_value(kind, v)
            if err:
                errors.append(f"{where}.{key}: {err}")
        if name == "yachts" and isinstance(rec.get("cabin_types"), dict) and _int(rec.get("cabins")):
            total = sum(n for n in rec["cabin_types"].values() if _int(n))
            if total != rec["cabins"]:
                errors.append(f"{where}: cabin_types add up to {total}, but cabins is {rec['cabins']}")


def parse_local(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None


def check_rules(feed, errors, warnings):
    yacht_ids = [y.get("id") for y in feed.get("yachts", []) if isinstance(y, dict)]
    known = set(yacht_ids)
    if len(known) != len(yacht_ids):
        errors.append("yachts: duplicate id")

    booking_ids = set()
    by_yacht = {}
    for name, i, p in [(n, i, p) for n in ("availability", "bookings") for i, p in enumerate(feed.get(n) or [])]:
        if not isinstance(p, dict):
            continue
        where = f"{name}[{i}]"
        if p.get("yacht_id") not in known:
            errors.append(f"{where}: yacht_id '{p.get('yacht_id')}' is not in the yacht list")
        start, end = parse_local(p.get("start")), parse_local(p.get("end"))
        if start and end:
            if end <= start:
                errors.append(f"{where}: end is not after start")
            by_yacht.setdefault(p.get("yacht_id"), []).append((start, end, where))
        if name == "bookings":
            bid = p.get("id")
            if bid in booking_ids:
                errors.append(f"{where}: duplicate booking id '{bid}'")
            booking_ids.add(bid)
            if p.get("status") == "hold":
                expires = p.get("hold_expires")
                if not expires:
                    errors.append(f"{where}: a hold needs hold_expires")
                elif isinstance(expires, str) and UTC_TS.match(expires):
                    when = datetime.strptime(expires[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
                    if when < datetime.now(timezone.utc):
                        warnings.append(f"{where}: hold expired {expires}; a released hold must leave the feed or become booked")

    for yid, spans in by_yacht.items():
        spans.sort()
        for (s1, e1, w1), (s2, e2, w2) in zip(spans, spans[1:]):
            if s2 < e1:
                errors.append(f"{w2}: overlaps {w1} for yacht '{yid}'")

    for i, s in enumerate(feed.get("seasons") or []):
        if not isinstance(s, dict):
            continue
        if s.get("yacht_id") not in known:
            errors.append(f"seasons[{i}]: yacht_id '{s.get('yacht_id')}' is not in the yacht list")
        if isinstance(s.get("start"), str) and isinstance(s.get("end"), str) and s["end"] < s["start"]:
            errors.append(f"seasons[{i}]: end is before start")
        low, high = s.get("weekly_rate_from"), s.get("weekly_rate_to")
        if _num(low) and _num(high) and high < low:
            errors.append(f"seasons[{i}]: weekly_rate_to is below weekly_rate_from")


def check_per_yacht(feed, errors):
    """Every yacht says what this recipient may see; the lists must agree with it."""
    access = {}
    for i, y in enumerate(feed.get("yachts") or []):
        if not isinstance(y, dict):
            continue
        a = y.get("access")
        if not isinstance(a, dict):
            errors.append(f"yachts[{i}]: a per_yacht feed needs 'access' on every yacht")
            continue
        access[y.get("id")] = a
        if a.get("profile") == "basic" and set(y) - BASIC_FIELDS:
            errors.append(f"yachts[{i}]: profile 'basic' allows only {sorted(BASIC_FIELDS - {'access'})}, found {sorted(set(y) - BASIC_FIELDS)}")
    levels = {a.get("calendar") for a in access.values()}
    if levels & {"busy", "status"} and "availability" not in feed:
        errors.append("a yacht has calendar 'busy' or 'status' but the feed has no 'availability' list")
    if "full" in levels and "bookings" not in feed:
        errors.append("a yacht has calendar 'full' but the feed has no 'bookings' list")
    for i, p in enumerate(feed.get("availability") or []):
        cal = access.get(p.get("yacht_id"), {}).get("calendar") if isinstance(p, dict) else None
        if cal not in ("busy", "status"):
            errors.append(f"availability[{i}]: yacht '{p.get('yacht_id')}' has calendar '{cal}', not busy or status")
        elif (cal == "busy") != (p.get("status") == "busy"):
            errors.append(f"availability[{i}]: calendar '{cal}' must {'only' if cal == 'busy' else 'never'} use status 'busy'")
    for i, p in enumerate(feed.get("bookings") or []):
        cal = access.get(p.get("yacht_id"), {}).get("calendar") if isinstance(p, dict) else None
        if cal != "full":
            errors.append(f"bookings[{i}]: yacht '{p.get('yacht_id')}' has calendar '{cal}', not full")
    for i, s in enumerate(feed.get("seasons") or []):
        rates = access.get(s.get("yacht_id"), {}).get("rates") if isinstance(s, dict) else None
        has_prices = isinstance(s, dict) and any(k in s for k in PRICE_FIELDS + ("weekly_rate_to", "holidays"))
        if rates not in ("seasons", "full"):
            errors.append(f"seasons[{i}]: yacht '{s.get('yacht_id')}' has rates '{rates}'")
        elif rates == "seasons" and has_prices:
            errors.append(f"seasons[{i}]: rates 'seasons' must not carry prices")
        elif rates == "full" and any(k not in s for k in PRICE_FIELDS):
            errors.append(f"seasons[{i}]: rates 'full' needs the price fields {list(PRICE_FIELDS)}")


def provided_level(feed):
    if feed.get("level") == "per_yacht":
        return "per_yacht"
    if "seasons" in feed and "bookings" in feed:
        return 4
    if "bookings" in feed:
        return 3
    if "availability" in feed:
        return 2
    return 1 if "yachts" in feed else 0


REQUIRED_KEYS = {1: {"yachts"}, 2: {"yachts", "availability"}, 3: {"yachts", "bookings"}, 4: {"yachts", "bookings", "seasons"}}


def validate(feed, from_sheet=False):
    errors, warnings = [], []
    if not isinstance(feed, dict):
        return ["feed is not a JSON object"], [], 0
    for key in ("standard", "ca", "generated_at", "level"):
        if key not in feed:
            errors.append(f"missing top-level '{key}'")
    for key in feed:
        if key not in {"standard", "ca", "generated_at", "level", *LISTS}:
            errors.append(f"unknown top-level key '{key}'")
    if "generated_at" in feed and not (isinstance(feed["generated_at"], str) and UTC_TS.match(feed["generated_at"])):
        errors.append(f"generated_at: bad utc: {feed['generated_at']!r}")

    level = feed.get("level")
    if level in REQUIRED_KEYS:
        present = {k for k in LISTS if k in feed}
        if present != REQUIRED_KEYS[level]:
            errors.append(f"level {level} feed must contain exactly {sorted(REQUIRED_KEYS[level])}, found {sorted(present)}")
    elif level == "per_yacht":
        check_per_yacht(feed, errors)
    elif "level" in feed:
        errors.append(f"level must be 1, 2, 3, 4 or 'per_yacht', found {level!r}")
    if level != "per_yacht":
        for i, a in enumerate(feed.get("availability") or []):
            if isinstance(a, dict) and a.get("status") == "busy":
                errors.append(f"availability[{i}]: status 'busy' is only for per_yacht feeds")
        for i, y in enumerate(feed.get("yachts") or []):
            if isinstance(y, dict) and "access" in y:
                errors.append(f"yachts[{i}]: 'access' is only for per_yacht feeds")
    if level == 4:
        for i, s in enumerate(feed.get("seasons") or []):
            if isinstance(s, dict) and any(k not in s for k in PRICE_FIELDS):
                errors.append(f"seasons[{i}]: a level 4 feed needs the price fields {list(PRICE_FIELDS)}")

    for name, fields in LISTS.items():
        if name in feed:
            if isinstance(feed[name], list):
                check_records(name, feed[name], fields, errors, from_sheet)
            else:
                errors.append(f"{name}: must be a list")
    check_rules(feed, errors, warnings)
    return errors, warnings, provided_level(feed)


def _number(raw):
    try:
        f = float(raw)
    except ValueError:
        return raw
    return int(f) if f.is_integer() and "." not in raw else f


def csv_cell(field, raw, fields):
    """Sheet cell -> JSON value, following SPEC.md section 8."""
    raw = raw.strip()
    if raw == "":
        return None
    kind = fields[field][1] if field in fields else "str"
    parts = [x.strip() for x in raw.split(";") if x.strip()]
    if kind in ("str_list", "url_list"):
        return parts
    if kind == "bool":
        return {"yes": True, "no": False, "true": True, "false": False}.get(raw.lower(), raw)
    if kind == "cabin_types":
        out = {}
        for part in parts:
            k, _, n = part.partition("=")
            out[k.strip()] = _number(n.strip()) if n.strip() else n
        return out
    if kind == "ports":
        ports = []
        for part in parts:
            port, _, fee = part.partition("=")
            entry = {"port": port.strip()}
            if fee.strip():
                entry["fee"] = _number(fee.strip())
            ports.append(entry)
        return ports
    if kind in ("int", "pos_int", "year", "number", "pos_number", "percent"):
        return _number(raw)
    return raw


def load_sheet_folder(folder):
    tabs = {"Yachts": "yachts", "Availability": "availability", "Bookings": "bookings", "Seasons": "seasons"}
    feed = {"standard": "yacht-calendar-standard/0.4", "ca": folder.name,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    for tab, key in tabs.items():
        path = folder / f"{tab}.csv"
        if path.exists():
            with path.open(newline="", encoding="utf-8-sig") as fh:
                feed[key] = [{k: csv_cell(k, v or "", LISTS[key]) for k, v in row.items()} for row in csv.DictReader(fh)]
    feed["level"] = provided_level(feed)
    return feed


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip())
        return 2
    path = Path(argv[1])
    if path.is_dir():
        feed, from_sheet = load_sheet_folder(path), True
    else:
        feed, from_sheet = json.loads(path.read_text(encoding="utf-8")), False
    errors, warnings, level = validate(feed, from_sheet)
    names = {0: "none", 1: "Fleet", 2: "Availability", 3: "Calendar", 4: "Seasons and rates", "per_yacht": "set per yacht"}
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error:   {e}")
    status = "INVALID" if errors else "VALID"
    print(f"{status}: {path} provides level {level} ({names[level]}), {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
