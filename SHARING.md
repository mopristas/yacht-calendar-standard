# Sharing: who sees which boats, and how much

The publisher (a central agent, an owner, a fleet) decides per boat, per part and per partner what each partner sees. Partners can be grouped, and any single person or company can be given more, or less, than their group.

The feed format does not change. A partner gets the same `yachts`, `availability`, `bookings` and `seasons`, filtered to what it may see, with each yacht's `access` stated on it.

Schema: [`schema/sharing.schema.json`](schema/sharing.schema.json) · Worked example: [`examples/sharing.json`](examples/sharing.json) · Reference resolver: [`tools/resolve.py`](tools/resolve.py)

## The parts of a setup

| Part | What it is | Example |
|---|---|---|
| **Publisher** | Who owns the boats and calendars | Example Yachts Ltd |
| **Recipient** | A company or a person you share with. A person can belong to a company and inherits its shares | DMA Yachting; Maria K. (of DMA Yachting) |
| **Group** | A named set of recipients | All partners; Top brokers |
| **Boat set** | A named set of boats: a fixed list, or a rule that new boats join automatically | Whole fleet; Ionian fleet; Owner's private boats |
| **Share** | To whom, which boats, and a level for each part | Top brokers × Ionian fleet: full / full / full |
| **Key** | The login or API key one recipient uses | Maria's AI assistant |

The setup is the publisher's own. Recipients never see it, only the data it lets through.

## Levels per part

Each share sets three independent levels, so a partner can see a calendar without prices, or specs without a calendar.

| Part | Levels (low → high) | What each adds |
|---|---|---|
| `profile` | `none` · `basic` · `full` | `basic`: id, name, length, guests, cabins. `full`: every yacht field. `none` = **block** (see below) |
| `calendar` | `none` · `busy` · `status` · `full` | `busy`: taken dates only, every period shows as `busy`. `status`: booked / hold / unavailable. `full`: bookings with pickup and drop-off ports and hold expiry |
| `rates` | `none` · `seasons` · `full` | `seasons`: base port, cruising areas, relocation ports, turnaround, minimum nights, no prices. `full`: weekly rates, VAT, APA, terms, holidays |

What each calendar level puts in the feed:

| `calendar` | Feed list | Record |
|---|---|---|
| `busy` | `availability` | `status` is always `busy` |
| `status` | `availability` | `status` is `booked`, `hold` or `unavailable` |
| `full` | `bookings` | The full booking record |

### Presets

The four levels from [ACCESS-LEVELS.md](ACCESS-LEVELS.md) are presets of the same settings:

| Preset | `profile` | `calendar` | `rates` |
|---|---|---|---|
| 1. Fleet | `full` | `none` | `none` |
| 2. Availability | `full` | `status` | `none` |
| 3. Calendar | `full` | `full` | `none` |
| 4. Seasons and rates | `full` | `full` | `full` |

## Share fields

| Field | Required | Example | Notes |
|---|---|---|---|
| `id` | Yes | `SH-2` | |
| `to` | Yes | `{"group": "G-TOP"}` or `{"recipient": "R-MARIA"}` | |
| `boats` | Yes | `{"set": "S-IONIAN"}` or `{"yacht": "EXY-007"}` | |
| `profile` | Yes | `full` | |
| `calendar` | Yes | `full` | |
| `rates` | Yes | `full` | |
| `calendar_window` | No | `{"months_ahead": 18}` | How far ahead the recipient can see. Bookings starting later are left out |
| `valid_from` / `valid_until` | No | `2027-09-30` | Inclusive dates. Outside them the share does not exist |
| `note` | No | `Working the owner's referral` | Internal only |

## Boat sets

| Field | Example | Notes |
|---|---|---|
| `yacht_ids` | `["EXY-007"]` | A fixed list |
| `rule.all` | `true` | Every boat |
| `rule.cruising_area` | `Ionian` | Boats listing this cruising area |
| `rule.type` | `catamaran` | |
| `rule.min_length` / `rule.max_length` | `40` | Metres |
| `rule.min_guests` | `10` | |

A set has either `yacht_ids` or `rule`. Every condition in a rule must match.

## How shares combine

For each boat and each key:

1. **Find the shares that apply.** A share applies if it is to the key's recipient, to the recipient's company, or to a group the recipient or its company is in; if it covers the boat; and if today is inside its `valid_from` / `valid_until`.
2. **Keep only the most specific.** Rank by who first, then by boat:
   - who: person or company named directly (**3**) → the person's company (**2**) → a group (**1**)
   - boat: the yacht named directly (**2**) → a boat set (**1**)

   Only the shares with the highest rank count. So a share to Maria beats any share to her company or her groups, and a share for one boat beats a share for a set.
