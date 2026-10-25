# Yacht Calendar Standard: Specification

Version 0.4 (draft, 25 October 2026)

The key words MUST, SHOULD and MAY are used as in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

Field names are plain English (`name`, `length`, `pickup`). A CA already on CYA can map its data with [CYA.md](CYA.md).

## 1. Formats used everywhere

| Kind | Format | Example |
|---|---|---|
| Id | String, 1-64 characters, stable forever | `EXY-001` |
| CYA id | 24 lowercase hex characters | `aaaaaaaaaaaaaaaaaaaa0001` |
| Local date-time | ISO 8601 without offset, to the minute, local time at the port | `2027-07-10T12:00` |
| UTC timestamp | ISO 8601 with `Z` | `2026-10-24T09:00:00Z` |
| Date | ISO 8601 | `2027-07-10` |
| Timezone | IANA name | `Europe/Athens` |
| Currency | ISO 4217 code | `EUR` |
| Money | Number, whole currency units, no symbols or separators | `108000` |
| Percent | Number, 0-100 | `35` |
| Length, beam, draft | Number, **metres** | `38.4` |
| Speed | Number, knots | `18` |
| Range | Number, nautical miles | `1800` |
| Fuel | Number, litres per hour | `380` |
| Location | `"<port or marina>, <country>"`, in English | `Lefkas Marina, Greece` |
| Yes / no | JSON `true` / `false`; in a sheet `yes` / `no` | `true` |
| List | JSON array of strings; in a sheet, values separated by `; ` | `["Ionian", "Saronic"]` |
| URL | `https://...` | `https://example.com/photo.jpg` |

**Missing values:** in JSON, leave the field out (do not send `null`). In a sheet, leave the cell empty.

## 2. Yacht (Level 1)

One record per yacht the CA centrally manages. Schema: [`schema/yacht.schema.json`](schema/yacht.schema.json).

Only five fields are required. Everything else is optional, but the more you fill in, the better brokers can match the boat to a client.

**If the yacht is on CYA**, send `cya_id` and the required fields; the specs are optional, because readers can take them from CYA. **If it is not on CYA**, please send the specs.

### Required

| Field | Type | Example | Notes |
|---|---|---|---|
| `id` | Id | `EXY-001` | Your own id. Never reused, never changed |
| `name` | String | `Blue Horizon` | Current name |
| `length` | Metres | `38.4` | Length overall. Tells apart yachts with the same name |
| `guests` | Integer | `10` | Overnight guests |
| `cabins` | Integer | `5` | |

### Identity

| Field | Type | Example | Notes |
|---|---|---|---|
| `cya_id` | CYA id | `aaaaaaaaaaaaaaaaaaaa0001` | Lets a reader match the yacht without guessing by name |
| `previous_names` | List | `["Horizon Blue"]` | |
| `type` | Enum | `motor` | `motor`, `sail`, `catamaran`, `power_catamaran`, `gulet`, `motor_sailer`, `other` |
| `builder` | String | `Westport` | |
| `model` | String | `125` | |
| `year` | Integer | `2008` | Year built |
| `refit` | Integer | `2023` | Year of the latest refit |
| `flag` | String | `Cayman Islands` | |

### Specs

| Field | Type | Example | Notes |
|---|---|---|---|
| `beam` | Metres | `7.6` | |
| `draft` | Metres | `2.1` | |
| `cruising_speed` | Knots | `18` | |
| `max_speed` | Knots | `22` | |
| `range` | Nautical miles | `1800` | At cruising speed |
| `fuel_per_hour` | Litres per hour | `380` | At cruising speed |

### Accommodation

| Field | Type | Example | Notes |
|---|---|---|---|
| `cabin_types` | Object of counts | `{"master": 1, "vip": 1, "double": 1, "twin": 2}` | Keys: `master`, `vip`, `double`, `twin`, `single`, `bunk`, `convertible`. MUST add up to `cabins`. In a sheet: `master = 1; vip = 1; double = 1; twin = 2` |
| `crew` | Integer | `8` | |
| `air_conditioning` | Yes / no | `true` | |
| `ac_at_night` | Yes / no | `true` | Air conditioning runs all night at anchor |

