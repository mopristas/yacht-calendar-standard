# Mapping from CYA

For a central agent whose fleet is already on Central Yacht Agent (CYA): the CYA field each of our fields comes from. Field names on the CYA side are as CYA's API returns them, so a CA (or an AI) can convert an export in one pass.

If a yacht is on CYA, sending `cya_id` plus the five required fields is enough at Level 1.

## Yacht

| Ours | CYA | Conversion |
|---|---|---|
| `cya_id` | `_id` | As is |
| `name` | `yachtName` | As is |
| `previous_names` | `yachtPreviousName` | Split into a list |
| `builder` | `builder_name` | As is |
| `year` | `year_build` | Integer |
| `refit` | `refit` | Integer year |
| `flag` | `flag` | As is |
| `length` | `lenght` (sic) + `units` | Convert to metres if `units` is feet (÷ 3.281) |
| `beam` | `beam` | Metres |
| `draft` | `draft` | Metres |
| `cruising_speed` | `cruising_speed` | Knots |
| `max_speed` | `max_speed` | Knots |
| `range` | `cruising_range` | Nautical miles |
| `fuel_per_hour` | `fuel_consumption` | Litres per hour |
| `cabin_types` | `accommodations` | Per bed-type cabin counts |
| `crew` | `crewGeneral.crewCount` | Integer |
| `crew_description` | `crewGeneral.crewDescription` | As is |
| `air_conditioning` | `air_conditioning` | Yes / no |
| `ac_at_night` | `fldAcAllNight` | Yes / no |
| `diving` | `scubaDiving` | Yes / no |
| `amenities` | `amenities` | Labels, not ids |
| `toys` | `watersports[]` | Label, plus ` xN` when `quantity` > 1 |
| `photos` | `main_image`, then `Images` | Main photo first |
| `videos` | `Videos` | URLs |
| `updated_at` | `updated_at` | UTC |

## Booking

| Ours | CYA | Conversion |
|---|---|---|
| `id` | booking id | As is |
| `status` | `category` | Same values: booked, hold, unavailable |
| `start` / `end` | `start` / `end` | Local time at the port |
| `pickup` / `dropoff` | pickup / drop-off location | Often empty on CYA. **This is the one thing we ask CAs to fill in** |

## Season

| Ours | CYA | Conversion |
|---|---|---|
| `name` | `title` | As is |
| `start` / `end` | `start_date` / `end_date` | Dates |
| `weekly_rate_from` / `weekly_rate_to` | `low_price` / `high_price` | Per week, excluding VAT and APA |
| `relocation_ports` | relocation ports | Rarely filled on CYA today |

## Not taken from CYA

`menuDetails`, `crewDetails` (named crew), `charter_preferences`, `broker_notes`, `yachtManager*` (CA contact details) and `ebrochure` links are left out on purpose: they are either personal data or specific to one broker account.
