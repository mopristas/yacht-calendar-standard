#!/usr/bin/env python3
"""MCP server (and AI-friendly HTTP API) for Yacht Calendar Standard feeds.

Partner mode: read one feed with your own key, for your own AI.
    python3 server/ycs_mcp.py --source https://api.example-ca.com/v1 --key $YCS_KEY
    python3 server/ycs_mcp.py --source "https://docs.google.com/spreadsheets/d/<id>/edit"
    python3 server/ycs_mcp.py --source examples/feed-as-dma.json

Publisher mode: serve every recipient from your sharing setup. Each request is
answered for the key in its Authorization header, so one server serves everyone.
    python3 server/ycs_mcp.py --sharing sharing.json --feed full-feed.json --transport http
    add --admin to expose the admin tools (needs YCS_ADMIN_SECRET over HTTP)
    add --public-url https://host to turn on OAuth 2.1 sign-in (dynamic client registration, a sign-in page
    where the user pastes their key) for Claude.ai and ChatGPT web connectors; raw keys keep working.
    --oauth-store PATH keeps the OAuth state (default: oauth-store.json beside --sharing).

Over HTTP the same server also answers the REST endpoints in openapi.yaml
(/v1/key, /v1/feed, /v1/search, ...), which is what ChatGPT GPT Actions use.
Needs: pip install "mcp>=2.3" (see server/requirements.txt).
"""
import argparse
import hmac
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import admin  # noqa: E402
import query  # noqa: E402
from resolve import SharingError, build_feed_for_access, access_for_recipient, check_setup, key_for_secret, usable_key  # noqa: E402

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions  # noqa: E402
from mcp.server.mcpserver import Context, MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

from oauth import YcsOAuthProvider, add_signin_routes  # noqa: E402

INSTRUCTIONS = """Yacht charter fleet data from a central agent (CA), under the Yacht Calendar Standard.
Start with my_access to see which yachts you can see and at what level. For "is anything free on these dates",
use search_available; for "which boats are already starting or ending near a port", use find_routes.
Every answer starts with a one-line summary you can relay, and ends with rules you must follow:
an open date means no booking is recorded, not confirmed availability, so the broker confirms with the CA
before quoting; the data is internal and never goes to a client; a yacht you cannot see is not shared with you."""

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)


class Denied(Exception):
    def __init__(self, status, body):
        super().__init__(body.get("error"))
        self.status, self.body = status, body


class Store:
    """Where the data comes from, cached for `ttl` seconds."""

    def __init__(self, args):
        self.args, self.ttl, self._cache = args, args.ttl, {}
        self.oauth = None  # set by build_server when --public-url turns OAuth on

    def _cached(self, name, loader):
        hit = self._cache.get(name)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        value = loader()
        self._cache[name] = (time.monotonic(), value)
        return value

    def today(self):
        return date.fromisoformat(self.args.today) if self.args.today else datetime.now(timezone.utc).date()

    def full_feed(self):
        return self._cached("full", lambda: query.load_source(self.args.feed))

    def setup(self):
        # Re-read every time in publisher mode: an admin change or a revoke takes effect at once.
        return admin.load(self.args.sharing)

    def identify(self, bearer, setup):
        """The key id a bearer stands for (OAuth token or raw secret), "admin" for the admin secret, else None."""
        if self.oauth:
            return self.oauth.identify(bearer, setup)
        key = key_for_secret(setup, bearer)
        return key["id"] if key else None

    def feed_for(self, bearer):
        """The normalised feed this caller may see."""
        if not self.args.sharing:
            return self._cached("partner", lambda: query.normalise(query.load_source(self.args.source, self.args.key)))
        setup, full = self.setup(), self.full_feed()
        key_id = self.args.as_key
        if bearer:
            key_id = self.identify(bearer, setup)
            if key_id is None or key_id == "admin":  # the admin secret opens the admin tools, not a recipient's feed
                raise Denied(401, {"error": "invalid_key"})
        if not key_id:
            raise Denied(401, {"error": "invalid_key", "hint": "send Authorization: Bearer <key>"})
        try:
            usable_key(setup, key_id, self.today())
            check_setup(setup, {y["id"] for y in full["yachts"]})
            recipient = next(k["recipient"] for k in setup["keys"] if k["id"] == key_id)
            access = access_for_recipient(setup, full, recipient, self.today())
        except SharingError as e:
            raise Denied(401 if str(e) == "invalid_key" else 500, {"error": str(e)}) from None
        feed = build_feed_for_access(setup, full, access, self.today())
        feed["recipient"] = next(r["name"] for r in setup["recipients"] if r["id"] == recipient)
        feed["_key"] = next(k for k in setup["keys"] if k["id"] == key_id)
        return query.normalise(feed)


