#!/usr/bin/env python3
"""Rebuild examples/ and templates/google-sheet/ from the one sample fleet below.

Run after changing a field, so the examples, the sheet templates and the
schemas never drift apart. CI fails if the committed files differ from the
output of this script.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

YACHTS = [
    {
        "id": "EXY-001", "name": "Blue Horizon", "cya_id": "aaaaaaaaaaaaaaaaaaaa0001",
        "previous_names": ["Horizon Blue"], "type": "motor", "builder": "Westport", "model": "125",
        "year": 2008, "refit": 2023, "flag": "Cayman Islands",
        "length": 38.4, "beam": 7.6, "draft": 2.1, "cruising_speed": 18, "max_speed": 22,
        "range": 1800, "fuel_per_hour": 380,
        "guests": 10, "cabins": 5, "cabin_types": {"master": 1, "vip": 1, "double": 1, "twin": 2},
        "crew": 8, "home_port": "Lefkas Marina, Greece", "cruising_areas": ["Ionian", "Saronic"],
        "air_conditioning": True, "ac_at_night": True, "diving": False,
        "amenities": ["Wi-Fi", "Jacuzzi", "Gym", "Stabilisers at anchor"],
        "toys": ["Jet ski x2", "Seabob", "Paddleboard x2", "Water skis"],
        "description": "Tri-deck motor yacht with a beach club and a flybridge Jacuzzi.",
        "crew_description": "Captain and crew of eight, together since 2021.",
        "photos": ["https://example.com/photos/blue-horizon-1.jpg", "https://example.com/photos/blue-horizon-2.jpg"],
        "videos": ["https://example.com/videos/blue-horizon.mp4"],
        "brochure": "https://example.com/brochures/blue-horizon.pdf",
        "updated_at": "2026-10-20T08:00:00Z",
    },
    {
        "id": "EXY-002", "name": "Kalimera", "type": "gulet", "builder": "Bodrum Shipyard",
        "year": 2019, "length": 30.0, "guests": 12, "cabins": 6, "cabin_types": {"double": 4, "twin": 2},
        "crew": 5, "home_port": "Bodrum, Turkey", "updated_at": "2026-10-20T08:00:00Z",
    },
]

BOOKINGS = [
    {"id": "BK-2027-0142", "yacht_id": "EXY-001", "status": "booked", "start": "2027-07-10T12:00",
     "end": "2027-07-17T12:00", "timezone": "Europe/Athens", "pickup": "Argostoli, Greece",
     "dropoff": "Zakynthos, Greece", "updated_at": "2026-10-24T09:00:00Z"},
    {"id": "BK-2027-0150", "yacht_id": "EXY-001", "status": "hold", "start": "2027-07-18T12:00",
     "end": "2027-07-25T12:00", "timezone": "Europe/Athens", "pickup": "Zakynthos, Greece",
     "dropoff": "Lefkas Marina, Greece", "hold_expires": "2026-11-02T18:00:00Z", "updated_at": "2026-10-24T09:00:00Z"},
    {"id": "UN-2027-0003", "yacht_id": "EXY-002", "status": "unavailable", "start": "2027-04-01T09:00",
     "end": "2027-05-15T18:00", "timezone": "Europe/Istanbul", "pickup": "Bodrum, Turkey",
     "dropoff": "Bodrum, Turkey", "updated_at": "2026-10-22T14:30:00Z"},
]

SEASONS = [
    {"yacht_id": "EXY-001", "name": "High Season", "start": "2027-07-01", "end": "2027-08-31",
     "base_port": "Lefkas Marina, Greece", "cruising_areas": ["Ionian"],
     "relocation_ports": [{"port": "Corfu, Greece", "fee": 4500}, {"port": "Zakynthos, Greece"}],
     "turnaround_hours": 24, "min_nights": 7, "currency": "EUR", "weekly_rate_from": 108000,
     "weekly_rate_to": 120000, "vat": 5.2, "apa": 35, "terms": "plus_expenses"},
    {"yacht_id": "EXY-002", "name": "Summer", "start": "2027-05-16", "end": "2027-10-15",
     "base_port": "Bodrum, Turkey", "cruising_areas": ["Turkish Riviera", "Dodecanese"],
     "relocation_ports": [{"port": "Göcek, Turkey", "fee": 2000}], "turnaround_hours": 24, "min_nights": 7,
     "currency": "EUR", "weekly_rate_from": 28000, "vat": 0, "apa": 20, "terms": "inclusive",
     "holidays": "Kurban Bayrami week 16-23 May 2027, flat 32000"},
]

AVAILABILITY = [{k: b[k] for k in ("yacht_id", "start", "end", "timezone", "status")} for b in BOOKINGS]

# Sheet columns, in order. Every field the schema allows, so a CA sees them all.
COLUMNS = {
    "Yachts": ["id", "name", "cya_id", "previous_names", "type", "builder", "model", "year", "refit", "flag",
               "length", "beam", "draft", "cruising_speed", "max_speed", "range", "fuel_per_hour",
               "guests", "cabins", "cabin_types", "crew", "home_port", "cruising_areas",
               "air_conditioning", "ac_at_night", "diving", "amenities", "toys", "description",
               "crew_description", "photos", "videos", "brochure", "updated_at"],
    "Availability": ["yacht_id", "start", "end", "timezone", "status"],
    "Bookings": ["id", "yacht_id", "status", "start", "end", "timezone", "pickup", "dropoff",
                 "hold_expires", "updated_at"],
    "Seasons": ["yacht_id", "name", "start", "end", "base_port", "cruising_areas", "relocation_ports",
                "turnaround_hours", "min_nights", "currency", "weekly_rate_from", "weekly_rate_to",
                "vat", "apa", "terms", "holidays"],
}
ROWS = {"Yachts": YACHTS, "Availability": AVAILABILITY, "Bookings": BOOKINGS, "Seasons": SEASONS}
LEVEL_TABS = {1: ["Yachts"], 2: ["Yachts", "Availability"], 3: ["Yachts", "Bookings"], 4: ["Yachts", "Bookings", "Seasons"]}
LEVEL_KEYS = {1: {"yachts": YACHTS}, 2: {"yachts": YACHTS, "availability": AVAILABILITY},
              3: {"yachts": YACHTS, "bookings": BOOKINGS}, 4: {"yachts": YACHTS, "bookings": BOOKINGS, "seasons": SEASONS}}


def cell(v):
    """JSON value -> sheet cell, following SPEC.md section 8."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, dict):  # cabin_types
        return "; ".join(f"{k} = {n}" for k, n in v.items())
    if isinstance(v, list):
        return "; ".join(x if isinstance(x, str) else x["port"] + (f" = {x['fee']}" if "fee" in x else "") for x in v)
    return str(v)


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build():
    head = {"standard": "yacht-calendar-standard/0.2", "ca": "Example Yachts Ltd", "generated_at": "2026-10-24T09:00:00Z"}
    for level, lists in LEVEL_KEYS.items():
        write_json(ROOT / f"examples/feed-level-{level}.json", {**head, "level": level, **lists})
        folder = ROOT / f"templates/google-sheet/level-{level}"
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("*.csv"):
            old.unlink()
        for tab in LEVEL_TABS[level]:
            with (folder / f"{tab}.csv").open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(COLUMNS[tab])
                for row in ROWS[tab]:
                    w.writerow([cell(row.get(c)) for c in COLUMNS[tab]])
    write_json(ROOT / "examples/key.json", {
        "ca": "Example Yachts Ltd", "partner": "Example Broker", "level": 3,
        "scopes": ["fleet:read", "availability:read", "calendar:read"],
        "yacht_ids": ["EXY-001"], "expires_at": "2027-12-31T23:59:59Z"})


if __name__ == "__main__":
    build()
    print("examples and templates rebuilt")