### Where she cruises

| Field | Type | Example | Notes |
|---|---|---|---|
| `home_port` | Location | `Lefkas Marina, Greece` | Usual base. Seasons (Level 4) give the base per season |
| `cruising_areas` | List | `["Ionian", "Saronic"]` | |

### On board

| Field | Type | Example | Notes |
|---|---|---|---|
| `amenities` | List | `["Wi-Fi", "Jacuzzi", "Gym"]` | |
| `toys` | List | `["Jet ski x2", "Seabob"]` | Water toys. Add `xN` for a quantity |
| `diving` | Yes / no | `false` | Scuba diving offered on board |

### Text and media

| Field | Type | Example | Notes |
|---|---|---|---|
| `description` | String | `Tri-deck motor yacht with a beach club.` | |
| `crew_description` | String | `Captain and crew of eight, together since 2021.` | No crew surnames or contact details |
| `photos` | List of URLs | `["https://.../1.jpg"]` | First photo = main photo |
| `videos` | List of URLs | `["https://.../tour.mp4"]` | |
| `brochure` | URL | `https://.../brochure.pdf` | Unbranded if possible |
| `updated_at` | UTC timestamp | `2026-10-24T09:00:00Z` | Last change to this record |

## 3. Availability (Level 2)

One record per busy period. Schema: [`schema/availability.schema.json`](schema/availability.schema.json).

| Field | Required | Type | Example | Notes |
|---|---|---|---|---|
| `yacht_id` | MUST | Id | `EXY-001` | The yacht's `id` |
| `start` | MUST | Local date-time | `2027-07-10T12:00` | |
| `end` | MUST | Local date-time | `2027-07-17T12:00` | After `start` |
| `timezone` | MUST | Timezone | `Europe/Athens` | |
| `status` | MUST | Enum | `booked` | `booked`, `hold` or `unavailable` (shipyard, owner use, crew leave, delivery). In a `per_yacht` feed, `busy` for a yacht whose calendar level is `busy` |

A Level 2 feed is a Level 3 feed with the Level 3 fields removed. A CA that serves Level 3 does not need to build Level 2 separately.

## 4. Booking (Level 3)

One record per booked or held period, with the ports. Schema: [`schema/booking.schema.json`](schema/booking.schema.json).

| Field | Required | Type | Example | Notes |
|---|---|---|---|---|
| `id` | MUST | Id | `BK-2027-0142` | Stable, so an edit replaces the old record |
| `yacht_id` | MUST | Id | `EXY-001` | |
| `status` | MUST | Enum | `booked` | As in Level 2 |
| `start` | MUST | Local date-time | `2027-07-10T12:00` | Embarkation, local time at the pickup port |
| `end` | MUST | Local date-time | `2027-07-17T12:00` | Disembarkation, local time at the drop-off port |
| `timezone` | MUST | Timezone | `Europe/Athens` | |
| `pickup` | MUST | Location | `Argostoli, Greece` | Where the charter starts. For `unavailable`, where the yacht is |
| `dropoff` | MUST | Location | `Zakynthos, Greece` | Where it ends |
| `hold_expires` | If `hold` | UTC timestamp | `2026-11-02T18:00:00Z` | When the hold lapses |
| `updated_at` | MUST | UTC timestamp | `2026-10-24T09:00:00Z` | Last change |

## 5. Season (Level 4)

One record per season per yacht. Schema: [`schema/season.schema.json`](schema/season.schema.json).

The price fields (`currency`, `weekly_rate_from`, `vat`, `apa`, `terms`) come all together or not at all. A level 4 feed MUST include them; a recipient whose rates level is `seasons` ([SHARING.md](SHARING.md)) gets the season without them.

