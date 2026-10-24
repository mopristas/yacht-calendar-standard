# Google Sheet templates

One folder per access level. Each CSV is one tab: import it into a Google Sheet tab with the same name (`Yachts`, `Availability`, `Bookings`, `Seasons`), replace the example rows with your fleet, and share the sheet as "Anyone with the link can view".

| Folder | Tabs | Level |
|---|---|---|
| `level-1/` | Yachts | 1. Fleet |
| `level-2/` | Yachts, Availability | 2. Availability |
| `level-3/` | Yachts, Bookings | 3. Calendar |
| `level-4/` | Yachts, Bookings, Seasons | 4. Seasons and rates |

Lists go in one cell separated by `; `. Relocation ports with a delivery fee: `Corfu, Greece = 4500; Preveza, Greece`.

Check a sheet before you share it: download each tab as CSV into one folder and run `python3 tools/validate.py <folder>`.
