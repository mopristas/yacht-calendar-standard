#!/usr/bin/env python3
"""Publisher admin over a sharing setup file: preview, list, change, issue and revoke keys.

Every change is two steps. Without confirm it returns the proposed record and
what it changes for each recipient ("Maria K.: Sirocco calendar status -> full");
with confirm it writes the file. Used by the admin MCP tools (server/ycs_mcp.py).
Standard library only.
"""
import copy
import hashlib
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from resolve import PARTS, SharingError, access_for_recipient, check_setup  # noqa: E402

KINDS = {"recipient": "recipients", "group": "groups", "boat_set": "boat_sets", "share": "shares", "key": "keys"}
REQUIRED = {
    "recipient": ("id", "type", "name"),
    "group": ("id", "name"),
    "boat_set": ("id", "name"),
    "share": ("id", "to", "boats", "profile", "calendar", "rates"),
    "key": ("id", "recipient"),
}


class AdminError(ValueError):
    pass


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, setup):
    """Write atomically, so a crash never leaves half a setup."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".sharing-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(setup, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _check_record(kind, record):
    if kind not in KINDS:
        raise AdminError(f"kind must be one of {sorted(KINDS)}")
    if not isinstance(record, dict):
        raise AdminError("record must be an object")
    missing = [f for f in REQUIRED[kind] if f not in record]
    if missing:
        raise AdminError(f"{kind} needs {missing}")
    if kind == "recipient" and record["type"] not in ("company", "person"):
        raise AdminError("recipient type must be 'company' or 'person'")
    if kind == "boat_set" and ("yacht_ids" in record) == ("rule" in record):
        raise AdminError("a boat set has either yacht_ids or rule")
    if kind == "share":
        for part, levels in PARTS.items():
            if record[part] not in levels:
                raise AdminError(f"share {part} must be one of {levels}")
        if set(record["to"]) not in ({"group"}, {"recipient"}):
            raise AdminError("share 'to' is {\"group\": id} or {\"recipient\": id}")
        if set(record["boats"]) not in ({"set"}, {"yacht"}):
            raise AdminError("share 'boats' is {\"set\": id} or {\"yacht\": id}")
    if kind == "key" and "secret_sha256" in record:
        raise AdminError("issue keys with issue_key, so the secret is generated and shown once")


def _label(access):
    if not access:
        return "not shared"
    return " / ".join(access[p] for p in PARTS) + (f", {access['months_ahead']} months" if access.get("months_ahead") else "")


def diff(before, after, feed, today):
    """What changes, per recipient and yacht, between two setups."""
    names = {y["id"]: y["name"] for y in feed["yachts"]}
    changes = []
    kept = {r["id"] for r in after["recipients"]}
    for r in before["recipients"]:
        if r["id"] not in kept:
            lost = access_for_recipient(before, feed, r["id"], today)
            changes.append(f"{r['name']}: removed, loses access to {len(lost)} yacht{'s' if len(lost) != 1 else ''}")
    for r in after["recipients"]:
        old = access_for_recipient(before, feed, r["id"], today) if any(x["id"] == r["id"] for x in before["recipients"]) else {}
        new = access_for_recipient(after, feed, r["id"], today)
        for yid in names:
            a, b = old.get(yid), new.get(yid)
            strip = lambda x: x and {k: v for k, v in x.items() if k != "shares"}  # noqa: E731
            if strip(a) != strip(b):
                changes.append(f"{r['name']}: {names[yid]} {_label(a)} -> {_label(b)}")
    return changes


def _plan(setup, feed, new_setup, today, what):
    try:
        check_setup(new_setup, {y["id"] for y in feed["yachts"]})
    except SharingError as e:
        raise AdminError(str(e)) from None
    changes = diff(setup, new_setup, feed, today)
    return {
        "summary": f"{what}. {len(changes) or 'No'} access change{'s' if len(changes) != 1 else ''}"
                   + (": " + "; ".join(changes[:5]) + (" ..." if len(changes) > 5 else ".") if changes else "."),
        "changes": changes,
    }


def upsert(path, feed, kind, record, today, confirm=False):
    setup = load(path)
    _check_record(kind, record)
    new = copy.deepcopy(setup)
    items = new[KINDS[kind]]
    i = next((n for n, x in enumerate(items) if x["id"] == record["id"]), None)
    if kind == "key" and i is not None:
        record = {**items[i], **record}  # keep the stored secret hash
    verb = "Update" if i is not None else "Add"
    if i is None:
        items.append(record)
    else:
        items[i] = record
    out = _plan(setup, feed, new, today, f"{verb} {kind} {record['id']}")
    out["record"] = {k: v for k, v in record.items() if k != "secret_sha256"}
    return _finish(path, new, out, confirm)


def delete(path, feed, kind, item_id, today, confirm=False):
    setup = load(path)
    if kind not in KINDS:
        raise AdminError(f"kind must be one of {sorted(KINDS)}")
    new = copy.deepcopy(setup)
    before = len(new[KINDS[kind]])
    new[KINDS[kind]] = [x for x in new[KINDS[kind]] if x["id"] != item_id]
    if len(new[KINDS[kind]]) == before:
        raise AdminError(f"no {kind} '{item_id}'")
    also = []
    if kind == "recipient":
        people = [r["name"] for r in new["recipients"] if r.get("company") == item_id]
        if people:
            raise AdminError(f"{item_id} still has people: {', '.join(people)}. Move or delete them first")
        also += [f"share {x['id']}" for x in new["shares"] if x["to"].get("recipient") == item_id]
        also += [f"key {x['id']}" for x in new["keys"] if x["recipient"] == item_id]
        new["shares"] = [x for x in new["shares"] if x["to"].get("recipient") != item_id]
        new["keys"] = [x for x in new["keys"] if x["recipient"] != item_id]
    elif kind == "group":
        also += [f"share {x['id']}" for x in new["shares"] if x["to"].get("group") == item_id]
        new["shares"] = [x for x in new["shares"] if x["to"].get("group") != item_id]
        for r in new["recipients"]:
            if item_id in r.get("groups", []):
                r["groups"] = [g for g in r["groups"] if g != item_id]
    elif kind == "boat_set":
        also += [f"share {x['id']}" for x in new["shares"] if x["boats"].get("set") == item_id]
        new["shares"] = [x for x in new["shares"] if x["boats"].get("set") != item_id]
    what = f"Delete {kind} {item_id}" + (f", and with it {', '.join(also)}" if also else "")
    return _finish(path, new, _plan(setup, feed, new, today, what), confirm)


def issue_key(path, feed, recipient, label, today, expires_at=None, confirm=False):
    setup = load(path)
    if not any(r["id"] == recipient for r in setup["recipients"]):
        raise AdminError(f"no recipient '{recipient}'")
    key_id = f"K-{recipient.removeprefix('R-')}-{sum(1 for k in setup['keys'] if k['recipient'] == recipient) + 1}"
    record = {"id": key_id, "recipient": recipient, "label": label, "expires_at": expires_at}
    if not confirm:
        return {"summary": f"Issue key {key_id} to {recipient}. The secret is shown once, when you confirm.",
                "record": record, "confirmed": False}
    secret = "ycs_" + secrets.token_urlsafe(32)
    record["secret_sha256"] = hashlib.sha256(secret.encode()).hexdigest()
    setup["keys"].append(record)
    save(path, setup)
    return {"summary": f"Key {key_id} issued. Send the secret to the recipient now: it is not stored and cannot be shown again.",
            "record": {k: v for k, v in record.items() if k != "secret_sha256"}, "secret": secret, "confirmed": True}


def revoke_key(path, feed, key_id, today, confirm=False):
    setup = load(path)
    key = next((k for k in setup["keys"] if k["id"] == key_id), None)
    if key is None:
        raise AdminError(f"no key '{key_id}'")
    new = copy.deepcopy(setup)
    next(k for k in new["keys"] if k["id"] == key_id)["revoked"] = True
    out = {"summary": f"Revoke key {key_id} ({key.get('label', '')}). It stops working on the next request; the recipient's other keys are not affected."}
    return _finish(path, new, out, confirm)


def preview(path, feed, who, today):
    setup = load(path)
    key = next((k for k in setup["keys"] if k["id"] == who), None)
    recipient = key["recipient"] if key else who
    names = {y["id"]: y["name"] for y in feed["yachts"]}
    try:
        access = access_for_recipient(setup, feed, recipient, today)
    except SharingError as e:
        raise AdminError(str(e)) from None
    rows = [{"yacht": names[y], "id": y, "shared": y in access,
             **({p: access[y][p] for p in PARTS} if y in access else {}),
             **({"months_ahead": access[y]["months_ahead"], "shares": access[y]["shares"]} if y in access else {})}
            for y in names]
    return {"summary": f"{recipient} sees {len(access)} of {len(names)} yachts.", "yachts": rows}


def list_items(path, kind):
    if kind not in KINDS:
        raise AdminError(f"kind must be one of {sorted(KINDS)}")
    items = load(path)[KINDS[kind]]
    return {"summary": f"{len(items)} {KINDS[kind].replace('_', ' ')}.",
            "items": [{k: v for k, v in x.items() if k != "secret_sha256"} for x in items]}


def _finish(path, new, out, confirm):
    if confirm:
        save(path, new)
        out["confirmed"] = True
        out["summary"] = "Done. " + out["summary"]
    else:
        out["confirmed"] = False
        out["summary"] += " Nothing is saved yet: call again with confirm=true to apply."
    return out