| Field | Required | Type | Example | Notes |
|---|---|---|---|---|
| `yacht_id` | MUST | Id | `EXY-001` | |
| `name` | MUST | String | `High Season` | |
| `start` | MUST | Date | `2027-07-01` | |
| `end` | MUST | Date | `2027-08-31` | Inclusive |
| `base_port` | MUST | Location | `Lefkas Marina, Greece` | |
| `cruising_areas` | MUST | List | `["Ionian"]` | Areas she cruises this season |
| `relocation_ports` | SHOULD | List of `{port, fee}` | `[{"port": "Corfu, Greece", "fee": 4500}]` | Ports she can start or end at, with any delivery fee in `currency`. In a sheet: `Corfu, Greece = 4500; Preveza, Greece` |
| `turnaround_hours` | MUST | Integer | `24` | Minimum gap between charters |
| `min_nights` | SHOULD | Integer | `7` | |
| `currency` | MUST | Currency | `EUR` | |
| `weekly_rate_from` | MUST | Money | `108000` | Base charter fee per week, excluding VAT and APA |
| `weekly_rate_to` | If a range | Money | `120000` | |
| `vat` | MUST | Percent | `5.2` | |
| `apa` | MUST | Percent | `35` | |
| `terms` | MUST | Enum | `plus_expenses` | `plus_expenses`, `inclusive`, `all_inclusive` |
| `holidays` | If any | String | `NY week 27 Dec - 3 Jan, flat 150000` | Fixed holiday and event weeks |

## 6. Feed document

A JSON feed is one object. Schema: [`schema/feed.schema.json`](schema/feed.schema.json).

```json
{
  "standard": "yacht-calendar-standard/0.4",
  "ca": "Example Yachts Ltd",
  "generated_at": "2026-10-24T09:00:00Z",
  "level": 3,
  "yachts": [],
  "bookings": []
}
```

| `level` | MUST contain | MUST NOT contain |
|---|---|---|
| 1 | `yachts` | `availability`, `bookings`, `seasons` |
| 2 | `yachts`, `availability` | `bookings`, `seasons` |
| 3 | `yachts`, `bookings` | `availability`, `seasons` |
| 4 | `yachts`, `bookings`, `seasons` | `availability` |
| `per_yacht` | `yachts`, each with `access`; then whichever lists the access calls for | Anything a yacht's `access` does not allow |

`per_yacht` feeds are what a recipient gets when the publisher shares per boat; see [SHARING.md](SHARING.md#the-feed-a-recipient-receives).

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

Pick the folder for the level you are sharing in [`templates/google-sheet/`](templates/google-sheet/) (`level-1` to `level-4`) and import each CSV into a tab of the same name: `Yachts`, `Availability`, `Bookings`, `Seasons`. Row 1 is the field names, exactly as written. You can delete optional columns you never fill. Share as "Anyone with the link can view" and send the link.

## 9. iCal

One calendar per yacht, or one calendar with the yacht `id` in square brackets at the start of each event title.

| iCal property | Field |
|---|---|
| `DTSTART` / `DTEND` with `TZID` | `start` / `end`, `timezone` |
| `UID` | booking `id` |
| `SUMMARY` starting `HOLD` | `status = hold` |
| `SUMMARY` starting `UNAVAILABLE` | `status = unavailable` |
| `LOCATION` = `pickup → dropoff` | `pickup`, `dropoff` (Level 3) |
| `LAST-MODIFIED` | `updated_at` |

## 10. Update rules

1. Update within one business day of any change.
2. A released hold MUST leave the feed, or become `booked`.
3. A cancelled booking MUST be removed. Keep the same `id` when editing.
4. Cover at least the next 18 months.
5. A date with no record means "no booking recorded". Readers MUST NOT treat it as confirmed availability, and MUST confirm a week and price with the CA before quoting it to a client.
6. Feeds MUST NOT contain client names, contact details, fees paid, commission or any other personal data.
