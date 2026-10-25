#!/usr/bin/env python3
"""Reference resolver: what does one key see?

Usage:
    python3 tools/resolve.py SHARING.json FULL_FEED.json --key KEY_ID [--date YYYY-MM-DD] [--explain]

SHARING.json is the publisher's sharing setup (schema/sharing.schema.json).
FULL_FEED.json is the publisher's own complete level 4 feed.
Prints the per_yacht feed that key would receive, or with --explain a table of
each yacht's access and the shares that decided it. The rules are in SHARING.md.
Standard library only.
"""
import argparse
import json
import sys
from datetime import date, datetime, timezone

PROFILE = ["none", "basic", "full"]
CALENDAR = ["none", "busy", "status", "full"]
RATES = ["none", "seasons", "full"]
PARTS = {"profile": PROFILE, "calendar": CALENDAR, "rates": RATES}
BASIC_FIELDS = ("id", "name", "length", "guests", "cabins")
PRICE_FIELDS = ("currency", "weekly_rate_from", "weekly_rate_to", "vat", "apa", "terms", "holidays")
WHO_RANK = {"recipient": 3, "company": 2, "group": 1}


class SharingError(ValueError):
    pass


def check_setup(setup, yacht_ids):
    """Reject references that point nowhere, and block shares that are only half a block."""
    recipients = {r["id"]: r for r in setup["recipients"]}
    groups = {g["id"] for g in setup["groups"]}
    sets = {s["id"] for s in setup["boat_sets"]}
    problems = []
    for r in setup["recipients"]:
        if r.get("company") and recipients.get(r["company"], {}).get("type") != "company":
            problems.append(f"recipient {r['id']}: company '{r['company']}' is not a company recipient")
        problems += [f"recipient {r['id']}: unknown group '{g}'" for g in r.get("groups", []) if g not in groups]
    for s in setup["boat_sets"]:
        problems += [f"boat set {s['id']}: unknown yacht '{y}'" for y in s.get("yacht_ids", []) if y not in yacht_ids]
    for sh in setup["shares"]:
        to, boats = sh["to"], sh["boats"]
        if "group" in to and to["group"] not in groups:
            problems.append(f"share {sh['id']}: unknown group '{to['group']}'")
        if "recipient" in to and to["recipient"] not in recipients:
            problems.append(f"share {sh['id']}: unknown recipient '{to['recipient']}'")
        if "set" in boats and boats["set"] not in sets:
            problems.append(f"share {sh['id']}: unknown boat set '{boats['set']}'")
        if "yacht" in boats and boats["yacht"] not in yacht_ids:
            problems.append(f"share {sh['id']}: unknown yacht '{boats['yacht']}'")
        if sh["profile"] == "none" and (sh["calendar"] != "none" or sh["rates"] != "none"):
            problems.append(f"share {sh['id']}: profile 'none' is a block, so calendar and rates must be 'none' too")
    for k in setup["keys"]:
        if k["recipient"] not in recipients:
            problems.append(f"key {k['id']}: unknown recipient '{k['recipient']}'")
    if problems:
        raise SharingError("; ".join(problems))
    return recipients


def in_set(yacht, boat_set):
    if "yacht_ids" in boat_set:
        return yacht["id"] in boat_set["yacht_ids"]
    rule = boat_set["rule"]
    areas = {a.lower() for a in yacht.get("cruising_areas", [])}
    return all([
        rule.get("all", True),
        "cruising_area" not in rule or rule["cruising_area"].lower() in areas,
        "type" not in rule or yacht.get("type") == rule["type"],
        "min_length" not in rule or yacht["length"] >= rule["min_length"],
        "max_length" not in rule or yacht["length"] <= rule["max_length"],
        "min_guests" not in rule or yacht["guests"] >= rule["min_guests"],
    ])


def who_rank(share, recipient, groups):
    to = share["to"]
    if to.get("recipient") == recipient["id"]:
        return WHO_RANK["recipient"]
    if recipient.get("company") and to.get("recipient") == recipient["company"]:
        return WHO_RANK["company"]
    if to.get("group") in groups:
        return WHO_RANK["group"]
    return 0


def active(share, today):
    return share.get("valid_from", "0000-00-00") <= today.isoformat() <= share.get("valid_until", "9999-12-31")