def request_of(ctx):
    """The HTTP request behind a tool call, or None over stdio."""
    try:
        return ctx.request_context.request
    except (AttributeError, ValueError):
        return None


def bearer_of(request):
    if request is None:
        return None
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else None


def oauth_enabled(args):
    return bool(args.public_url and args.sharing and args.transport == "http")


def build_server(args):
    store = Store(args)
    oauth_kwargs = {}
    if oauth_enabled(args):
        store.oauth = YcsOAuthProvider(
            args.oauth_store or Path(args.sharing).resolve().parent / "oauth-store.json", store.setup, store.today,
            os.environ.get("YCS_ADMIN_SECRET") or None)
        public = args.public_url.rstrip("/")
        oauth_kwargs = {"auth_server_provider": store.oauth, "auth": AuthSettings(
            issuer_url=public, resource_server_url=public + "/mcp", validate_token_resource=False,
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True))}
    server = MCPServer(name="yacht-calendar-standard", title="Yacht calendars", instructions=INSTRUCTIONS,
                       version="0.4", website_url="https://github.com/mopristas/yacht-calendar-standard", **oauth_kwargs)
    if store.oauth:
        add_signin_routes(server, store.oauth, lambda: store.full_feed().get("ca") or "the central agent")

    def feed(ctx):
        return store.feed_for(bearer_of(request_of(ctx)))

    def answer(fn):
        try:
            return fn()
        except query.QueryError as e:
            return {"summary": f"Could not answer: {e}", "error": str(e)}
        except Denied as e:
            return {"summary": "Your key was not accepted.", **e.body}

    @server.tool(annotations=READ)
    def my_access(ctx: Context) -> dict:
        """Which yachts you can see and how much of each: profile (basic/full), calendar
        (none/busy/status/full, plus how many months ahead) and rates (none/seasons/full). Call this first."""
        return answer(lambda: query.my_access(feed(ctx), store.today()))

    @server.tool(annotations=READ)
    def search_available(start: str, end: str, ctx: Context, guests: int | None = None, area: str | None = None,
                         yacht_type: str | None = None, min_length: float | None = None, max_length: float | None = None,
                         include_taken: bool = False) -> dict:
        """Find yachts free for a charter. start and end are dates (YYYY-MM-DD), embarkation and
        disembarkation. Optional: guests (minimum), area (cruising area or port, e.g. "Ionian"),
        yacht_type (motor, sail, catamaran, power_catamaran, gulet, motor_sailer), min_length / max_length
        in metres. Each yacht comes back free, on_hold, taken (hidden unless include_taken), no_calendar
        or beyond_window, with where she is coming from or going to next, and the weekly rate if shared."""
        return answer(lambda: query.search_available(feed(ctx), start, end, guests, area, yacht_type, min_length,
                                                     max_length, include_taken, store.today()))

    @server.tool(annotations=READ)
    def find_routes(place: str, ctx: Context, start: str | None = None, end: str | None = None) -> dict:
        """Yachts already starting or ending a charter at a port, or based or cruising in an area,
        between start and end (default: the next 12 months). Use it to offer a client a route a yacht
        is already doing, e.g. place="Zakynthos" or place="Ionian"."""
        return answer(lambda: query.find_routes(feed(ctx), place, start, end, store.today()))

    @server.tool(annotations=READ)
    def get_yacht(yacht: str, ctx: Context) -> dict:
        """One yacht's details (specs, cabins, toys, photos, brochure) by id or name."""
        return answer(lambda: query.get_yacht(feed(ctx), yacht))

    @server.tool(annotations=READ)
    def get_calendar(yacht: str, ctx: Context, start: str | None = None, end: str | None = None) -> dict:
        """One yacht's booked, held and unavailable periods between start and end (default: the next
        18 months), with pickup and drop-off ports if your calendar level is full."""
        return answer(lambda: query.get_calendar(feed(ctx), yacht, start, end, store.today()))

    @server.tool(annotations=READ)
    def get_rate(yacht: str, start: str, ctx: Context, end: str | None = None) -> dict:
        """The season and weekly rate (with VAT, APA and terms) for a yacht on a start date."""
        return answer(lambda: query.get_rate(feed(ctx), yacht, start, end))

    if args.admin:
        add_admin_tools(server, store, args)
    add_rest_routes(server, store)
    return server


