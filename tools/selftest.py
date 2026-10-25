#!/usr/bin/env python3
"""Self-test: sheet templates read back as the JSON examples, and bad feeds are caught."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import load_sheet_folder, validate  # noqa: E402
from resolve import SharingError, build_feed, resolve_access  # noqa: E402
from datetime import date  # noqa: E402

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

# Sharing: the worked example in SHARING.md
setup = json.loads((ROOT / "examples/sharing.json").read_text())
full = base
day = date(2026, 10, 24)


def access(key, when=day, s=setup):
    return {y: (a["profile"], a["calendar"], a["rates"]) for y, a in resolve_access(s, full, key, when).items()}


dma, maria, acme = access("K-DMA-1"), access("K-MARIA-1"), access("K-ACME-1")
check("group shares add up: DMA gets the Ionian boat in full", dma["EXY-001"] == ("full", "full", "full"))
check("everyone else's boats stay busy-only", dma["EXY-002"] == ("full", "busy", "none"))
check("person beats company: Maria sees Sirocco with status and seasons", maria["EXY-007"] == ("full", "status", "seasons"))
check("person share does not leak to her company", dma["EXY-007"] == ("full", "busy", "none"))
check("block hides the boat completely", "EXY-007" not in acme)
check("Maria's share ends on valid_until", access("K-MARIA-1", date(2027, 10, 1))["EXY-007"] == ("full", "busy", "none"))
as_dma = build_feed(setup, full, "K-DMA-1", day, "2026-10-24T09:00:00Z")
check("18-month window drops the 2028 booking", "BK-2028-0007" not in [b["id"] for b in as_dma["bookings"]])
check("busy hides booked/hold", {a["status"] for a in as_dma["availability"]} == {"busy"})
as_maria = build_feed(setup, full, "K-MARIA-1", day, "2026-10-24T09:00:00Z")
sirocco_season = [x for x in as_maria["seasons"] if x["yacht_id"] == "EXY-007"][0]
check("rates 'seasons' strips prices", "weekly_rate_from" not in sirocco_season)
for name, f in (("dma", as_dma), ("maria", as_maria)):
    check(f"resolved feed for {name} validates", not validate(f)[0])

basic = copy.deepcopy(setup)
basic["shares"][0]["profile"] = "basic"
y = [x for x in build_feed(basic, full, "K-ACME-1", day)["yachts"] if x["id"] == "EXY-002"][0]
check("profile 'basic' keeps only the five core fields", set(y) == {"id", "name", "length", "guests", "cabins", "access"})

for label, breaker in {
    "revoked key": lambda s: s["keys"][2].update(revoked=True),
    "expired key": lambda s: s["keys"][2].update(expires_at="2026-01-01T00:00:00Z"),
    "share to an unknown group": lambda s: s["shares"][0]["to"].update(group="G-NOPE"),
    "half a block": lambda s: s["shares"][3].update(calendar="busy"),
}.items():
    broken = copy.deepcopy(setup)
    breaker(broken)
    try:
        resolve_access(broken, full, "K-ACME-1", day)
        check(f"rejects: {label}", False)
    except SharingError:
        check(f"rejects: {label}", True)

leaky = copy.deepcopy(as_dma)
leaky["bookings"].append(dict(full["bookings"][2]))
check("validator catches a booking leaked to a busy-only yacht", bool(validate(leaky)[0]))

sys.exit(1 if failed else 0)
