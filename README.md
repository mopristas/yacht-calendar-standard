# Yacht Calendar Standard

An open format for sharing a charter fleet's yachts, availability and calendars with charter brokers.

Central agents (CAs) and fleet operators publish one feed. Brokers, and the AI assistants that brokers use, read it. The field names follow the Central Yacht Agent (CYA) booking and season format, so a CA that already keeps CYA current has nothing new to learn. The one addition is that **every booking carries its pickup and drop-off port**.

Maintained by [DMA Yachting](https://dmayachting.com). Free to use and implement, by anyone, with any partner.

- Specification: [SPEC.md](SPEC.md)
- Access levels and keys: [ACCESS-LEVELS.md](ACCESS-LEVELS.md)
- JSON Schemas: [`schema/`](schema/)
- HTTP API (OpenAPI 3.1): [`openapi.yaml`](openapi.yaml)
- Examples: [`examples/`](examples/)
- Google Sheet templates, one per level: [`templates/google-sheet/`](templates/google-sheet/)
- Validator: [`tools/validate.py`](tools/validate.py)

## Why

A yacht calendar that a broker can read directly means:

- "Is she free 10 to 17 July?" gets answered without an email round trip.
- A broker can offer a yacht on a route she is already doing, for example a charter already set to start in Kefalonia and end in Zakynthos.
- The CA gets fewer, better enquiries: only for boats that are actually free.

## Access levels

A CA decides how much each partner sees. Each level includes the levels below it.

| Level | Name | Scope | What the partner sees |
|---|---|---|---|
| 1 | Fleet | `fleet:read` | The yacht list: name, length, builder, guests, cabins |
| 2 | Availability | `availability:read` | Busy periods per yacht: start, end, and booked / hold / unavailable |
| 3 | Calendar | `calendar:read` | Full bookings: pickup and drop-off ports, timezone, hold expiry |
| 4 | Seasons and rates | `rates:read` | Base port, cruising areas, relocation ports, turnaround, weekly rates, VAT, APA, terms |

Access is granted with a **key**: one key per partner, carrying the levels the CA chose. Revoking the key ends the access. See [ACCESS-LEVELS.md](ACCESS-LEVELS.md).

No level ever contains client names, charter fees paid, or any other personal data.

## Ways to publish (best first)

| Option | What the CA does | Levels it can carry |
|---|---|---|
| 1. Keep CYA current | Update bookings and holds on CYA, and fill in pickup and drop-off ports | Whatever CYA shares |
| 2. HTTP API | Serve the endpoints in [`openapi.yaml`](openapi.yaml), behind a key | 1-4, per key |
| 3. JSON feed URL | One URL returning a [feed document](schema/feed.schema.json) | 1-4, one feed URL per level |
| 4. Google Sheet | Copy the [template](templates/google-sheet/), share "anyone with the link can view" | Whichever tabs you include |
| 5. iCal (.ics) | The calendar link your booking system already exports | 2, or 3 if `LOCATION` is filled |

One feed per CA, covering every yacht the CA centrally manages.

## Quick check

```bash
python3 tools/validate.py examples/feed-level-4.json
```

The validator checks a JSON feed (or a folder of sheet CSV exports) against the schemas and the update rules, and prints the access level the feed actually provides. It needs Python 3.9+ and nothing else.

## Status

Version 0.1, draft, 24 October 2026. Changes are proposed as issues or pull requests. Field names are stable from 1.0.

## Licence

Specification and schemas: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Code in `tools/`: MIT. See [LICENSE](LICENSE).