def add_admin_tools(server, store, args):
    admin_secret = os.environ.get("YCS_ADMIN_SECRET")

    def guarded(ctx, fn):
        request = request_of(ctx)
        if request is not None:  # over HTTP: only the publisher's admin secret
            given = bearer_of(request) or ""
            if store.oauth:
                is_admin = store.oauth.identify(given, store.setup()) == "admin"
            else:
                is_admin = bool(admin_secret) and hmac.compare_digest(given.encode(), admin_secret.encode())
            if not is_admin:
                return {"summary": "Admin tools need the publisher's admin key.", "error": "insufficient_scope", "required": "admin"}
        try:
            return fn()
        except admin.AdminError as e:
            return {"summary": f"Not changed: {e}", "error": str(e)}

    path = args.sharing

    @server.tool(annotations=READ)
    def admin_preview(who: str, ctx: Context) -> dict:
        """What a recipient (by id) or key (by id) sees, per yacht, and which shares decided it."""
        return guarded(ctx, lambda: admin.preview(path, store.full_feed(), who, store.today()))

    @server.tool(annotations=READ)
    def admin_list(kind: str, ctx: Context) -> dict:
        """List recipients, groups, boat sets, shares or keys. kind: recipient, group, boat_set, share, key."""
        return guarded(ctx, lambda: admin.list_items(path, kind))

    @server.tool(annotations=WRITE)
    def admin_save(kind: str, record: dict, ctx: Context, confirm: bool = False) -> dict:
        """Add or replace a recipient, group, boat_set, share or key (by its id). Without confirm it only
        shows what would change for whom; call again with confirm=true to save. Shares: {"id", "to":
        {"group"|"recipient": id}, "boats": {"set"|"yacht": id}, "profile": none|basic|full, "calendar":
        none|busy|status|full, "rates": none|seasons|full, optional "calendar_window": {"months_ahead": n},
        "valid_from", "valid_until"}. Always show the human the changes and get their OK before confirming."""
        return guarded(ctx, lambda: admin.upsert(path, store.full_feed(), kind, record, store.today(), confirm))

    @server.tool(annotations=WRITE)
    def admin_delete(kind: str, id: str, ctx: Context, confirm: bool = False) -> dict:
        """Delete a recipient, group, boat_set, share or key. Without confirm it only shows what would change."""
        return guarded(ctx, lambda: admin.delete(path, store.full_feed(), kind, id, store.today(), confirm))

    @server.tool(annotations=WRITE)
    def admin_issue_key(recipient: str, label: str, ctx: Context, expires_at: str | None = None, confirm: bool = False) -> dict:
        """Issue a new key to a recipient. The secret is returned once, on confirm, and never stored."""
        return guarded(ctx, lambda: admin.issue_key(path, store.full_feed(), recipient, label, store.today(), expires_at, confirm))

    @server.tool(annotations=WRITE)
    def admin_revoke_key(key_id: str, ctx: Context, confirm: bool = False) -> dict:
        """Revoke a key. It stops working on the next request."""
        return guarded(ctx, lambda: admin.revoke_key(path, store.full_feed(), key_id, store.today(), confirm))


