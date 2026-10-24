#!/usr/bin/env python3
"""Self-test: sheet templates read back as the JSON examples, and bad feeds are caught."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import load_sheet_folder, validate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
failed = 0


def check(label, ok):
    global failed
    print(f"{'ok  ' if ok else 'FAIL'} {label}")
    failed += not ok


for level in (1, 2, 3, 4):
    sheet = load_sheet_folder(ROOT / f"templates/google-sheet/level-{level}")
    feed = json.loads((ROOT / f"examples/feed-level-{level}.json").read_text())
    for key in ("yachts", "availability", "bookings", "seasons"):
        if key in feed:
            rows = [{k: v for k, v in r.items() if v is not None} for r in sheet[key]]
            check(f"level {level} sheet {key} == JSON", rows == feed[key])

base = json.loads((ROOT / "examples/feed-level-4.json").read_text())
BAD = {
    "hold without hold_expires": lambda f: f["bookings"][1].pop("hold_expires"),
    "overlapping bookings": lambda f: f["bookings"][1].update(start="2027-07-15T12:00"),
    "client name": lambda f: f["bookings"][0].update(client_name="X"),
    "port without country": lambda f: f["bookings"][2].update(pickup="Bodrum"),
    "cabin types do not add up": lambda f: f["yachts"][0]["cabin_types"].update(twin=3),
    "unknown yacht": lambda f: f["seasons"][0].update(yacht_id="NOPE"),
    "null instead of left out": lambda f: f["yachts"][1].update(beam=None),
    "level 4 with availability": lambda f: f.update(availability=[]),
}
for label, breaker in BAD.items():
    bad = copy.deepcopy(base)
    breaker(bad)
    errors, _, _ = validate(bad)
    check(f"catches: {label}", bool(errors))

sys.exit(1 if failed else 0)
