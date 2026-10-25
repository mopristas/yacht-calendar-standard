# Connecting AI assistants

The standard is built to be read by AI assistants (Claude, ChatGPT and others). There are three ways in:

| Way | For | What you need |
|---|---|---|
| **MCP server** ([`server/ycs_mcp.py`](server/ycs_mcp.py)) | Claude Desktop, Claude Code, the Claude API, Cursor, ChatGPT connectors, any MCP client | Python 3.10+ and `pip install -r server/requirements.txt` |
| **HTTP API** ([`openapi.yaml`](openapi.yaml)) | ChatGPT custom GPTs (Actions), any agent framework | The publisher's API URL and your key |
| **[`llms.txt`](llms.txt)** | Any model that reads the web | Nothing |

Every answer, over MCP or HTTP, starts with a one-line `summary` an assistant can relay as it is, and ends with the `rules` it must follow (an open date is not confirmed availability; the data is internal; an unlisted yacht is not shared).

## The tools

| MCP tool | HTTP | Answers |
|---|---|---|
| `my_access` | `GET /v1/key` | Which yachts you can see, and how much of each |
| `search_available` | `GET /v1/search?start=&end=&guests=&area=&yacht_type=&min_length=&max_length=` | What is free on these dates. Each yacht: `free`, `on_hold`, `taken`, `no_calendar` or `beyond_window`, with where she comes from and goes next, and the weekly rate if shared |
| `find_routes` | `GET /v1/routes?place=&start=&end=` | Which yachts already start or end at a port, or are based or cruising in an area |
| `get_yacht` | `GET /v1/yachts` | Specs, cabins, toys, photos, brochure |
| `get_calendar` | `GET /v1/availability`, `GET /v1/bookings` | One yacht's periods |
| `get_rate` | `GET /v1/rate?yacht=&start=&end=` | Season, weekly rate, VAT, APA, terms |

Publishers who run the server with `--admin` also get `admin_preview`, `admin_list`, `admin_save`, `admin_delete`, `admin_issue_key` and `admin_revoke_key`. Changes are always two steps: the first call shows what would change for whom ("Maria K.: Sirocco busy → full"), and nothing is saved until the call is repeated with `confirm=true`.

## Partner: plug a CA's feed into your own assistant

You received a key, a feed link or a Google Sheet link from a CA. Run the server locally against it.

**Claude Code**

```bash
claude mcp add yacht-calendars -e YCS_KEY=<your key> -- \
  python3 /path/to/yacht-calendar-standard/server/ycs_mcp.py --source https://api.example-ca.com/v1
```

**Claude Desktop** (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "yacht-calendars": {
      "command": "python3",
      "args": ["/path/to/yacht-calendar-standard/server/ycs_mcp.py", "--source", "https://api.example-ca.com/v1"],
      "env": { "YCS_KEY": "<your key>" }
    }
  }
}
```

`--source` takes any form a CA can publish in: an API base URL (`.../v1`), a JSON feed URL, a Google Sheet URL shared as "anyone with the link can view", a local JSON file, or a folder of sheet CSVs. Several CAs = several entries, one per CA.

Then ask, for example: *"Which yachts are free 10 to 17 July 2027 for 10 guests in the Ionian?"* or *"Which boats finish a charter in Zakynthos in July?"*

## Publisher: serve every partner from one server

Run the server in publisher mode, behind HTTPS. Each request is answered for the key in its `Authorization: Bearer` header, using your [sharing setup](SHARING.md), so one server serves every partner and each sees only what you shared.

```bash
YCS_ADMIN_SECRET=<a long random secret> python3 server/ycs_mcp.py \
  --sharing sharing.json --feed full-feed.json --admin \
  --transport http --host 0.0.0.0 --port 8000
```

- MCP endpoint: `https://<your host>/mcp`
- HTTP API: `https://<your host>/v1/...` (the endpoints in [`openapi.yaml`](openapi.yaml))
- Keys: issue them with the `admin_issue_key` tool (or [`tools/admin.py`](tools/admin.py)). Only a SHA-256 hash is stored; the secret is shown once.
- Changes to `sharing.json`, including revoking a key, apply on the next request. The feed is re-read every 5 minutes (`--ttl`).
- The admin tools only answer the `YCS_ADMIN_SECRET` key.

To check what one partner sees before you hand out their key, run it locally over stdio as that key:

```bash
python3 server/ycs_mcp.py --sharing sharing.json --feed full-feed.json --as-key K-MARIA-1
```

## Connecting to a hosted server

| Client | How |
|---|---|
| Claude Code | `claude mcp add --transport http yacht-calendars https://<host>/mcp --header "Authorization: Bearer <key>"` |
| Claude API (MCP connector) | `mcp_servers: [{"type": "url", "url": "https://<host>/mcp", "name": "yacht-calendars", "authorization_token": "<key>"}]` |
| ChatGPT custom GPT | Configure → Actions → import [`openapi.yaml`](openapi.yaml), set the server URL to `https://<host>`, Authentication: API key, Bearer, paste the key |
| Other MCP clients | Streamable HTTP at `https://<host>/mcp` with an `Authorization: Bearer <key>` header |

Claude.ai and ChatGPT web connectors sign users in with OAuth 2.1, which the reference server includes. Start it in publisher mode over HTTP with `--public-url https://<host>` (the address people reach it at, behind HTTPS):

```
python3 server/ycs_mcp.py --sharing sharing.json --feed full-feed.json --transport http --public-url https://<host>
```

The server then registers connectors on the fly, serves the OAuth endpoints and metadata, and shows its own sign-in page. A user adds the connector URL `https://<host>/mcp` in Claude.ai (Settings > Connectors > Add custom connector) or in ChatGPT, is sent to the sign-in page, and pastes the key their central agent gave them, once. After that the connector refreshes its own tokens (access 1 hour, refresh 30 days). Tokens are tied to that key and checked on every request, so revoking the key cuts the connector off at once. OAuth state lives in `oauth-store.json` beside the sharing file (change with `--oauth-store`); only hashes of codes and tokens are stored. Bearer keys keep working as before.

## Suggested assistant instructions

For a broker's own assistant or a custom GPT:

> You help charter brokers find yachts. Use the yacht calendar tools for any question with dates, routes or rates. Relay each answer's summary. "Free" means no booking is recorded: always tell the broker to confirm the week and the price with the central agent before quoting. Never put calendar data, feed links or screenshots in anything meant for a client. If a yacht is not in the results, it is not shared with you: say so, do not guess.