def add_rest_routes(server, store):
    """The read endpoints of openapi.yaml, plus the AI ones (/v1/search, /v1/routes, /v1/rate)."""

    def handler(fn):
        async def endpoint(request: Request):
            try:
                feed = store.feed_for(bearer_of(request))
                return JSONResponse(fn(feed, request.query_params))
            except Denied as e:
                return JSONResponse(e.body, status_code=e.status)
            except query.QueryError as e:
                return JSONResponse({"error": "bad_request", "detail": str(e)}, status_code=400)
        return endpoint

    def strip(feed):
        return {k: v for k, v in feed.items() if not k.startswith("_") and k != "recipient"}

    def periods(feed, name, q):
        rows = feed.get(name) or []
        if q.get("yacht_id"):
            rows = [r for r in rows if r["yacht_id"] == q["yacht_id"]]
        if q.get("from"):
            rows = [r for r in rows if r["end"][:10] >= q["from"]]
        if q.get("to"):
            rows = [r for r in rows if r["start"][:10] <= q["to"]]
        if q.get("updated_since") and name == "bookings":
            rows = [r for r in rows if r["updated_at"] >= q["updated_since"]]
        return rows

    def needs(feed, part, levels, scope):
        if not any(y["access"][part] in levels for y in feed["yachts"]):
            raise Denied(403, {"error": "insufficient_scope", "required": scope})

    def key_info(feed, q):
        key = feed.get("_key", {})
        return {"ca": feed["ca"], "recipient": feed.get("recipient"), "expires_at": key.get("expires_at"),
                "yachts": [{"id": y["id"], "access": {p: y["access"][p] for p in ("profile", "calendar", "rates")},
                            "months_ahead": y["access"].get("months_ahead")} for y in feed["yachts"]]}

    def availability(feed, q):
        needs(feed, "calendar", ("busy", "status", "full"), "availability:read")
        rows = periods(feed, "availability", q) + [
            {k: b[k] for k in ("yacht_id", "start", "end", "timezone", "status")} for b in periods(feed, "bookings", q)]
        return {"availability": sorted(rows, key=lambda r: (r["yacht_id"], r["start"])), "next_cursor": None}

    def bookings(feed, q):
        needs(feed, "calendar", ("full",), "calendar:read")
        return {"bookings": periods(feed, "bookings", q), "next_cursor": None}

    def seasons(feed, q):
        needs(feed, "rates", ("seasons", "full"), "rates:read")
        rows = [s for s in feed.get("seasons") or [] if not q.get("yacht_id") or s["yacht_id"] == q["yacht_id"]]
        return {"seasons": rows, "next_cursor": None}

    def number(q, name, cast):
        return cast(q[name]) if q.get(name) else None

    routes = {
        "/v1/key": key_info,
        "/v1/feed": lambda f, q: strip(f),
        "/v1/yachts": lambda f, q: {"yachts": strip(f)["yachts"], "next_cursor": None},
        "/v1/availability": availability,
        "/v1/bookings": bookings,
        "/v1/seasons": seasons,
        "/v1/search": lambda f, q: query.search_available(
            f, q.get("start"), q.get("end"), number(q, "guests", int), q.get("area"), q.get("yacht_type"),
            number(q, "min_length", float), number(q, "max_length", float), q.get("include_taken") == "true", store.today()),
        "/v1/routes": lambda f, q: query.find_routes(f, q.get("place", ""), q.get("start"), q.get("end"), store.today()),
        "/v1/rate": lambda f, q: query.get_rate(f, q.get("yacht", ""), q.get("start"), q.get("end")),
    }
    for path, fn in routes.items():
        server.custom_route(path, methods=["GET"])(handler(fn))

    @server.custom_route("/llms.txt", methods=["GET"])
    async def llms(request: Request):
        from starlette.responses import PlainTextResponse
        return PlainTextResponse((ROOT / "llms.txt").read_text(encoding="utf-8"))


def parse_args(argv):
    ap = argparse.ArgumentParser(description="Yacht Calendar Standard MCP server")
    src = ap.add_argument_group("partner mode")
    src.add_argument("--source", help="Feed file, sheet CSV folder, Google Sheet URL, feed URL or API base URL")
    src.add_argument("--key", default=os.environ.get("YCS_KEY"), help="Your key for a URL source (or YCS_KEY)")
    pub = ap.add_argument_group("publisher mode")
    pub.add_argument("--sharing", help="Your sharing setup (schema/sharing.schema.json)")
    pub.add_argument("--feed", help="Your full level 4 feed (any source form)")
    pub.add_argument("--as-key", help="stdio only: answer as this key id (for testing a recipient's view)")
    pub.add_argument("--public-url", help="https://host this server is reached at; turns on OAuth sign-in (needs --transport http)")
    pub.add_argument("--oauth-store", help="OAuth state file (default: oauth-store.json beside --sharing)")
    pub.add_argument("--admin", action="store_true", help="Add the admin tools")
    ap.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--ttl", type=int, default=300, help="Seconds to cache the source (default 300)")
    ap.add_argument("--today", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if bool(args.source) == bool(args.sharing):
        ap.error("give either --source (partner mode) or --sharing and --feed (publisher mode)")
    if args.sharing and not args.feed:
        ap.error("--sharing needs --feed")
    if args.public_url and not (args.sharing and args.transport == "http"):
        ap.error("--public-url needs publisher mode and --transport http")
    if args.admin and not args.sharing:
        ap.error("--admin needs publisher mode")
    if args.admin and args.transport == "http" and not os.environ.get("YCS_ADMIN_SECRET"):
        ap.error("--admin over HTTP needs YCS_ADMIN_SECRET")
    return args


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    server = build_server(args)
    if args.transport == "http":
        server.run("streamable-http", host=args.host, port=args.port)
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
