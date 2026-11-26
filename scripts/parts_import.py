#!/usr/bin/env python3
"""Add printable parts and repair guides to Ember's offline parts library.

Run on the P1 from ~/ember:
  .venv/bin/python scripts/parts_import.py add-file FILE [FILE...] --name N --category C --license L \
        [--source URL] [--author A] [--tags "a b"] [--notes "print notes"]
  .venv/bin/python scripts/parts_import.py add-url URL --name N --category C --license L [...]
  .venv/bin/python scripts/parts_import.py seed [--max-gb 3] [--only github|ifixit|scad]
  .venv/bin/python scripts/parts_import.py list [QUERY]
  .venv/bin/python scripts/parts_import.py stats

License is required (CC0, CC-BY*, GPL, MIT, BSD, Public-Domain ...). Items without one are refused.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ember import parts  # noqa: E402
from ember.config import load_settings  # noqa: E402

UA = {"User-Agent": "Ember-parts-library/0.4 (personal offline use)"}
SPDX_FIX = {"GPL-3.0": "GPL-3.0", "GPL-2.0": "GPL-2.0", "CC0-1.0": "CC0-1.0", "Unlicense": "Public-Domain"}


def get(url: str, limit: int = parts.MAX_FILE_BYTES) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("https only")
    req = urllib.request.Request(url, headers=UA)  # noqa: S310
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 # nosec B310 - https only
        data = bytes(resp.read(limit + 1))
    if len(data) > limit:
        raise ValueError("file too large")
    return data


def get_json(url: str) -> Any:
    return json.loads(get(url, 80_000_000))


def meta_from(args: argparse.Namespace, source: str) -> dict[str, Any]:
    return {
        "name": args.name,
        "category": args.category,
        "license": args.license,
        "source_url": source,
        "author": args.author,
        "tags": args.tags,
        "notes": args.notes,
    }


def cmd_add_file(args: argparse.Namespace, data_dir: Path) -> None:
    conn = parts.open_db(data_dir)
    part_id = parts.add_part(conn, data_dir, meta_from(args, args.source or "local"), [Path(f) for f in args.files])
    print(f"added part #{part_id}")


def cmd_add_url(args: argparse.Namespace, data_dir: Path) -> None:
    name = parts.safe_name(urllib.parse.unquote(urllib.parse.urlparse(args.url).path))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(get(args.url))
        conn = parts.open_db(data_dir)
        part_id = parts.add_part(conn, data_dir, meta_from(args, args.url), [path])
    print(f"added part #{part_id} from {args.url}")


class Budget:
    def __init__(self, max_bytes: int) -> None:
        self.left = max_bytes

    def take(self, n: int) -> bool:
        if n > self.left:
            return False
        self.left -= n
        return True


def seed_github(conn: Any, data_dir: Path, src: dict[str, Any], budget: Budget) -> int:
    repo, ref = src["repo"], src["ref"]
    info = get_json(f"https://api.github.com/repos/{repo}")
    spdx = ((info.get("license") or {}).get("spdx_id") or "").strip()
    lic = SPDX_FIX.get(spdx, spdx)
    try:
        parts.check_license(lic)
    except parts.PartsError:
        print(f"  skip {repo}: license '{spdx or 'none'}' not accepted")
        return 0
    tree = get_json(f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1")["tree"]
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in tree:
        path = item["path"]
        if item["type"] != "blob" or not path.lower().endswith(parts.MODEL_EXT):
            continue
        if not any(path.startswith(p) for p in src["include"]):
            continue
        depth = int(src.get("group_depth", 0))
        key = "/".join(path.split("/")[:depth]) if depth else ""
        groups.setdefault(key, []).append(item)
    added = 0
    author = repo.split("/")[0]
    for key, items in sorted(groups.items()):
        name = f"{info.get('name', repo)}{' - ' + key.replace('_', ' ') if key else ''}"[:120]
        url = f"https://github.com/{repo}/tree/{ref}/{urllib.parse.quote(key)}"
        if conn.execute("SELECT 1 FROM parts WHERE source_url = ? AND name = ?", (url, name)).fetchone():
            continue
        size = sum(int(i.get("size", 0)) for i in items[:100])
        if not budget.take(size):
            print(f"  stop: size cap reached at {name}")
            return added
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for i in items[:100]:
                raw = get(f"https://raw.githubusercontent.com/{repo}/{ref}/{urllib.parse.quote(i['path'])}")
                dest = Path(tmp) / parts.safe_name(i["path"].replace("/", "_")[-120:])
                dest.write_bytes(raw)
                files.append(dest)
            meta = {
                "name": name,
                "category": src["category"],
                "license": lic,
                "source_url": url,
                "author": author,
                "tags": src.get("tags", ""),
                "notes": src.get("notes", ""),
                "description": (info.get("description") or "")[:500],
            }
            try:
                parts.add_part(conn, data_dir, meta, files)
                added += 1
                print(f"  + {name} ({len(files)} files, {size / 1e6:.1f} MB, {lic})")
            except parts.PartsError as exc:
                print(f"  skip {name}: {exc}")
    return added


def guide_text(g: dict[str, Any]) -> str:
    lines = [g.get("title", ""), g.get("introduction_raw", "") or ""]
    for n, step in enumerate(g.get("steps") or [], 1):
        title = step.get("title") or ""
        lines.append(f"Step {n}{': ' + title if title else ''}")
        lines.extend(f"- {ln.get('text_raw', '')}" for ln in step.get("lines") or [])
    tools = ", ".join(t.get("text", "") for t in g.get("tools") or [])
    parts_used = ", ".join(t.get("text", "") for t in g.get("parts") or [])
    if tools:
        lines.append(f"Tools: {tools}")
    if parts_used:
        lines.append(f"Parts: {parts_used}")
    return "\n".join(x for x in lines if x)


def seed_ifixit(conn: Any, cfg: dict[str, Any]) -> int:
    added = 0
    for query in cfg["queries"]:
        q = urllib.parse.quote(query)
        found = get_json(f"https://www.ifixit.com/api/2.0/search/{q}?filter=guide&limit={int(cfg['per_query'])}")
        for hit in found.get("results", []):
            gid = int(hit.get("guideid") or 0)
            url = f"https://www.ifixit.com/Guide/_/{gid}"
            if not gid or conn.execute("SELECT 1 FROM guides WHERE source_url = ?", (url,)).fetchone():
                continue
            g = get_json(f"https://www.ifixit.com/api/2.0/guides/{gid}")
            meta = {
                "title": g.get("title", ""),
                "category": query,
                "license": cfg["license"],
                "source_url": url,
                "author": (g.get("author") or {}).get("username", "iFixit"),
            }
            try:
                parts.add_guide(conn, meta, guide_text(g))
                added += 1
            except parts.PartsError:
                continue
            time.sleep(0.5)
        print(f"  ifixit '{query}': total {added}")
    return added


def seed_scad(conn: Any, data_dir: Path, cfg: dict[str, Any]) -> int:
    folder = REPO / cfg["dir"]
    manifest = json.loads((folder / "parts.json").read_text())
    added = 0
    for item in manifest:
        files = [folder / "stl" / f for f in item["stl"]] + [folder / item["scad"]]
        files = [f for f in files if f.is_file()]
        meta = {
            **item,
            "license": cfg["license"],
            "author": cfg["author"],
            "source_url": f"ember:coldboot/parts-scad/{item['scad']}",
        }
        try:
            parts.add_part(conn, data_dir, meta, files)
            added += 1
        except parts.PartsError as exc:
            print(f"  skip {item['name']}: {exc}")
    print(f"  scad parts: {added}")
    return added


def cmd_seed(args: argparse.Namespace, data_dir: Path) -> None:
    cfg = json.loads((REPO / "coldboot/parts-seed.json").read_text())
    conn = parts.open_db(data_dir)
    budget = Budget(int(args.max_gb * 1e9))
    if args.only in ("", "scad"):
        seed_scad(conn, data_dir, cfg["scad"])
    if args.only in ("", "github"):
        for src in cfg["github"]:
            try:
                seed_github(conn, data_dir, src, budget)
            except (OSError, ValueError, KeyError) as exc:
                print(f"  ! {src['repo']}: {exc}")
    if args.only in ("", "ifixit"):
        try:
            seed_ifixit(conn, cfg["ifixit"])
        except (OSError, ValueError, KeyError) as exc:
            print(f"  ! ifixit: {exc}")
    print(json.dumps(parts.stats(conn, data_dir), indent=1))


def main() -> int:
    ap = argparse.ArgumentParser(description="Ember parts library import")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("add-file", "add-url"):
        p = sub.add_parser(name)
        if name == "add-file":
            p.add_argument("files", nargs="+")
            p.add_argument("--source", default="")
        else:
            p.add_argument("url")
        p.add_argument("--name", required=True)
        p.add_argument("--category", required=True, choices=parts.CATEGORIES)
        p.add_argument("--license", required=True)
        p.add_argument("--author", default="")
        p.add_argument("--tags", default="")
        p.add_argument("--notes", default="")
    s = sub.add_parser("seed")
    s.add_argument("--max-gb", type=float, default=3.0)
    s.add_argument("--only", default="", choices=["", "github", "ifixit", "scad"])
    lp = sub.add_parser("list")
    lp.add_argument("query", nargs="?", default="")
    sub.add_parser("stats")
    args = ap.parse_args()
    data_dir = load_settings().data_dir
    try:
        if args.cmd == "add-file":
            cmd_add_file(args, data_dir)
        elif args.cmd == "add-url":
            cmd_add_url(args, data_dir)
        elif args.cmd == "seed":
            cmd_seed(args, data_dir)
        elif args.cmd == "list":
            for h in parts.search(parts.open_db(data_dir), args.query, 50):
                print(f"{h['kind']:5} #{h['id']:<4} {h.get('name') or h.get('title')}  [{h['license']}]")
        else:
            print(json.dumps(parts.stats(parts.open_db(data_dir), data_dir), indent=1))
    except (parts.PartsError, ValueError, OSError) as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
