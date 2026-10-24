# Access levels and keys

The CA owns the data and decides who sees what. This page defines the four levels and how keys carry them.

## The levels

Each level includes everything below it. A Level 3 key also returns Level 1 and Level 2 data.

### Level 1: Fleet (`fleet:read`)

The yacht list ([`yacht`](schema/yacht.schema.json)). Enough for a broker to know the boat exists and match it to their own records.

Returns: `yacht_id`, `yacht_name`, `cya_id`, `length_m`, `builder`, `year_built`, `type`, `guests`, `cabins`, `crew`, `updated_at`.

### Level 2: Availability (`availability:read`)

Busy periods only ([`availability`](schema/availability.schema.json)). Answers "is she free on these dates?" and nothing more.

Returns per busy period: `yacht_id`, `start`, `end`, `timezone`, `category` (`booked`, `hold` or `unavailable`).

No ports, no booking ids, no hold expiry. A CA that is careful about routes can stop here.

### Level 3: Calendar (`calendar:read`)

Full bookings ([`booking`](schema/booking.schema.json)). Answers "where does she start and finish?", so a broker can offer a route the yacht is already doing.

Adds: `booking_id`, `pickup_location`, `drop_off_location`, `hold_expires`, `updated_at`.

### Level 4: Seasons and rates (`rates:read`)

Seasons ([`season`](schema/season.schema.json)): where the yacht is based, where she will go, and what she costs.

Adds: `base_port`, `cruising_areas`, `relocation_ports`, `turnaround_hours`, `min_nights`, `currency`, weekly rates, `vat_percent`, `apa_percent`, `terms`, `holiday_rules`.

### Never shared at any level

Client names, contact details, charter fees actually paid, commission, owner details, or any other personal data.

## Keys

A key is how a CA grants a level to one partner.

| Rule | |
|---|---|
| One key per partner | So access can be revoked for one partner without touching the others |
| The key carries its scopes | For example `fleet:read availability:read calendar:read` for Level 3 |
| Sent as a bearer token | `Authorization: Bearer <key>` on every request |
| Can be limited to some yachts | Optional: a key may cover only part of the fleet (for example one region) |
| Can expire | Optional: the CA sets an expiry date; the partner gets `401` after it |
| Revocable at any time | The partner gets `401` from the next request on |

### Responses

| Situation | HTTP status | Body |
|---|---|---|
| No key, unknown key, expired or revoked key | `401` | `{"error": "invalid_key"}` |
| Valid key, endpoint needs a higher level | `403` | `{"error": "insufficient_scope", "required": "calendar:read"}` |
| Valid key, yacht outside the key's fleet | `404` | `{"error": "not_found"}` (do not reveal that the yacht exists) |

### Telling the partner what the key can do

`GET /v1/key` returns the key's own grant, so a partner (or their AI assistant) can see what it may ask for:

```json
{
  "ca": "Example Yachts Ltd",
  "partner": "DMA Yachting",
  "level": 3,
  "scopes": ["fleet:read", "availability:read", "calendar:read"],
  "yacht_ids": null,
  "expires_at": "2027-12-31T23:59:59Z"
}
```

`yacht_ids: null` means the whole fleet.

## Levels outside the HTTP API

| Route | How the level is set |
|---|---|
| JSON feed URL | One secret URL per level (for example `.../feed?key=...`). The feed's `level` field states it |
| Google Sheet | By which tabs the shared sheet contains: `Yachts` = 1, plus `Availability` = 2, `Bookings` instead = 3, plus `Seasons` = 4 |
| iCal | Busy events only = 2. With `LOCATION` and `UID` filled = 3 |

Anyone with a sheet or feed link can read it, so treat the link itself as the key: send it to one partner, and change the link to revoke.
