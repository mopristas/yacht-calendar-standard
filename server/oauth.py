"""OAuth 2.1 sign-in for the publisher server, so Claude.ai and ChatGPT web connectors can connect.

The MCP SDK serves /authorize, /token, /register, /revoke and the .well-known metadata. This module
is the provider behind them plus our own /oauth/signin page, where the user pastes the key their
central agent gave them. A token is bound to that key's id (or to "admin"), kept in `subject`, and
the key is re-checked on every request, so revoking it in sharing.json ends every token at once.

State is one JSON file, written atomically. Codes and tokens are stored only as SHA-256 hashes.
"""
import hashlib
import hmac
import html
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path

from mcp.server.auth.provider import (AccessToken, AuthorizationCode, AuthorizationParams, RefreshToken, TokenError,
                                      construct_redirect_uri)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from resolve import SharingError, key_for_secret, usable_key

CODE_TTL = 300
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 86400
REQUEST_TTL = 900
MAX_FAILURES = 10
ADMIN = "admin"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class YcsOAuthProvider:
    def __init__(self, path, load_setup, today, admin_secret=None):
        self.path, self.load_setup, self.today, self.admin_secret = Path(path), load_setup, today, admin_secret
        self.lock = threading.RLock()
        self.data = {"clients": {}, "requests": {}, "codes": {}, "access": {}, "refresh": {}}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))

    # -- storage -----------------------------------------------------------------------------------
    def _save(self):
        now = time.time()
        for table in ("codes", "access", "refresh"):
            self.data[table] = {h: r for h, r in self.data[table].items() if r["expires_at"] > now}
        self.data["requests"] = {i: r for i, r in self.data["requests"].items() if r["created"] + REQUEST_TTL > now}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".oauth-store-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # -- who a bearer is ---------------------------------------------------------------------------
    def identify(self, bearer, setup=None):
        """The key id (or "admin") a bearer stands for right now, or None. Accepts our access tokens
        and raw key secrets; a key that is revoked or expired in sharing.json is refused every time."""
        if not bearer:
            return None
        setup = setup if setup is not None else self.load_setup()
        with self.lock:
            rec = self.data["access"].get(digest(bearer))
        if rec is not None:
            subject = rec["subject"] if rec["expires_at"] > time.time() else None
        elif self.admin_secret and hmac.compare_digest(bearer.encode(), self.admin_secret.encode()):
            return ADMIN
        else:
            key = key_for_secret(setup, bearer)
            subject = key["id"] if key else None
        return subject if self._subject_ok(setup, subject) else None

    def _subject_ok(self, setup, subject):
        if subject == ADMIN:
            return True
        if subject is None:
            return False
        try:
            usable_key(setup, subject, self.today())
        except SharingError:
            return False
        return True

    def key_for_signin(self, pasted):
        """Key id or "admin" for what the user pasted on the sign-in page, or None."""
        if not pasted:
            return None
        if self.admin_secret and hmac.compare_digest(pasted.encode(), self.admin_secret.encode()):
            return ADMIN
        setup = self.load_setup()
        key = key_for_secret(setup, pasted)
        return key["id"] if key and self._subject_ok(setup, key["id"]) else None

    # -- clients -----------------------------------------------------------------------------------
    async def get_client(self, client_id):
        with self.lock:
            rec = self.data["clients"].get(client_id)
        return OAuthClientInformationFull.model_validate(rec) if rec else None

    async def register_client(self, client_info):
        with self.lock:
            self.data["clients"][client_info.client_id] = json.loads(client_info.model_dump_json(exclude_none=True))
            self._save()

    # -- authorization -----------------------------------------------------------------------------
    async def authorize(self, client, params: AuthorizationParams):
        request_id = secrets.token_urlsafe(24)
        with self.lock:
            self.data["requests"][request_id] = {
                "client_id": client.client_id, "created": time.time(), "failures": 0,
                "params": json.loads(params.model_dump_json())}
            self._save()
        return f"/oauth/signin?request={request_id}"

    def pending(self, request_id):
        with self.lock:
            rec = self.data["requests"].get(request_id or "")
            if rec and rec["created"] + REQUEST_TTL > time.time():
                return rec
        return None

    def describe(self, request_id):
        """Which app is asking, and where the sign-in goes back to, for the page to show."""
        from urllib.parse import urlparse
        with self.lock:
            rec = self.data["requests"].get(request_id or "")
            client = self.data["clients"].get(rec["client_id"], {}) if rec else {}
        if not rec:
            return None, None
        return client.get("client_name") or rec["client_id"], urlparse(rec["params"]["redirect_uri"]).netloc

    def fail(self, request_id):
        """Count a failed sign-in; the request is dropped at MAX_FAILURES. True when it was dropped."""
        with self.lock:
            rec = self.data["requests"].get(request_id)
            if rec is None:
                return True
            rec["failures"] += 1
            dropped = rec["failures"] >= MAX_FAILURES
            if dropped:
                del self.data["requests"][request_id]
            self._save()
            return dropped

    def complete(self, request_id, subject):
        """Turn a pending request into an auth code for subject. Returns the redirect URL."""
        with self.lock:
            rec = self.data["requests"].pop(request_id)
            p = rec["params"]
            code = secrets.token_urlsafe(32)
            self.data["codes"][digest(code)] = {
                "client_id": rec["client_id"], "scopes": p["scopes"] or [], "expires_at": time.time() + CODE_TTL,
                "code_challenge": p["code_challenge"], "redirect_uri": p["redirect_uri"],
                "redirect_uri_provided_explicitly": p["redirect_uri_provided_explicitly"],
                "resource": p.get("resource"), "subject": subject}
            self._save()
        return construct_redirect_uri(p["redirect_uri"], code=code, state=p["state"])

    async def load_authorization_code(self, client, authorization_code):
        with self.lock:
            rec = self.data["codes"].get(digest(authorization_code))
        if not rec or rec["client_id"] != client.client_id or rec["expires_at"] <= time.time():
            return None
        return AuthorizationCode(code=authorization_code, **rec)

    async def exchange_authorization_code(self, client, authorization_code):
        with self.lock:
            rec = self.data["codes"].pop(digest(authorization_code.code), None)
            if rec is None:  # single use
                raise TokenError(error="invalid_grant", error_description="authorization code already used")
            return self._issue(client.client_id, rec["scopes"], rec["resource"], rec["subject"])

    def _issue(self, client_id, scopes, resource, subject):
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        shared = {"client_id": client_id, "scopes": scopes, "resource": resource, "subject": subject}
        self.data["access"][digest(access)] = {**shared, "expires_at": int(now + ACCESS_TTL), "refresh": digest(refresh)}
        self.data["refresh"][digest(refresh)] = {**shared, "expires_at": int(now + REFRESH_TTL), "access": digest(access)}
        self._save()
        return OAuthToken(access_token=access, expires_in=ACCESS_TTL, scope=" ".join(scopes) or None, refresh_token=refresh)

    # -- refresh -----------------------------------------------------------------------------------
    async def load_refresh_token(self, client, refresh_token):
        with self.lock:
            rec = self.data["refresh"].get(digest(refresh_token))
        if not rec or rec["client_id"] != client.client_id or rec["expires_at"] <= time.time():
            return None
        return RefreshToken(token=refresh_token, client_id=rec["client_id"], scopes=rec["scopes"],
                            expires_at=rec["expires_at"], resource=rec["resource"], subject=rec["subject"])

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        with self.lock:
            rec = self.data["refresh"].pop(digest(refresh_token.token), None)
            if rec is None:
                raise TokenError(error="invalid_grant", error_description="refresh token already used")
            self.data["access"].pop(rec["access"], None)  # rotate: the old pair both die
            return self._issue(client.client_id, scopes or rec["scopes"], rec["resource"], rec["subject"])

    # -- using and revoking tokens -----------------------------------------------------------------
    async def load_access_token(self, token):
        """Our OAuth access tokens, raw key secrets and the admin secret. The key id rides in `subject`."""
        subject = self.identify(token)
        if subject is None:
            return None
        with self.lock:
            rec = self.data["access"].get(digest(token))
        if rec is not None:
            return AccessToken(token=token, client_id=rec["client_id"], scopes=rec["scopes"],
                               expires_at=rec["expires_at"], resource=rec["resource"], subject=subject)
        return AccessToken(token=token, client_id="raw-key", scopes=[], expires_at=None, subject=subject)

    async def revoke_token(self, token):
        with self.lock:
            h = digest(token.token)
            access = self.data["access"].pop(h, None)
            refresh = self.data["refresh"].pop(h, None)
            if access:
                self.data["refresh"].pop(access["refresh"], None)
            if refresh:
                self.data["access"].pop(refresh["access"], None)
            self._save()

    # -- the SDK's optional grant, not offered -----------------------------------------------------
    async def exchange_identity_assertion(self, client, params):
        raise TokenError(error="unsupported_grant_type", error_description="not supported")


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in</title>
<style>body{{font:16px system-ui,sans-serif;max-width:28rem;margin:4rem auto;padding:0 1rem}}
input,button{{font:inherit;width:100%;padding:.6rem;margin-top:.5rem;box-sizing:border-box}}.err{{color:#b00020}}</style>
</head><body>
<h1>Sign in to {name}'s yacht calendars</h1>
<p><b>{app}</b> is asking to read the yacht calendars your key can see. After you sign in you go back to <b>{host}</b>.
Only continue if you started this from your own AI app.</p>
{message}
<form method="post" action="/oauth/signin">
<input type="hidden" name="request" value="{request}">
<label for="key">Paste the key your central agent gave you</label>
<input id="key" name="key" type="password" autocomplete="off" required autofocus>
<button type="submit">Sign in</button>
</form></body></html>"""


def add_signin_routes(server, provider, publisher_name):
    def page(request_id, message="", status=200):
        error = f'<p class="err">{html.escape(message)}</p>' if message else ""
        app, host = provider.describe(request_id)
        return HTMLResponse(PAGE.format(name=html.escape(publisher_name()), app=html.escape(app or "An app"), host=html.escape(host or "the app"),
                                        message=error, request=html.escape(request_id, quote=True)),
                            status_code=status, headers={"Cache-Control": "no-store"})

    @server.custom_route("/oauth/signin", methods=["GET"])
    async def signin_form(request: Request):
        request_id = request.query_params.get("request", "")
        if provider.pending(request_id) is None:
            return HTMLResponse("<p>This sign-in link has expired. Start again from your AI app.</p>", status_code=400)
        return page(request_id)

    @server.custom_route("/oauth/signin", methods=["POST"])
    async def signin_submit(request: Request):
        form = await request.form()
        request_id, pasted = str(form.get("request", "")), str(form.get("key", "")).strip()
        if provider.pending(request_id) is None:
            return HTMLResponse("<p>This sign-in link has expired. Start again from your AI app.</p>", status_code=400)
        subject = provider.key_for_signin(pasted)
        if subject is None:
            if provider.fail(request_id):
                return HTMLResponse("<p>Too many wrong keys. Start again from your AI app.</p>", status_code=429)
            return page(request_id, "That key was not accepted.", 401)
        return RedirectResponse(provider.complete(request_id, subject), status_code=302, headers={"Cache-Control": "no-store"})
