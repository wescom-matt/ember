#!/usr/bin/env python3
"""Make stand-alone Centauri Carbon 2 slicer profiles for the OrcaSlicer command line.

OrcaSlicer 2.5 ships its vendor profiles packed, and its CLI only accepts JSON files
whose 'inherits' chain it can resolve, so we fetch Elegoo's CC2 profiles from the
OrcaSlicer source at a pinned tag and merge each inheritance chain into one file.

    python3 cc2_profiles.py OUTDIR            # needs internet once (GitHub)
    -> OUTDIR/machine/*.json  OUTDIR/process/*.json  OUTDIR/filament/*.json  OUTDIR/SOURCE.txt

Profiles are from OrcaSlicer (AGPL-3.0), unchanged except for the merge.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

TAG = "v2.5.2"
REPO = "OrcaSlicer/OrcaSlicer"
ROOT = "resources/profiles/Elegoo/"
UA = {"User-Agent": "ember-coldboot"}
MAX_FILES = 400


def get(url: str, limit: int = 5_000_000) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("https only")
    req = urllib.request.Request(url, headers=UA)  # noqa: S310
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 # nosec B310 - fixed GitHub URLs
        return bytes(resp.read(limit))


def wanted(path: str) -> bool:
    rel = path[len(ROOT) :]
    return path.endswith(".json") and ("ECC2" in rel or "/BASE/" in rel or rel.count("/") == 1)


def fetch() -> dict[str, tuple[str, dict[str, Any]]]:
    tree = json.loads(get(f"https://api.github.com/repos/{REPO}/git/trees/{TAG}?recursive=1", 60_000_000))
    paths = [t["path"] for t in tree["tree"] if t["path"].startswith(ROOT) and wanted(t["path"])][:MAX_FILES]
    by_name: dict[str, tuple[str, dict[str, Any]]] = {}
    for path in paths:
        raw = get(f"https://raw.githubusercontent.com/{REPO}/{TAG}/{urllib.parse.quote(path)}")
        data = json.loads(raw)
        kind = path[len(ROOT) :].split("/", 1)[0]
        if isinstance(data, dict) and data.get("name"):
            by_name[str(data["name"])] = (kind, data)
    return by_name


def flatten(name: str, by_name: dict[str, tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    chain: list[dict[str, Any]] = []
    current: str | None = name
    for _ in range(12):  # bounded inheritance depth
        if not current or current not in by_name:
            break
        data = by_name[current][1]
        chain.append(data)
        current = data.get("inherits") or None
    merged: dict[str, Any] = {}
    for data in reversed(chain):
        merged.update(data)
    merged.pop("inherits", None)
    merged["name"] = name
    merged["from"] = "User"
    return merged


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out = Path(sys.argv[1])
    by_name = fetch()
    count = 0
    for name, (kind, data) in sorted(by_name.items()):
        if str(data.get("instantiation", "")).lower() != "true":
            continue
        if not any(k in name for k in ("Centauri Carbon 2", "CC2", "ECC2")):
            continue
        dest = out / kind / f"{name}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(flatten(name, by_name), indent=1))
        count += 1
    (out / "SOURCE.txt").write_text(f"https://github.com/{REPO}/tree/{TAG}/{ROOT} (AGPL-3.0), merged by Ember\n")
    print(f"{count} CC2 profiles -> {out}")
    return 0 if count else 1


if __name__ == "__main__":
    raise SystemExit(main())