3. **Among those, the highest level wins**, part by part. Two group shares for the same boat add up.
4. **A block hides the boat.** If the winning `profile` is `none`, the boat does not appear at all: not in `yachts`, not in any list. A block share sets all three parts to `none`. It beats broader shares, never an equally specific one.
5. **The calendar window** comes from the winning share(s) for the calendar part. No window on any of them means no limit.

No shares at all for a boat means the boat is not shared.

## Worked example

From [`examples/sharing.json`](examples/sharing.json). DMA Yachting is in *All partners* and *Top brokers*; Maria is a person at DMA Yachting; Acme Charters is in *All partners*.

| Share | To | Boats | profile | calendar | rates | Other |
|---|---|---|---|---|---|---|
| SH-1 | All partners | Whole fleet | full | busy | none | |
| SH-2 | Top brokers | Ionian fleet | full | full | full | 18 months ahead |
| SH-3 | Maria | Sirocco | full | status | seasons | until 30 Sep 2027 |
| SH-4 | Acme Charters | Owner's private boats | none | none | none | block |

What each key sees (run `python3 tools/resolve.py examples/sharing.json examples/feed-level-4.json --key K-MARIA-1 --date 2026-10-24 --explain`):

| Boat | DMA Yachting | Maria | Acme Charters |
|---|---|---|---|
| Blue Horizon (Ionian) | full / full / full, 18 months (SH-1 + SH-2) | same, from her company | full / busy / none (SH-1) |
| Kalimera (Turkey) | full / busy / none (SH-1) | same | full / busy / none |
| Sirocco (private) | full / busy / none (SH-1) | full / status / seasons (SH-3 wins) | **not shared** (SH-4 blocks) |

The resulting feeds are in [`examples/feed-as-dma.json`](examples/feed-as-dma.json), [`feed-as-maria.json`](examples/feed-as-maria.json) and [`feed-as-acme.json`](examples/feed-as-acme.json). After 30 September 2027 Maria's share expires and she falls back to her company's access.

## The feed a recipient receives

`"level": "per_yacht"`, and each yacht carries its own access. Maria's feed, shortened to Sirocco (her full profile fields cut for space):

```json
{
  "standard": "yacht-calendar-standard/0.4",
  "ca": "Example Yachts Ltd",
  "generated_at": "2026-10-24T09:00:00Z",
  "level": "per_yacht",
  "yachts": [
    { "id": "EXY-007", "name": "Sirocco", "length": 45.0, "guests": 10, "cabins": 5,
      "access": { "profile": "full", "calendar": "status", "rates": "seasons" } }
  ],
  "availability": [
    { "yacht_id": "EXY-007", "start": "2027-08-01T12:00", "end": "2027-08-08T12:00",
      "timezone": "Europe/Athens", "status": "booked" }
  ],
  "seasons": [
    { "yacht_id": "EXY-007", "name": "Summer", "start": "2027-06-01", "end": "2027-09-30",
      "base_port": "Athens, Greece", "cruising_areas": ["Saronic", "Cyclades"], "turnaround_hours": 48, "min_nights": 7 }
  ]
}
```

A reader MUST use `access` to tell "no booking" from "not allowed to see": a yacht with `calendar: none` and no periods is not free, its calendar is just not shared.

## Managing a setup over the API

The publisher manages its setup with an admin key (scope `admin`). Endpoints in [`openapi.yaml`](openapi.yaml):

| Endpoint | What it does |
|---|---|
| `GET/POST /v1/admin/recipients`, `PUT/DELETE /v1/admin/recipients/{id}` | Sign up companies and people, set their company and groups |
| `GET/POST /v1/admin/groups`, `PUT/DELETE /v1/admin/groups/{id}` | Groups |
| `GET/POST /v1/admin/boat-sets`, `PUT/DELETE /v1/admin/boat-sets/{id}` | Boat sets |
| `GET/POST /v1/admin/shares`, `PUT/DELETE /v1/admin/shares/{id}` | Shares |
| `GET/POST /v1/admin/keys`, `DELETE /v1/admin/keys/{id}` | Issue and revoke keys. The secret is shown once, at creation |
| `GET /v1/admin/preview?key=` or `?recipient=` | What that key or recipient would see, per boat, with the deciding shares (the `--explain` table) |

The same setup can be kept as a JSON file or a Google Sheet with one tab per part; [`tools/resolve.py`](tools/resolve.py) shows exactly how it must be read.
