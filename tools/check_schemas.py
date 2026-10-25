#!/usr/bin/env python3
"""Check every example feed against schema/feed.schema.json (needs jsonschema>=4.18)."""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

root = Path(__file__).resolve().parent.parent
base = "https://github.com/mopristas/yacht-calendar-standard/schema/"
registry = Registry().with_resources(
    (base + p.name, Resource.from_contents(json.loads(p.read_text()))) for p in (root / "schema").glob("*.json")
)
feed_schema = json.loads((root / "schema/feed.schema.json").read_text())
validator = Draft202012Validator(feed_schema, registry=registry)
failed = 0
sharing = Draft202012Validator(json.loads((root / "schema/sharing.schema.json").read_text()), registry=registry)
for path in sorted((root / "examples").glob("*.json")):
    if path.name == "key.json":
        continue
    v = sharing if path.name == "sharing.json" else validator
    errs = list(v.iter_errors(json.loads(path.read_text())))
    for e in errs:
        print(f"{path.name}: {'/'.join(map(str, e.path))}: {e.message}")
    print(f"{path.name}: {'OK' if not errs else 'FAIL'}")
    failed += bool(errs)
sys.exit(1 if failed else 0)
