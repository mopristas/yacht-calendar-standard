# Yacht Calendar Standard

An open format for sharing a charter fleet's yachts, availability and calendars with charter brokers.

Central agents (CAs) and fleet operators publish one feed. Brokers, and the AI assistants that brokers use, read it. Field names are plain English (`name`, `length`, `pickup`, `dropoff`), and [CYA.md](CYA.md) maps each one to its Central Yacht Agent (CYA) field, so a CA already on CYA can convert in minutes. The one thing we add to what CAs usually share is that **every booking carries its pickup and drop-off port**.

Maintained by [DMA Yachting](https://dmayachting.com). Free to use and implement, by anyone, with any partner.

- Specification: [SPEC.md](SPEC.md)
- Access levels and keys: [ACCESS-LEVELS.md](ACCESS-LEVELS.md)
- Sharing per boat, per part and per partner, with groups: [SHARING.md](SHARING.md)
- Mapping from CYA field names: [CYA.md](CYA.md)
- JSON Schemas: [`schema/`](schema/)
- HTTP API (OpenAPI 3.1): [`openapi.yaml`](openapi.yaml)
- Examples: [`examples/`](examples/)
- Google Sheet templates, one per level: [`templates/google-sheet/`](templates/google-sheet/)
- Reference resolver (what one key sees): [`tools/resolve.py`](tools/resolve.py)
- **AI assistants (MCP server, ChatGPT Actions, llms.txt): [AI.md](AI.md)**
- Validator: [`tools/validate.py`](tools/validate.py) (and `tools/build_examples.py`, which rebuilds every example and template from one sample fleet)

## Why

A yacht calendar that a broker can read directly means:

- "Is she free 10 to 17 July?" gets answered without an email round trip.
- A broker can offer a yacht on a route she is already doing, for example a charter already set to start in Kefalonia and end in Zakynthos.
- The CA gets fewer, better enquiries: only for boats that are actually free.

## Who sees what

The publisher decides, per boat and per partner, how much of each part a partner sees: the boat's profile, its calendar, and its rates. Partners can be put in groups ("Top brokers"), boats in sets ("Ionian fleet", or a rule like "over 40 m"), and any one company or person can get more, or less, than their group. See [SHARING.md](SHARING.md).

For a simple setup there are four preset levels; each includes the levels below it.

| Level | Name | Scope | What the partner sees |
|---|---|---|---|
| 1 | Fleet | `fleet:read` | The boats: name, length, guests, cabins, plus any specs, amenities, toys, photos and brochure the CA adds |
| 2 | Availability | `availability:read` | Busy periods per yacht: start, end, and booked / hold / unavailable |
| 3 | Calendar | `calendar:read` | Full bookings: pickup and drop-off ports, timezone, hold expiry |
| 4 | Seasons and rates | `rates:read` | Base port, cruising areas, relocation ports, turnaround, weekly rates, VAT, APA, terms |

Access is granted with a **key**: one per person or system, belonging to one recipient. Revoking the key ends the access. See [ACCESS-LEVELS.md](ACCESS-LEVELS.md).

No level ever contains client names, charter fees paid, or any other personal data.

## For AI assistants

The standard is built to be read by AI. The MCP server in [`server/`](server/) plugs any feed into Claude, ChatGPT or any MCP client, with six read tools shaped like a broker's questions: `my_access`, `search_available` ("what is free 10 to 17 July for 10 in the Ionian?"), `find_routes` ("which boats finish in Zakynthos?"), `get_yacht`, `get_calendar` and `get_rate`. Every answer starts with a one-line summary and ends with the rules the AI must follow.

A publisher can run the same server for all its partners at once: each request is answered for the key it carries, and admin tools let the publisher manage partners, groups and shares by asking its own AI ("share the Ionian boats with Top brokers, calendar only, until September"), with every change previewed before it is saved. See [AI.md](AI.md).

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

Version 0.4, draft, 25 October 2026. 0.4 added the MCP server, the AI endpoints (/v1/search, /v1/routes, /v1/rate), publisher admin and llms.txt. 0.2 renamed fields to plain names and added full yacht specs. 0.3 added sharing per boat, per part and per partner, with groups ([SHARING.md](SHARING.md)) and a reference resolver. Changes are proposed as issues or pull requests. Field names are stable from 1.0.

## Licence

Specification and schemas: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Code in `tools/`: MIT. See [LICENSE](LICENSE).
