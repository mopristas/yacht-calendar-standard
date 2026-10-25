#!/usr/bin/env python3
"""MCP server test: in memory (partner and publisher mode) and over real HTTP with keys.

Needs: pip install -r server/requirements.txt
"""
import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tools"))

import admin  # noqa: E402
import httpx2  # noqa: E402
import query  # noqa: E402
import ycs_mcp  # noqa: E402
from mcp.client.client import Client  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

DAY = "2026-10-24"
logging.disable(logging.INFO)
failed = 0


def check(label, ok):
    global failed
    print(f"{'ok  ' if ok else 'FAIL'} {label}")
    failed += not ok


def result(r):
    return r.structured_content or json.loads(r.content[0].text)


async def in_memory():
    partner = ycs_mcp.build_server(ycs_mcp.parse_args(["--source", str(ROOT / "examples/feed-as-dma.json"), "--today", DAY]))
    async with Client(partner) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        check("partner mode lists the six read tools",
              set(tools) == {"my_access", "search_available", "find_routes", "get_yacht", "get_calendar", "get_rate"})
        check("read tools are marked read-only", all(t.annotations and t.annotations.read_only_hint for t in tools.values()))
        r = result(await c.call_tool("search_available", {"start": "2027-07-10", "end": "2027-07-17", "guests": 8}))
        check("search over MCP", r["counts"]["free"] == 2 and r["rules"])
        r = result(await c.call_tool("get_yacht", {"yacht": "nope"}))
        check("unknown yacht is an answer, not a crash", "is shared with you" in r["summary"] and r.get("error"))

    publisher = ycs_mcp.build_server(ycs_mcp.parse_args([
        "--sharing", str(ROOT / "examples/sharing.json"), "--feed", str(ROOT / "examples/feed-level-4.json"),
        "--as-key", "K-ACME-1", "--admin", "--today", DAY]))
    async with Client(publisher) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        check("publisher --admin adds the admin tools", {"admin_save", "admin_issue_key", "admin_revoke_key"} <= names)
        r = result(await c.call_tool("get_yacht", {"yacht": "Sirocco"}))
        check("--as-key answers as that key (Acme cannot see Sirocco)", r.get("error") and "is shared with you" in r["summary"])
        r = result(await c.call_tool("admin_save", {"kind": "share", "record": {
            "id": "SH-9", "to": {"group": "G-ALL"}, "boats": {"yacht": "EXY-002"},
            "profile": "full", "calendar": "full", "rates": "full"}}))
        check("admin_save without confirm only previews", r["confirmed"] is False and len(r["changes"]) == 3)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url, token=None):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


async def mcp_call(url, token, tool, args):
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30) as h:
        async with Client(streamable_http_client(url, http_client=h)) as c:
            return result(await c.call_tool(tool, args))


