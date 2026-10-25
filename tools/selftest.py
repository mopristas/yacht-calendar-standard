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

# Query layer: the answers an AI relays
import query  # noqa: E402
qd, qm, qa = (query.normalise(json.loads((ROOT / f"examples/feed-as-{n}.json").read_text())) for n in ("dma", "maria", "acme"))
r = query.search_available(qd, "2027-07-10", "2027-07-17", today=day)
check("search: booked boat is taken, others free", r["counts"]["taken"] == 1 and r["counts"]["free"] == 2)
check("search: summary carries the confirm-with-CA rule", "confirm with the CA" in r["summary"] and r["rules"])
r = query.search_available(qd, "2027-07-03", "2027-07-10", today=day)
bh = [y for y in r["yachts"] if y["id"] == "EXY-001"][0]
check("search: full calendar shows where she goes next", "Argostoli" in bh.get("after", ""))
check("search: weekly rate attached when shared", bh["rate"]["weekly_rate_from"] == 108000)
check("search: hold shows as on_hold", query.search_available(qd, "2027-07-19", "2027-07-24", today=day)["counts"]["on_hold"] == 1)
check("search: beyond the 18-month window is flagged",
      query.search_available(qd, "2028-07-01", "2028-07-08", today=day)["counts"]["beyond_window"] == 1)
check("search: guests filter", all(y["guests"] >= 11 for y in query.search_available(qd, "2027-09-01", "2027-09-08", guests=11, today=day)["yachts"]))
routes = query.find_routes(qm, "Zakynthos", today=day)
check("routes: finds the charter ending and starting in Zakynthos", {m["kind"] for m in routes["matches"]} >= {"ends_here", "starts_here"})
check("routes: busy-only partner sees no ports", not query.find_routes(qa, "Zakynthos", today=day)["matches"])
check("rates 'seasons' answer has no price", "not shared" in query.get_rate(qm, "Sirocco", "2027-07-03")["summary"])
try:
    query.get_yacht(qa, "Sirocco")
    check("blocked yacht is unknown to the partner", False)
except query.QueryError:
    check("blocked yacht is unknown to the partner", True)

# Admin: two-step changes on a copy of the setup
import shutil  # noqa: E402
import tempfile  # noqa: E402
import admin  # noqa: E402
tmp = Path(tempfile.mkdtemp()) / "sharing.json"
shutil.copy(ROOT / "examples/sharing.json", tmp)
share = {"id": "SH-9", "to": {"recipient": "R-ACME"}, "boats": {"yacht": "EXY-002"}, "profile": "full", "calendar": "full", "rates": "full"}
plan = admin.upsert(tmp, full, "share", share, day)
check("admin: preview names who changes", plan["changes"] == ["Acme Charters: Kalimera full / busy / none -> full / full / full"])
check("admin: preview saves nothing", "SH-9" not in tmp.read_text())
admin.upsert(tmp, full, "share", share, day, confirm=True)
check("admin: confirm saves", "SH-9" in tmp.read_text())
issued = admin.issue_key(tmp, full, "R-ACME", "test", day, confirm=True)
from resolve import key_for_secret  # noqa: E402
check("admin: issued secret resolves to its key", key_for_secret(admin.load(tmp), issued["secret"])["id"] == issued["record"]["id"])
check("admin: secret is not stored", issued["secret"] not in tmp.read_text())
admin.revoke_key(tmp, full, issued["record"]["id"], day, confirm=True)
try:
    resolve_access(admin.load(tmp), full, issued["record"]["id"], day)
    check("admin: revoked key stops working", False)
except SharingError:
    check("admin: revoked key stops working", True)
gone = admin.delete(tmp, full, "recipient", "R-ACME", day)
check("admin: deleting a recipient removes its shares and keys, and reports lost access",
      "share SH-4" in gone["summary"] and "key K-ACME-1" in gone["summary"] and "Acme Charters: removed" in gone["summary"])
try:
    admin.delete(tmp, full, "recipient", "R-DMA", day)
    check("admin: a company with people cannot be deleted", False)
except admin.AdminError:
    check("admin: a company with people cannot be deleted", True)
try:
    admin.upsert(tmp, full, "share", {**share, "calendar": "everything"}, day)
    check("admin: rejects a bad level", False)
except admin.AdminError:
    check("admin: rejects a bad level", True)

sys.exit(1 if failed else 0)
