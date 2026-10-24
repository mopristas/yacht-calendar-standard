# Yacht Calendar Standard: Specification

Version 0.1 (draft, 24 October 2026)

The key words MUST, SHOULD and MAY are used as in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

## 1. Formats used everywhere

| Kind | Format | Example |
|---|---|---|
| Id | String, 1-64 characters, stable forever | `EXY-001` |
| CYA id | 24 lowercase hex characters | `aaaaaaaaaaaaaaaaaaaa0001` |
| Local date-time | ISO 8601 without offset, minutes precision, local time at the port | `2027-07-10T12:00` |
| UTC timestamp | ISO 8601 with `Z` | `2026-10-24T09:00:00Z` |
| Date | ISO 8601 | `2027-07-10` |
| Timezone | IANA name | `Europe/Athens` |
| Currency | ISO 4217 code | `EUR` |
| Money | Number, whole currency units, no symbols or separators | `108000` |
| Percent | Number, 0-100 | `35` |
| Length | Number, metres, one decimal | `38.4` |
| Location | `"<port or marina>, <country>"`, in English | `Lefkas Marina, Greece` |
| List (JSON) | Array of strings | `["Ionian", "Saronic"]` |
| List (Sheet / CSV) | Values separated by `; ` | `Ionian; Saronic` |
| Empty | JSON `null`, or an empty cell | |

## 2. Yacht (Level 1)

One record per yacht the CA centrally manages. Schema: [`schema/yacht.schema.json`](schema/yacht.schema.json).

| Field | Required | Type | Example | Notes |
|---|---|---|---|---|
| `yacht_id` | MUST | Id | `EXY-001` | The CA's own id. Never reused, never changed |
| `yacht_name` | MUST | String | `Blue Horizon` | Current name |
| `cya_id` | If on CYA | CYA id | `aaaaaaaaaaaaaaaaaaaa0001` | Lets a reader match the yacht without guessing by name |
| `length_m` | MUST | Length | `38.4` | Tells apart yachts with the same name |
| `builder` | SHOULD | String | `Westport` | |
| `year_built` | SHOULD | Integer | `2008` | |
| `type` | SHOULD | Enum | `motor` | `motor`, `sail`, `catamaran`, `power_catamaran`, `gulet`, `motor_sailer`, `other` |
| `guests` | MUST | Integer | `10` | Overnight guests |
| `cabins` | MUST | Integer | `5` | |
| `crew` | MAY | Integer | `8` | |
| `updated_at` | SHOULD | UTC timestamp | `2026-10-24T09:00:00Z` | Last change to this record |

## 3. Availability (Level 2)

One record per busy period. Schema: [`schema/availability.schema.json`](schema/availability.schema.json).

| Field | Required | Type | Example | Notes |
|---|---|---|---|---|
| `yacht_id` | MUST | Id | `EXY-001` | From the yacht list |
| `start` | MUST | Local date-time | `2027-07-10T12:00` | |
| `end` | MUST | Local date-time | `2027-07-17T12:00` | After `start` |
| `timezone` | MUST | Timezone | `Europe/Athens` | |
| `category` | MUST | Enum | `booked` | `booked`, `hold` or `unavailable` (shipyard, owner use, crew leave, delivery) |

A Level 2 feed is a Level 3 feed with the Level 3 fields removed. A CA that serves Level 3 does not need to build Level 2 separately.

## 4. Booking (Level 3)

One record per booked or held period. Follows CYA `GET /bookings`, with the ports made required. Schema: [`schema/booking.schema.json`](schema/booking.schema.json).

| Field | Required | Type | Example | Notes |
|---|---|---|---|---|
| `booking_id` | MUST | Id | `BK-2027-0142` | Stable, so an edit replaces the old record |
| `yacht_id` | MUST | Id | `EXY-001` | |
| `category` | MUST | Enum | `booked` | As in Level 2 |
| `start` | MUST | Local date-time | `2027-07-10T12:00` | Embarkation, local time at the pickup port |
| `end` | MUST | Local date-time | `2027-07-17T12:00` | Disembarkation, local time at the drop-off port |
| `timezone` | MUST | Timezone | `Europe/Athens` | |
| `pickup_location` | MUST | Location | `Argostoli, Greece` | Where the charter starts. For `unavailable`, where the yacht is |
| `drop_off_location` | MUST | Location | `Zakynthos, Greece` | Where it ends |
| `hold_expires` | If `hold` | UTC timestamp | `2026-11-02T18:00:00Z` | When the hold lapses |
| `updated_at` | MUST | UTC timestamp | `2026-10-24T09:00:00Z` | Last change |

## 5. Season (Level 4)

One record per season per yacht. Follows CYA `/yacht/seasons`. Schema: [`schema/season.schema.json`](schema/season.schema.json).

