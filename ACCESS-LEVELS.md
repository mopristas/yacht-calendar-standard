# Access levels and keys

The publisher owns the data and decides who sees what. There are two ways to do that:

- **Simple:** one preset level for a whole feed, link or key. Below.
- **Per boat, per part, per partner, with groups:** [SHARING.md](SHARING.md). The presets are shortcuts for the same settings.

## The preset levels

Each level includes everything below it.

| Level | Scope | `profile` | `calendar` | `rates` |
|---|---|---|---|---|
| 1. Fleet | `fleet:read` | full | none | none |
| 2. Availability | `availability:read` | full | status | none |
| 3. Calendar | `calendar:read` | full | full | none |
| 4. Seasons and rates | `rates:read` | full | full | full |

### Level 1: Fleet

The yacht list ([`yacht`](schema/yacht.schema.json)): `id`, `name`, `length`, `guests`, `cabins` (required), plus any specs the publisher fills in: builder, year, beam, draft, speeds, cabin types, crew, home port, amenities, toys, description, photos, videos and brochure. See [SPEC.md](SPEC.md#2-yacht-level-1).

### Level 2: Availability

Busy periods ([`availability`](schema/availability.schema.json)): `yacht_id`, `start`, `end`, `timezone`, `status` (`booked`, `hold` or `unavailable`). No ports, no booking ids, no hold expiry.

### Level 3: Calendar

Full bookings ([`booking`](schema/booking.schema.json)). Adds booking `id`, `pickup`, `dropoff`, `hold_expires`, `updated_at`, so a broker can offer a route the yacht is already doing.

### Level 4: Seasons and rates

Seasons ([`season`](schema/season.schema.json)) with prices: `base_port`, `cruising_areas`, `relocation_ports`, `turnaround_hours`, `min_nights`, `currency`, `weekly_rate_from`, `weekly_rate_to`, `vat`, `apa`, `terms`, `holidays`.

### Never shared at any level

Client names, contact details, charter fees actually paid, commission, owner details, or any other personal data.

## Keys

| Rule | |
|---|---|
| One key per person or system | Revoke one without touching the others |
| Belongs to one recipient | Sees what that recipient's shares add up to ([SHARING.md](SHARING.md#how-shares-combine)) |
| Sent as a bearer token | `Authorization: Bearer <key>` on every request |
| Can expire | The partner gets `401` after it |
| Revocable at any time | The partner gets `401` from the next request on |

### Responses

| Situation | HTTP status | Body |
|---|---|---|
| No key, unknown key, expired or revoked key | `401` | `{"error": "invalid_key"}` |
| Valid key, no yacht shared at the level this endpoint needs | `403` | `{"error": "insufficient_scope", "required": "calendar:read"}` |
| Valid key, yacht not shared with this key | `404` | `{"error": "not_found"}` (never reveal that the yacht exists) |

### Telling the partner what the key can do

`GET /v1/key` returns the key's own access, per yacht, so a partner (or their AI assistant) knows what it may ask for:

```json
{
  "ca": "Example Yachts Ltd",
  "recipient": "Maria K.",
  "expires_at": null,
  "yachts": [
    { "id": "EXY-001", "access": { "profile": "full", "calendar": "full", "rates": "full" }, "months_ahead": 18 },
    { "id": "EXY-007", "access": { "profile": "full", "calendar": "status", "rates": "seasons" }, "months_ahead": null }
  ]
}
```

## Levels outside the HTTP API

| Route | How the level is set |
|---|---|
| JSON feed URL | One secret URL per recipient. The feed's `level` field states it (`1`-`4` or `per_yacht`) |
| Google Sheet | By which tabs the shared sheet contains: `Yachts` = 1, plus `Availability` = 2, `Bookings` instead = 3, plus `Seasons` = 4 |
| iCal | Busy events only = 2. With `LOCATION` and `UID` filled = 3 |

Anyone with a sheet or feed link can read it, so treat the link itself as the key: send it to one partner, and change the link to revoke.
