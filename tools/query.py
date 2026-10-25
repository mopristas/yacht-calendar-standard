#!/usr/bin/env python3
"""Answer a broker's questions from a Yacht Calendar Standard feed.

The same functions back the MCP server (mcp/server.py) and the AI-friendly
HTTP endpoints, so every client gets the same answers. Each answer is a dict
that starts with a one-line `summary` and ends with the `rules` a reader must
follow. Standard library only.

    python3 tools/query.py examples/feed-as-dma.json search 2027-07-10 2027-07-17 --guests 8
    python3 tools/query.py examples/feed-as-dma.json routes Zakynthos
"""
import argparse
import csv
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from resolve import add_months  # noqa: E402
from validate import LISTS, csv_cell, load_sheet_folder  # noqa: E402

PRESETS = {
    1: {"profile": "full", "calendar": "none", "rates": "none"},
    2: {"profile": "full", "calendar": "status", "rates": "none"},
    3: {"profile": "full", "calendar": "full", "rates": "none"},
    4: {"profile": "full", "calendar": "full", "rates": "full"},
}
TAKEN = {"booked", "unavailable", "busy"}
STATUS_ORDER = ["free", "on_hold", "no_calendar", "beyond_window", "taken"]


class QueryError(ValueError):
    pass


def rules(ca):
    return [
        f"An open date means no booking is recorded, not that the yacht is available. Confirm the week and the price with {ca} before quoting a client.",
        "This calendar data is internal. Never show the feed, its link, these results or a screenshot of them to a client.",
        "A yacht that is not listed is not shared with you. Do not guess about it.",
    ]


# ---------------------------------------------------------------- loading

SHEET = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)")


