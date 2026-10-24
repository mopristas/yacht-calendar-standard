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
CATEGORIES = {"booked", "hold", "unavailable"}
YACHT_TYPES = {"motor", "sail", "catamaran", "power_catamaran", "gulet", "motor_sailer", "other"}
TERMS = {"plus_expenses", "inclusive", "all_inclusive"}
PERSONAL = re.compile(r"client|guest_name|email|phone|passport|owner_name|commission|fee_paid|price_paid", re.I)

# field -> (required, kind)
YACHT = {
    "yacht_id": (True, "id"), "yacht_name": (True, "str"), "cya_id": (False, "cya_id"),
    "length_m": (True, "pos_number"), "builder": (False, "str"), "year_built": (False, "int"),
    "type": (False, "yacht_type"), "guests": (True, "pos_int"), "cabins": (True, "int"),
    "crew": (False, "int"), "updated_at": (False, "utc"),
}
AVAILABILITY = {
    "yacht_id": (True, "id"), "start": (True, "local_dt"), "end": (True, "local_dt"),
    "timezone": (True, "tz"), "category": (True, "category"),
}
BOOKING = {
    "booking_id": (True, "id"), "yacht_id": (True, "id"), "category": (True, "category"),
    "start": (True, "local_dt"), "end": (True, "local_dt"), "timezone": (True, "tz"),
    "pickup_location": (True, "location"), "drop_off_location": (True, "location"),
    "hold_expires": (False, "utc"), "updated_at": (True, "utc"),
}
SEASON = {
    "yacht_id": (True, "id"), "title": (True, "str"), "start_date": (True, "date"),
    "end_date": (True, "date"), "base_port": (True, "location"), "cruising_areas": (True, "str_list"),
    "relocation_ports": (False, "ports"), "turnaround_hours": (True, "int"), "min_nights": (False, "pos_int"),
    "currency": (True, "currency"), "weekly_rate_low": (True, "number"), "weekly_rate_high": (False, "number"),
    "vat_percent": (True, "percent"), "apa_percent": (True, "percent"), "terms": (True, "terms"),
    "holiday_rules": (False, "str"),
}
LISTS = {"yachts": YACHT, "availability": AVAILABILITY, "bookings": BOOKING, "seasons": SEASON}
INT_FIELDS = {"year_built", "guests", "cabins", "crew", "turnaround_hours", "min_nights"}
NUM_FIELDS = {"length_m", "weekly_rate_low", "weekly_rate_high", "vat_percent", "apa_percent"}


def check_value(kind, v):
    """Return an error string, or None if v is valid for kind."""
    is_num = isinstance(v, (int, float)) and not isinstance(v, bool)
    checks = {
        "id": lambda: isinstance(v, str) and ID.match(v),
        "str": lambda: isinstance(v, str) and v.strip(),
        "cya_id": lambda: isinstance(v, str) and CYA_ID.match(v),
        "pos_number": lambda: is_num and v > 0,
        "number": lambda: is_num and v >= 0,
        "int": lambda: isinstance(v, int) and not isinstance(v, bool) and v >= 0,
        "pos_int": lambda: isinstance(v, int) and not isinstance(v, bool) and v >= 1,
        "percent": lambda: is_num and 0 <= v <= 100,
        "yacht_type": lambda: v in YACHT_TYPES,
        "category": lambda: v in CATEGORIES,
        "terms": lambda: v in TERMS,
        "local_dt": lambda: isinstance(v, str) and LOCAL_DT.match(v),
        "utc": lambda: isinstance(v, str) and UTC_TS.match(v),
        "date": lambda: isinstance(v, str) and DATE.match(v),
        "tz": lambda: isinstance(v, str) and TZ.match(v),
        "currency": lambda: isinstance(v, str) and CURRENCY.match(v),
        "location": lambda: isinstance(v, str) and LOCATION.match(v),
        "str_list": lambda: isinstance(v, list) and v and all(isinstance(x, str) and x for x in v),
        "ports": lambda: isinstance(v, list) and all(
            isinstance(p, dict) and LOCATION.match(str(p.get("port", "")))
            and (p.get("fee") is None or (isinstance(p["fee"], (int, float)) and p["fee"] >= 0)) for p in v),
    }
    return None if checks[kind]() else f"bad {kind}: {v!r}"


def check_records(name, records, fields, errors):
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
            v = rec.get(key)
            if v is None or v == "" or v == []:
                if required:
                    errors.append(f"{where}: missing required '{key}'")
                continue
            err = check_value(kind, v)
            if err:
                errors.append(f"{where}.{key}: {err}")