def resolve_access(setup, feed, key_id, today):
    """Return {yacht_id: {"profile", "calendar", "rates", "months_ahead", "shares"}} for one key."""
    yachts = {y["id"]: y for y in feed["yachts"]}
    recipients = check_setup(setup, set(yachts))
    key = next((k for k in setup["keys"] if k["id"] == key_id), None)
    now = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    if key is None or key.get("revoked") or (
        key.get("expires_at") and datetime.strptime(key["expires_at"][:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc) < now
    ):
        raise SharingError("invalid_key")
    recipient = recipients[key["recipient"]]
    company = recipients.get(recipient.get("company"), {})
    groups = set(recipient.get("groups", [])) | set(company.get("groups", []))
    sets = {s["id"]: s for s in setup["boat_sets"]}

    result = {}
    for yid, yacht in yachts.items():
        candidates = []
        for sh in setup["shares"]:
            who = who_rank(sh, recipient, groups)
            if not who or not active(sh, today):
                continue
            boats = sh["boats"]
            if boats.get("yacht") == yid:
                candidates.append(((who, 2), sh))
            elif "set" in boats and in_set(yacht, sets[boats["set"]]):
                candidates.append(((who, 1), sh))
        if not candidates:
            continue
        top = max(rank for rank, _ in candidates)
        winners = [sh for rank, sh in candidates if rank == top]
        access = {part: max((sh[part] for sh in winners), key=levels.index) for part, levels in PARTS.items()}
        if access["profile"] == "none":
            continue  # blocked
        windows = [sh.get("calendar_window", {}).get("months_ahead") for sh in winners if sh["calendar"] == access["calendar"]]
        access["months_ahead"] = None if None in windows else max(windows)
        access["shares"] = [sh["id"] for sh in winners]
        result[yid] = access
    return result


def add_months(d, months):
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue


def build_feed(setup, feed, key_id, today, generated_at=None):
    access = resolve_access(setup, feed, key_id, today)
    out = {
        "standard": "yacht-calendar-standard/0.3",
        "ca": setup["publisher"]["name"],
        "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "level": "per_yacht",
        "yachts": [],
    }
    for y in feed["yachts"]:
        a = access.get(y["id"])
        if not a:
            continue
        record = dict(y) if a["profile"] == "full" else {k: y[k] for k in BASIC_FIELDS}
        record["access"] = {p: a[p] for p in PARTS}
        out["yachts"].append(record)

    def in_window(period):
        months = access[period["yacht_id"]]["months_ahead"]
        return months is None or period["start"][:10] < add_months(today, months).isoformat()

    levels = {a["calendar"] for a in access.values()}
    if levels & {"busy", "status"}:
        out["availability"] = [
            {"yacht_id": b["yacht_id"], "start": b["start"], "end": b["end"], "timezone": b["timezone"],
             "status": "busy" if access[b["yacht_id"]]["calendar"] == "busy" else b["status"]}
            for b in feed.get("bookings", [])
            if access.get(b["yacht_id"], {}).get("calendar") in ("busy", "status") and in_window(b)
        ]
    if "full" in levels:
        out["bookings"] = [b for b in feed.get("bookings", [])
                           if access.get(b["yacht_id"], {}).get("calendar") == "full" and in_window(b)]
    if {a["rates"] for a in access.values()} - {"none"}:
        out["seasons"] = []
        for s in feed.get("seasons", []):
            rates = access.get(s["yacht_id"], {}).get("rates", "none")
            if rates == "full":
                out["seasons"].append(s)
            elif rates == "seasons":
                out["seasons"].append({k: v for k, v in s.items() if k not in PRICE_FIELDS})
    return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("sharing")
    ap.add_argument("feed")
    ap.add_argument("--key", required=True)
    ap.add_argument("--date", help="Resolve as of this date (default today, UTC)")
    ap.add_argument("--explain", action="store_true", help="Show each yacht's access and the deciding shares")
    args = ap.parse_args(argv[1:])
    setup = json.load(open(args.sharing, encoding="utf-8"))
    feed = json.load(open(args.feed, encoding="utf-8"))
    today = date.fromisoformat(args.date) if args.date else datetime.now(timezone.utc).date()
    try:
        if args.explain:
            access = resolve_access(setup, feed, args.key, today)
            names = {y["id"]: y["name"] for y in feed["yachts"]}
            print(f"{'yacht':<24} {'profile':<8} {'calendar':<9} {'rates':<8} {'window':<8} shares")
            for y in feed["yachts"]:
                a = access.get(y["id"])
                label = f"{y['id']} {names[y['id']]}"[:24]
                if not a:
                    print(f"{label:<24} not shared")
                    continue
                window = f"{a['months_ahead']} mo" if a["months_ahead"] else "all"
                print(f"{label:<24} {a['profile']:<8} {a['calendar']:<9} {a['rates']:<8} {window:<8} {', '.join(a['shares'])}")
        else:
            print(json.dumps(build_feed(setup, feed, args.key, today), indent=2, ensure_ascii=False))
    except SharingError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