def _get(url, key=None):
    headers = {"Accept": "application/json, text/csv", "User-Agent": "yacht-calendar-standard/0.4"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return r.read().decode("utf-8-sig")


def _sheet_tab(sheet_id, tab, list_name):
    """One tab of a public Google Sheet, or None if the sheet has no such tab.

    gviz falls back to the first tab for an unknown name, so the header row is
    checked against the tab's own fields before it is trusted.
    """
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={urllib.parse.quote(tab)}"
    rows = list(csv.DictReader(io.StringIO(_get(url))))
    fields = LISTS[list_name]
    header = set(rows[0]) if rows else set()
    required = {k for k, (req, _) in fields.items() if req}
    if not rows or not header <= set(fields) or not required <= header:
        return None
    return [{k: csv_cell(k, v or "", fields) for k, v in r.items()} for r in rows]


def load_source(source, key=None):
    """A feed from a file, a folder of sheet CSVs, a Google Sheet, a feed URL or an API base URL."""
    path = Path(source)
    if path.is_dir():
        return load_sheet_folder(path)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    m = SHEET.search(source)
    if m:
        feed = {"standard": "yacht-calendar-standard/0.4", "ca": "Google Sheet",
                "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
        for tab, name in (("Yachts", "yachts"), ("Availability", "availability"), ("Bookings", "bookings"), ("Seasons", "seasons")):
            rows = _sheet_tab(m.group(1), tab, name)
            if rows is not None:
                feed[name] = rows
        feed["level"] = 4 if "seasons" in feed else 3 if "bookings" in feed else 2 if "availability" in feed else 1
        return feed
    if source.startswith(("http://", "https://")):
        url = source.rstrip("/") + "/feed" if source.rstrip("/").endswith("/v1") else source
        return json.loads(_get(url, key))
    raise QueryError(f"cannot read source '{source}'")


def normalise(feed):
    """Give every yacht an `access`, whatever level the feed was published at."""
    level = feed.get("level")
    if level != "per_yacht":
        preset = PRESETS.get(level)
        if not preset:
            raise QueryError(f"unknown feed level {level!r}")
        for y in feed["yachts"]:
            y.setdefault("access", dict(preset))
    return feed


# ---------------------------------------------------------------- helpers

def _date(s, label):
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        raise QueryError(f"{label} must be a date like 2027-07-10, got {s!r}") from None


def _n(count, word):
    plural = word + ("es" if word.endswith("ch") else "s")
    return f"{count} {word if count == 1 else plural}"


def _fmt(d):
    return f"{d.day} {d:%b %Y}"


def _periods(feed, yacht_id):
    """(start_date, end_date, record) for one yacht, from whichever list the feed has."""
    out = []
    for name in ("bookings", "availability"):
        for p in feed.get(name) or []:
            if p.get("yacht_id") == yacht_id:
                out.append((_date(p["start"], "start"), _date(p["end"], "end"), p))
    return sorted(out, key=lambda t: t[0])


def _find_yacht(feed, yacht):
    want = str(yacht).strip().lower()
    for y in feed["yachts"]:
        if y["id"].lower() == want or y["name"].lower() == want:
            return y
    matches = [y for y in feed["yachts"] if want and want in y["name"].lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise QueryError(f"'{yacht}' matches several yachts: {', '.join(y['name'] for y in matches)}. Use the id.")
    raise QueryError(f"no yacht '{yacht}' is shared with you")


def _areas(feed, y):
    names = list(y.get("cruising_areas", [])) + [y.get("home_port", "")]
    for s in feed.get("seasons") or []:
        if s["yacht_id"] == y["id"]:
            names += s.get("cruising_areas", []) + [s.get("base_port", "")]
            names += [r["port"] for r in s.get("relocation_ports", [])]
    return [n for n in names if n]


def _season(feed, yacht_id, day):
    for s in feed.get("seasons") or []:
        if s["yacht_id"] == yacht_id and _date(s["start"], "start") <= day <= _date(s["end"], "end"):
            return s
    return None


def _rate(season):
    if not season:
        return None
    out = {"season": season["name"], "base_port": season["base_port"]}
    if "weekly_rate_from" in season:
        out.update({k: season[k] for k in ("currency", "weekly_rate_from", "weekly_rate_to", "vat", "apa", "terms", "holidays") if k in season})
    return out


def _brief(y):
    return {k: y[k] for k in ("id", "name", "length", "guests", "cabins", "type", "builder", "year") if k in y}


def _window_end(y, today):
    months = y["access"].get("months_ahead")
    return add_months(today, months) if months else None


# ---------------------------------------------------------------- the tools

def my_access(feed, today=None):
    """What this key can see, per yacht."""
    today = today or date.today()
    yachts = [{"id": y["id"], "name": y["name"], **y["access"]} for y in feed["yachts"]]
    with_cal = sum(1 for y in yachts if y["calendar"] != "none")
    with_rates = sum(1 for y in yachts if y["rates"] == "full")
    return {
        "summary": f"You can see {_n(len(yachts), 'yacht')} from {feed['ca']}: {with_cal} with a calendar, {with_rates} with prices.",
        "ca": feed["ca"],
        "levels": {
            "calendar": "busy = taken dates only; status = booked / hold / unavailable; full = bookings with pickup and drop-off ports",
            "rates": "seasons = base port and areas, no prices; full = weekly rates, VAT, APA",
        },
        "yachts": yachts,
        "rules": rules(feed["ca"]),
    }


def search_available(feed, start, end, guests=None, area=None, yacht_type=None, min_length=None,
                     max_length=None, include_taken=False, today=None):
    """Which yachts are free from start to end, with the filters given."""
    today = today or date.today()
    start, end = _date(start, "start"), _date(end, "end")
    if end <= start:
        raise QueryError("end must be after start")
    results, skipped = [], {"too_small": 0, "other_type": 0, "other_area": 0, "area_unknown": 0, "length": 0}
    for y in feed["yachts"]:
        if guests and y["guests"] < int(guests):
            skipped["too_small"] += 1
            continue
        if (min_length and y["length"] < float(min_length)) or (max_length and y["length"] > float(max_length)):
            skipped["length"] += 1
            continue
        if yacht_type and y.get("type") and y["type"] != yacht_type:
            skipped["other_type"] += 1
            continue
        if area:
            places = _areas(feed, y)
            if not places:
                skipped["area_unknown"] += 1
                continue
            if not any(area.lower() in p.lower() for p in places):
                skipped["other_area"] += 1
                continue
        item = _brief(y)
        access = y["access"]
        window_end = _window_end(y, today)
        periods = _periods(feed, y["id"])
        clashes = [p for s, e, p in periods if s < end and e > start]
        if access["calendar"] == "none":
            item["status"] = "no_calendar"
            item["note"] = "Calendar not shared with you. Ask the CA."
        elif window_end and end > window_end:
            item["status"] = "beyond_window"
            item["note"] = f"You can only see bookings up to {_fmt(window_end)}."
        elif any(p["status"] in TAKEN for p in clashes):
            item["status"] = "taken"
        elif clashes:
            item["status"] = "on_hold"
            expiry = [p.get("hold_expires") for p in clashes if p.get("hold_expires")]
            item["note"] = "Held by someone else" + (f" until {expiry[0]}" if expiry else "") + ". May come free."
        else:
            item["status"] = "free"
            item["note"] = "No booking recorded on these dates."
        if access["calendar"] == "full" and item["status"] in ("free", "on_hold"):
            before = [(e, p) for s, e, p in periods if e <= start]
            after = [(s, p) for s, e, p in periods if s >= end]
            if before:
                e, p = before[-1]
                item["before"] = f"Previous charter ends {_fmt(e)} in {p['dropoff']}"
            if after:
                s, p = after[0]
                item["after"] = f"Next charter starts {_fmt(s)} in {p['pickup']}"
        rate = _rate(_season(feed, y["id"], start))
        if rate:
            item["rate"] = rate
        results.append(item)

    counts = {s: sum(1 for r in results if r["status"] == s) for s in STATUS_ORDER}
    shown = [r for r in results if include_taken or r["status"] != "taken"]
    shown.sort(key=lambda r: (STATUS_ORDER.index(r["status"]), -r["length"]))
    filters = ", ".join(f for f in [
        f"{guests}+ guests" if guests else "", area or "", yacht_type or "",
        f"{min_length}+ m" if min_length else "", f"up to {max_length} m" if max_length else ""] if f)
    parts = [f"{counts['free']} free"]
    parts += [f"{counts[k]} {label}" for k, label in (("on_hold", "on hold"), ("taken", "taken"),
              ("no_calendar", "with no calendar shared"), ("beyond_window", "beyond your calendar window")) if counts[k]]
    summary = f"{_fmt(start)} to {_fmt(end)}{' (' + filters + ')' if filters else ''}: {_n(len(results), 'yacht')} match" + ("es" if len(results) == 1 else "") + ", " + ", ".join(parts) + "."
    if counts["free"]:
        summary += " Free means no booking recorded; confirm with the CA before quoting."
    out = {"summary": summary, "counts": counts, "yachts": shown}
    if any(skipped.values()):
        out["filtered_out"] = {k: v for k, v in skipped.items() if v}
    out["rules"] = rules(feed["ca"])
    return out


def find_routes(feed, place, start=None, end=None, today=None):
    """Yachts already starting, ending, based or cruising at a port or area."""
    today = today or date.today()
    start = _date(start, "start") if start else today
    end = _date(end, "end") if end else start + timedelta(days=365)
    needle = place.lower()
    hits = []
    for y in feed["yachts"]:
        periods = _periods(feed, y["id"])
        if y["access"]["calendar"] == "full":
            for i, (s, e, p) in enumerate(periods):
                nxt = periods[i + 1][0] if i + 1 < len(periods) else None
                prev = periods[i - 1] if i else None
                if needle in p["dropoff"].lower() and start <= e <= end:
                    hits.append({"date": e.isoformat(), "yacht": _brief(y), "kind": "ends_here", "port": p["dropoff"],
                                 "text": f"{y['name']} ends a charter in {p['dropoff']} on {_fmt(e)}"
                                         + (f"; next booking starts {_fmt(nxt)}" if nxt else "; nothing booked after")})
                if needle in p["pickup"].lower() and start <= s <= end:
                    hits.append({"date": s.isoformat(), "yacht": _brief(y), "kind": "starts_here", "port": p["pickup"],
                                 "text": f"{y['name']} starts a charter in {p['pickup']} on {_fmt(s)}"
                                         + (f"; previous charter ends {_fmt(prev[1])} in {prev[2]['dropoff']}" if prev else "; nothing booked before")})
        for s in feed.get("seasons") or []:
            if s["yacht_id"] != y["id"] or _date(s["end"], "end") < start or _date(s["start"], "start") > end:
                continue
            where = [s["base_port"]] + s.get("cruising_areas", []) + [r["port"] for r in s.get("relocation_ports", [])]
            match = next((w for w in where if needle in w.lower()), None)
            if match:
                hits.append({"date": s["start"], "yacht": _brief(y), "kind": "season", "port": match,
                             "text": f"{y['name']} is based in {s['base_port']} for {s['name']} ({_fmt(_date(s['start'], 's'))} to {_fmt(_date(s['end'], 'e'))}), cruising {', '.join(s['cruising_areas'])}"})
    hits.sort(key=lambda h: h["date"])
    no_ports = sum(1 for y in feed["yachts"] if y["access"]["calendar"] != "full")
    summary = f"{_n(len(hits), 'match')} for '{place}' between {_fmt(start)} and {_fmt(end)}."
    if no_ports:
        summary += (f" {_n(no_ports, 'yacht')} {'does' if no_ports == 1 else 'do'} not share"
                    f" {'its' if no_ports == 1 else 'their'} ports with you, so {'it' if no_ports == 1 else 'they'} cannot show here.")
    return {"summary": summary, "matches": hits, "rules": rules(feed["ca"])}


def get_yacht(feed, yacht):
    y = _find_yacht(feed, yacht)
    record = {k: v for k, v in y.items() if k != "access"}
    return {"summary": f"{y['name']}: {y['length']} m, {y['guests']} guests, {y['cabins']} cabins.",
            "yacht": record, "access": y["access"], "rules": rules(feed["ca"])}


def get_calendar(feed, yacht, start=None, end=None, today=None):
    today = today or date.today()
    y = _find_yacht(feed, yacht)
    if y["access"]["calendar"] == "none":
        return {"summary": f"{y['name']}'s calendar is not shared with you.", "periods": [], "rules": rules(feed["ca"])}
    start = _date(start, "start") if start else today
    end = _date(end, "end") if end else start + timedelta(days=548)
    periods = [p for s, e, p in _periods(feed, y["id"]) if s < end and e > start]
    window_end = _window_end(y, today)
    summary = f"{y['name']}: {_n(len(periods), 'booked or held period')} between {_fmt(start)} and {_fmt(end)}."
    if window_end:
        summary += f" You can see bookings up to {_fmt(window_end)} only."
    return {"summary": summary, "calendar_level": y["access"]["calendar"], "periods": periods, "rules": rules(feed["ca"])}


def get_rate(feed, yacht, start, end=None):
    y = _find_yacht(feed, yacht)
    if y["access"]["rates"] == "none":
        return {"summary": f"{y['name']}'s rates are not shared with you.", "rules": rules(feed["ca"])}
    day = _date(start, "start")
    season = _season(feed, y["id"], day)
    if not season:
        return {"summary": f"No season covers {_fmt(day)} for {y['name']}.", "rules": rules(feed["ca"])}
    rate = _rate(season)
    nights = (_date(end, "end") - day).days if end else 7
    if "weekly_rate_from" in rate:
        price = f"{rate['currency']} {rate['weekly_rate_from']:,}" + (f" to {rate['weekly_rate_to']:,}" if rate.get("weekly_rate_to") else "")
        summary = (f"{y['name']}, {season['name']}: {price} per week plus {rate['vat']}% VAT"
                   f"{' and ' + str(rate['apa']) + '% APA' if rate['terms'] == 'plus_expenses' else ''} ({rate['terms'].replace('_', ' ')}), based in {season['base_port']}.")
        if nights != 7:
            summary += f" For {nights} nights, ask the CA: pro rata is not guaranteed."
        if season.get("min_nights") and nights < season["min_nights"]:
            summary += f" Minimum stay is {season['min_nights']} nights."
    else:
        summary = f"{y['name']}, {season['name']}: based in {season['base_port']}. Prices are not shared with you."
    return {"summary": summary, "rate": rate, "rules": rules(feed["ca"])}


# ---------------------------------------------------------------- CLI

def main(argv):
    ap = argparse.ArgumentParser(description="Ask a feed a broker's question.")
    ap.add_argument("source", help="Feed file, sheet CSV folder, Google Sheet URL, feed URL or API base URL")
    ap.add_argument("--key", help="Bearer key for a URL source")
    ap.add_argument("--today", help="Answer as of this date")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("access")
    s = sub.add_parser("search")
    s.add_argument("start"); s.add_argument("end")
    s.add_argument("--guests", type=int); s.add_argument("--area"); s.add_argument("--type")
    s.add_argument("--min-length", type=float); s.add_argument("--max-length", type=float)
    s.add_argument("--include-taken", action="store_true")
    r = sub.add_parser("routes")
    r.add_argument("place"); r.add_argument("--start"); r.add_argument("--end")
    for name in ("yacht", "calendar"):
        p = sub.add_parser(name)
        p.add_argument("yacht")
        if name == "calendar":
            p.add_argument("--start"); p.add_argument("--end")
    p = sub.add_parser("rate")
    p.add_argument("yacht"); p.add_argument("start"); p.add_argument("--end")
    a = ap.parse_args(argv[1:])
    today = _date(a.today, "today") if a.today else date.today()
    feed = normalise(load_source(a.source, a.key))
    try:
        out = {
            "access": lambda: my_access(feed, today),
            "search": lambda: search_available(feed, a.start, a.end, a.guests, a.area, a.type, a.min_length,
                                               a.max_length, a.include_taken, today),
            "routes": lambda: find_routes(feed, a.place, a.start, a.end, today),
            "yacht": lambda: get_yacht(feed, a.yacht),
            "calendar": lambda: get_calendar(feed, a.yacht, getattr(a, "start", None), getattr(a, "end", None), today),
            "rate": lambda: get_rate(feed, a.yacht, a.start, a.end),
        }[a.cmd]()
    except QueryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