def parse_local(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None


def check_rules(feed, errors, warnings):
    yacht_ids = [y.get("yacht_id") for y in feed.get("yachts", []) if isinstance(y, dict)]
    known = set(yacht_ids)
    if len(known) != len(yacht_ids):
        errors.append("yachts: duplicate yacht_id")

    periods = feed.get("bookings") or feed.get("availability") or []
    name = "bookings" if "bookings" in feed else "availability"
    booking_ids = set()
    by_yacht = {}
    for i, p in enumerate(periods):
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
            bid = p.get("booking_id")
            if bid in booking_ids:
                errors.append(f"{where}: duplicate booking_id '{bid}'")
            booking_ids.add(bid)
            if p.get("category") == "hold" and not p.get("hold_expires"):
                errors.append(f"{where}: a hold needs hold_expires")
            if p.get("category") == "hold" and p.get("hold_expires") and UTC_TS.match(p["hold_expires"]):
                expires = datetime.strptime(p["hold_expires"][:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
                if expires < datetime.now(timezone.utc):
                    warnings.append(f"{where}: hold expired {p['hold_expires']}; a released hold must leave the feed or become booked")

    for yid, spans in by_yacht.items():
        spans.sort()
        for (s1, e1, w1), (s2, e2, w2) in zip(spans, spans[1:]):
            if s2 < e1:
                errors.append(f"{w2}: overlaps {w1} for yacht '{yid}'")

    for i, s in enumerate(feed.get("seasons", [])):
        if not isinstance(s, dict):
            continue
        if s.get("yacht_id") not in known:
            errors.append(f"seasons[{i}]: yacht_id '{s.get('yacht_id')}' is not in the yacht list")
        if isinstance(s.get("start_date"), str) and isinstance(s.get("end_date"), str) and s["end_date"] < s["start_date"]:
            errors.append(f"seasons[{i}]: end_date is before start_date")
        low, high = s.get("weekly_rate_low"), s.get("weekly_rate_high")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)) and high < low:
            errors.append(f"seasons[{i}]: weekly_rate_high is below weekly_rate_low")


def provided_level(feed):
    if "seasons" in feed and "bookings" in feed:
        return 4
    if "bookings" in feed:
        return 3
    if "availability" in feed:
        return 2
    return 1 if "yachts" in feed else 0


REQUIRED_KEYS = {1: {"yachts"}, 2: {"yachts", "availability"}, 3: {"yachts", "bookings"}, 4: {"yachts", "bookings", "seasons"}}


def validate(feed):
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
    elif "level" in feed:
        errors.append(f"level must be 1, 2, 3 or 4, found {level!r}")

    for name, fields in LISTS.items():
        if name in feed:
            if isinstance(feed[name], list):
                check_records(name, feed[name], fields, errors)
            else:
                errors.append(f"{name}: must be a list")
    check_rules(feed, errors, warnings)
    return errors, warnings, provided_level(feed)


def csv_cell(field, raw, fields):
    raw = raw.strip()
    if raw == "":
        return None
    kind = fields[field][1] if field in fields else "str"
    if kind == "str_list":
        return [x.strip() for x in raw.split(";") if x.strip()]
    if kind == "ports":
        ports = []
        for part in [x.strip() for x in raw.split(";") if x.strip()]:
            port, _, fee = part.partition("=")
            fee = fee.strip()
            ports.append({"port": port.strip(), "fee": float(fee) if fee.replace(".", "", 1).isdigit() else (fee or None)})
        return ports
    if field in INT_FIELDS:
        return int(raw) if raw.isdigit() else raw
    if field in NUM_FIELDS:
        try:
            return float(raw)
        except ValueError:
            return raw
    return raw


def load_sheet_folder(folder):
    tabs = {"Yachts": "yachts", "Availability": "availability", "Bookings": "bookings", "Seasons": "seasons"}
    feed = {"standard": "yacht-calendar-standard/0.1", "ca": folder.name,
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
    feed = load_sheet_folder(path) if path.is_dir() else json.loads(path.read_text(encoding="utf-8"))
    errors, warnings, level = validate(feed)
    names = {0: "none", 1: "Fleet", 2: "Availability", 3: "Calendar", 4: "Seasons and rates"}
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error:   {e}")
    status = "INVALID" if errors else "VALID"
    print(f"{status}: {path} provides level {level} ({names[level]}), {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