| Field | Required | Type | Example | Notes |
|---|---|---|---|---|
| `yacht_id` | MUST | Id | `EXY-001` | |
| `title` | MUST | String | `High Season` | |
| `start_date` | MUST | Date | `2027-07-01` | |
| `end_date` | MUST | Date | `2027-08-31` | Inclusive |
| `base_port` | MUST | Location | `Lefkas Marina, Greece` | |
| `cruising_areas` | MUST | List | `["Ionian"]` | Areas she cruises this season |
| `relocation_ports` | SHOULD | List of objects | `[{"port": "Corfu, Greece", "fee": 4500}]` | Ports she can start or end at, with any delivery fee (in `currency`). In a sheet: `Corfu, Greece = 4500; Preveza, Greece` |
| `turnaround_hours` | MUST | Integer | `24` | Minimum gap between charters |
| `min_nights` | SHOULD | Integer | `7` | |
| `currency` | MUST | Currency | `EUR` | |
| `weekly_rate_low` | MUST | Money | `108000` | Base charter fee per week, excluding VAT and APA |
| `weekly_rate_high` | If a range | Money | `120000` | |
| `vat_percent` | MUST | Percent | `5.2` | |
| `apa_percent` | MUST | Percent | `35` | |
| `terms` | MUST | Enum | `plus_expenses` | `plus_expenses`, `inclusive`, `all_inclusive` |
| `holiday_rules` | If any | String | `NY week 27 Dec - 3 Jan, flat 150000` | Fixed holiday and event weeks |

## 6. Feed document

A JSON feed is one object. Schema: [`schema/feed.schema.json`](schema/feed.schema.json).

```json
{
  "standard": "yacht-calendar-standard/0.1",
  "ca": "Example Yachts Ltd",
  "generated_at": "2026-10-24T09:00:00Z",
  "level": 3,
  "yachts": [],
  "bookings": [],
  "seasons": []
}
```

| `level` | MUST contain | MUST NOT contain |
|---|---|---|
| 1 | `yachts` | `availability`, `bookings`, `seasons` |
| 2 | `yachts`, `availability` | `bookings`, `seasons` |
| 3 | `yachts`, `bookings` | `seasons` |
| 4 | `yachts`, `bookings`, `seasons` | |

Full examples for every level are in [`examples/`](examples/).

## 7. HTTP API

Defined in [`openapi.yaml`](openapi.yaml). All endpoints are `GET`, return JSON, and need `Authorization: Bearer <key>`.

| Endpoint | Scope | Returns |
|---|---|---|
| `GET /v1/key` | any | The key's own grant ([ACCESS-LEVELS.md](ACCESS-LEVELS.md#telling-the-partner-what-the-key-can-do)) |
| `GET /v1/yachts` | `fleet:read` | `{"yachts": [...]}` |
| `GET /v1/availability?from=&to=&yacht_id=` | `availability:read` | `{"availability": [...]}` |
| `GET /v1/bookings?from=&to=&yacht_id=&updated_since=` | `calendar:read` | `{"bookings": [...]}` |
| `GET /v1/seasons?yacht_id=` | `rates:read` | `{"seasons": [...]}` |
| `GET /v1/feed` | any | A feed document at the key's level |

`from` and `to` are dates and select periods that overlap them. `updated_since` is a UTC timestamp and lets a reader fetch only what changed. Lists MAY be paged with `?cursor=`; a paged response carries `"next_cursor"` (null on the last page).

## 8. Google Sheet

Pick the folder for the level you are sharing in [`templates/google-sheet/`](templates/google-sheet/) (`level-1` to `level-4`) and copy each CSV into a tab of the same name. Tab names are exactly `Yachts`, `Availability`, `Bookings` and `Seasons`; row 1 is the field names, exactly as written (see [ACCESS-LEVELS.md](ACCESS-LEVELS.md#levels-outside-the-http-api)). Share as "Anyone with the link can view" and send the link.

## 9. iCal

One calendar per yacht, or one calendar with the `yacht_id` in square brackets at the start of each event title.

| iCal property | Field |
|---|---|
| `DTSTART` / `DTEND` with `TZID` | `start` / `end`, `timezone` |
| `UID` | `booking_id` |
| `SUMMARY` starting `HOLD` | `category = hold` |
| `SUMMARY` starting `UNAVAILABLE` | `category = unavailable` |
| `LOCATION` = `pickup → drop-off` | `pickup_location`, `drop_off_location` (Level 3) |
| `LAST-MODIFIED` | `updated_at` |

## 10. Update rules

1. Update within one business day of any change.
2. A released hold MUST leave the feed, or become `booked`.
3. A cancelled booking MUST be removed. Keep the same `booking_id` when editing.
4. Cover at least the next 18 months.
5. A date with no record means "no booking recorded". Readers MUST NOT treat it as confirmed availability, and MUST confirm a week and price with the CA before quoting it to a client.
6. Feeds MUST NOT contain client names, contact details, fees paid, commission or any other personal data.