def over_http():
    tmp = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "examples/sharing.json", tmp / "sharing.json")
    full = query.load_source(str(ROOT / "examples/feed-level-4.json"))
    secrets = {r: admin.issue_key(tmp / "sharing.json", full, r, "test", date.fromisoformat(DAY), confirm=True)
               for r in ("R-MARIA", "R-ACME")}
    port = free_port()
    env = {**os.environ, "YCS_ADMIN_SECRET": "admin-test-secret"}
    proc = subprocess.Popen([sys.executable, str(ROOT / "server/ycs_mcp.py"), "--sharing", str(tmp / "sharing.json"),
                             "--feed", str(ROOT / "examples/feed-level-4.json"), "--admin", "--transport", "http",
                             "--port", str(port), "--today", DAY], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(base + "/llms.txt", timeout=1)
                break
            except OSError:
                time.sleep(0.25)
        maria, acme = secrets["R-MARIA"]["secret"], secrets["R-ACME"]["secret"]
        check("HTTP: no key is 401", get(base + "/v1/key")[0] == 401)
        check("HTTP: wrong key is 401", get(base + "/v1/key", "nope")[0] == 401)
        status, body = get(base + "/v1/key", maria)
        check("HTTP: /v1/key lists per-yacht access", status == 200 and len(body["yachts"]) == 3)
        check("HTTP: busy-only partner gets 403 on bookings", get(base + "/v1/bookings", acme)[0] == 403)
        status, body = get(base + "/v1/search?start=2027-07-10&end=2027-07-17", maria)
        check("HTTP: /v1/search answers with a summary", status == 200 and body["summary"])
        check("HTTP: bad date is 400", get(base + "/v1/search?start=soon&end=2027-07-17", maria)[0] == 400)
        status, body = get(base + "/v1/feed", acme)
        check("HTTP: feed hides the blocked yacht", status == 200 and "EXY-007" not in {y["id"] for y in body["yachts"]})
        r = asyncio.run(mcp_call(base + "/mcp", maria, "my_access", {}))
        check("HTTP MCP: answers for the bearer key", "3 yachts" in r["summary"])
        r = asyncio.run(mcp_call(base + "/mcp", maria, "admin_list", {"kind": "key"}))
        check("HTTP MCP: admin tools refuse a partner key", r.get("error") == "insufficient_scope")
        r = asyncio.run(mcp_call(base + "/mcp", "admin-test-secret", "admin_revoke_key",
                                 {"key_id": secrets["R-ACME"]["record"]["id"], "confirm": True}))
        check("HTTP MCP: admin key can revoke", r.get("confirmed") is True)
        check("HTTP: revoked key is refused on the next request", get(base + "/v1/key", acme)[0] == 401)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def oauth_flow():
    import base64
    import hashlib
    import secrets
    from urllib.parse import parse_qs, urlparse

    tmp = Path(tempfile.mkdtemp())
    shutil.copy(ROOT / "examples/sharing.json", tmp / "sharing.json")
    full = query.load_source(str(ROOT / "examples/feed-level-4.json"))
    issued = admin.issue_key(tmp / "sharing.json", full, "R-MARIA", "oauth test", date.fromisoformat(DAY), confirm=True)
    maria, key_id = issued["secret"], issued["record"]["id"]
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen([sys.executable, str(ROOT / "server/ycs_mcp.py"), "--sharing", str(tmp / "sharing.json"),
                             "--feed", str(ROOT / "examples/feed-level-4.json"), "--transport", "http", "--port", str(port),
                             "--public-url", base, "--today", DAY], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(base + "/llms.txt", timeout=1)
                break
            except OSError:
                time.sleep(0.25)
        h = httpx2.Client(timeout=30, follow_redirects=False)
        meta = h.get(base + "/.well-known/oauth-authorization-server").json()
        check("OAuth: metadata advertises register, authorize, token", all(k in meta for k in
              ("registration_endpoint", "authorization_endpoint", "token_endpoint")))
        redirect = "http://127.0.0.1:9/callback"
        reg = h.post(base + "/register", json={"redirect_uris": [redirect], "token_endpoint_auth_method": "none",
                                               "grant_types": ["authorization_code", "refresh_token"],
                                               "response_types": ["code"], "client_name": "test connector"})
        client_id = reg.json().get("client_id")
        check("OAuth: dynamic client registration", reg.status_code in (200, 201) and client_id)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        auth = h.get(base + "/authorize", params={"response_type": "code", "client_id": client_id, "redirect_uri": redirect,
                                                  "code_challenge": challenge, "code_challenge_method": "S256",
                                                  "state": "st-123", "resource": base + "/mcp"})
        loc = auth.headers.get("location", "")
        check("OAuth: /authorize sends the user to our sign-in page", auth.status_code == 302 and loc.startswith("/oauth/signin?request="))
        page = h.get(base + loc)
        check("OAuth: sign-in page names the publisher and asks for the key",
              page.status_code == 200 and "Example Yachts Ltd" in page.text and "Paste the key your central agent gave you" in page.text)
        check("OAuth: sign-in page says which app is asking and where it goes back to",
              "<b>test connector</b> is asking" in page.text and "go back to <b>127.0.0.1" in page.text)
        request_id = parse_qs(urlparse(loc).query)["request"][0]
        bad = h.post(base + "/oauth/signin", data={"request": request_id, "key": "not-a-key"})
        check("OAuth: wrong key is 401 with a message", bad.status_code == 401 and "That key was not accepted." in bad.text)
        good = h.post(base + "/oauth/signin", data={"request": request_id, "key": maria})
        back = urlparse(good.headers.get("location", ""))
        q = parse_qs(back.query)
        check("OAuth: right key redirects to the client with code and state",
              good.status_code == 302 and back.geturl().startswith(redirect) and q.get("state") == ["st-123"] and q.get("code"))
        code = q["code"][0]
        tok = h.post(base + "/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
                                             "client_id": client_id, "code_verifier": verifier}).json()
        check("OAuth: /token returns access and refresh tokens", tok.get("access_token") and tok.get("refresh_token"))
        again = h.post(base + "/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
                                               "client_id": client_id, "code_verifier": verifier})
        check("OAuth: an auth code works once", again.status_code == 400)
        access, refresh = tok["access_token"], tok["refresh_token"]
        r = asyncio.run(mcp_call(base + "/mcp", access, "my_access", {}))
        check("OAuth: MCP my_access with the access token answers for that key", "3 yachts" in r["summary"])
        check("OAuth: REST /v1/key accepts the access token", get(base + "/v1/key", access)[0] == 200)
        r = asyncio.run(mcp_call(base + "/mcp", maria, "my_access", {}))
        check("OAuth: a raw key still works as a bearer", "3 yachts" in r["summary"])
        new = h.post(base + "/token", data={"grant_type": "refresh_token", "refresh_token": refresh, "client_id": client_id}).json()
        check("OAuth: refresh token gives a new access token", new.get("access_token") and new["access_token"] != access)
        old = h.post(base + "/token", data={"grant_type": "refresh_token", "refresh_token": refresh, "client_id": client_id})
        check("OAuth: the old refresh token no longer works", old.status_code == 400)
        check("OAuth: the old access token no longer works after rotation", get(base + "/v1/key", access)[0] == 401)
        access = new["access_token"]
        check("OAuth: the new access token works", get(base + "/v1/key", access)[0] == 200)
        stored = (tmp / "oauth-store.json").read_text(encoding="utf-8")
        check("OAuth: store holds no plain code, token or key",
              not any(v in stored for v in (code, access, refresh, new["refresh_token"], tok["access_token"], maria)))
        admin.revoke_key(tmp / "sharing.json", full, key_id, date.fromisoformat(DAY), confirm=True)
        check("OAuth: a token whose key was revoked is refused on the next request", get(base + "/v1/key", access)[0] == 401)
        try:
            asyncio.run(mcp_call(base + "/mcp", access, "my_access", {}))
            refused = False
        except Exception:
            refused = True
        check("OAuth: and so is the MCP endpoint", refused)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


asyncio.run(in_memory())
over_http()
oauth_flow()
sys.exit(1 if failed else 0)
