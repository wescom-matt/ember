#!/usr/bin/env python3
"""Add printable parts and repair guides to Ember's offline parts library.

Run on the P1 from ~/ember:
  .venv/bin/python scripts/parts_import.py add-file FILE [FILE...] --name N --category C --license L \
        [--source URL] [--author A] [--tags "a b"] [--notes "print notes"]
  .venv/bin/python scripts/parts_import.py add-url URL --name N --category C --license L [...]
  .venv/bin/python scripts/parts_import.py seed [--max-gb 3] [--only github|ifixit|scad]   (cap = whole library)
  .venv/bin/python scripts/parts_import.py list [QUERY]
  .venv/bin/python scripts/parts_import.py stats
  .venv/bin/python scripts/parts_import.py remove PART_ID

License is required (CC0, CC-BY*, GPL, MIT, BSD, Public-Domain ...). Items without one are refused.
"""

from __future__ import annotations

import argparse
import hashlib
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
        self.full = False

    def take(self, n: int) -> bool:
        if n > self.left:
            return False
        self.left -= n
        return True


LICENSE_WORDS = {
    "MIT": ("permission is hereby granted",),
    "GPL": ("gnu general public license",),
    "LGPL": ("lesser general public license", "gnu general public license"),
    "AGPL": ("affero general public license",),
    "CC": ("creative commons", "attribution"),
    "CC0": ("cc0", "creative commons zero", "public domain"),
    "Public-Domain": ("unlicense", "public domain"),
    "BSD": ("redistribution and use",),
    "0BSD": ("permission to use, copy, modify",),
    "ISC": ("permission to use, copy, modify",),
    "Apache": ("apache license",),
    "MPL": ("mozilla public license",),
    "CERN": ("cern open hardware",),
}
MAX_REPO_BYTES = 200 * 1024 * 1024  # skip oversized repos
MODEL_PREFERRED = (".stl", ".3mf", ".step", ".stp")


def license_text_matches(lic: str, text: str) -> bool:
    """The repo's own LICENSE file must agree with the recorded SPDX id."""
    low = text.lower()
    for key in sorted(LICENSE_WORDS, key=len, reverse=True):
        if lic.upper().startswith(key.upper()):
            return any(w in low for w in LICENSE_WORDS[key])
    return False


def repo_license(src: dict[str, Any]) -> str:
    lic = str(src.get("license") or "")
    if not lic:  # fall back to GitHub's own detection (rate-limited API)
        info = get_json(f"https://api.github.com/repos/{src['repo']}")
        lic = ((info.get("license") or {}).get("spdx_id") or "").strip()
    return SPDX_FIX.get(lic, lic)


LICENSE_NAMES = ("license", "licence", "copying")


def _is_license(path: str) -> bool:
    return path.rsplit("/", 1)[-1].lower().startswith(LICENSE_NAMES)


def fetch_repo(src: dict[str, Any], tmp: Path) -> tuple[str, dict[str, list[Path]]]:
    """Download the repo tarball once; return (license text to check, {group: [model files]}).

    Conservative license rules: several root license files (e.g. MIT code + CC case) need an explicit
    'license_file' in the seed entry, else the text returned is '' and the repo is skipped. Model files
    in a sub-folder that has its own license file are left out (they may be under other terms)."""
    import tarfile  # noqa: PLC0415

    tar_path = tmp / "repo.tgz"
    tar_path.write_bytes(get(f"https://codeload.github.com/{src['repo']}/tar.gz/{src['ref']}", MAX_REPO_BYTES))
    include = src.get("include") or [""]
    exclude = [x.lower() for x in src.get("exclude") or []]
    exts = MODEL_PREFERRED + ((".scad",) if src.get("scad") else ())
    depth = int(src.get("group_depth", 0))
    groups: dict[str, list[Path]] = {}
    root_lic: dict[str, str] = {}
    sub_lic_dirs: list[str] = []
    with tarfile.open(tar_path, "r:gz") as tar:
        members = [m for m in tar.getmembers() if m.isfile() and "/" in m.name]
        for m in members:
            path = m.name.split("/", 1)[1]
            if _is_license(path) and m.size < 300_000:
                if "/" in path:
                    sub_lic_dirs.append(path.rsplit("/", 1)[0] + "/")
                else:
                    fh = tar.extractfile(m)
                    root_lic[path] = fh.read().decode("utf-8", "replace") if fh else ""
        for m in members:
            path = m.name.split("/", 1)[1]
            low = path.lower()
            if m.size <= 0 or m.size > parts.MAX_FILE_BYTES or not low.endswith(exts):
                continue
            if any(x in low for x in exclude) or not any(path.startswith(p) for p in include):
                continue
            if any(path.startswith(d) for d in sub_lic_dirs):
                continue
            fh = tar.extractfile(m)
            if fh is None:
                continue
            key = "/".join(path.split("/")[:depth]) if depth else ""
            dest = tmp / "f" / str(len(groups)) / parts.safe_name(path.replace("/", "_")[-120:])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(fh.read())
            groups.setdefault(key, []).append(dest)
    tar_path.unlink()
    if src.get("license_file"):
        text = root_lic.get(str(src["license_file"]), "")
    else:
        text = next(iter(root_lic.values())) if len(root_lic) == 1 else ""
    return text, groups


def seed_github(conn: Any, data_dir: Path, src: dict[str, Any], budget: Budget, seen: set[str]) -> int:
    repo, ref = src["repo"], src["ref"]
    lic = repo_license(src)
    try:
        parts.check_license(lic)
    except parts.PartsError:
        print(f"  skip {repo}: license '{lic or 'none'}' not accepted")
        return 0
    added = 0
    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        lic_text, groups = fetch_repo(src, tmp)
        if not license_text_matches(lic, lic_text):
            print(f"  skip {repo}: no single LICENSE file matching {lic} (set license_file after checking by hand)")
            return 0
        for key, files in sorted(groups.items()):
            label = f"{src.get('name') or repo.split('/')[1]}{' - ' + key.replace('/', ' - ') if key else ''}"
            name = parts.safe_name(label.replace("_", " ")[:120])
            url = f"https://github.com/{repo}/tree/{ref}/{urllib.parse.quote(key)}".rstrip("/")
            if conn.execute("SELECT 1 FROM parts WHERE source_url = ? AND name = ?", (url, name)).fetchone():
                continue
            fresh = []
            for f in files[: int(src.get("max_files", 60))]:
                digest = hashlib.sha256(f.read_bytes()).hexdigest()
                if digest not in seen:  # de-duplicate identical files across sources
                    seen.add(digest)
                    fresh.append(f)
            size = sum(f.stat().st_size for f in fresh)
            if not fresh:
                continue
            if not budget.take(size):
                print(f"  stop: size cap reached at {name}")
                budget.full = True
                return added
            meta = {
                "name": name,
                "category": src["category"],
                "license": lic,
                "source_url": url,
                "author": src.get("author") or repo.split("/")[0],
                "tags": src.get("tags", ""),
                "notes": src.get("notes", ""),
                "description": str(src.get("description") or "")[:500],
            }
            try:
                parts.add_part(conn, data_dir, meta, fresh)
                added += 1
                print(f"  + [{src['category']}] {name} ({len(fresh)} files, {size / 1e6:.1f} MB, {lic})")
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
        src_url = f"ember:coldboot/parts-scad/{item['scad']}"
        if conn.execute("SELECT 1 FROM parts WHERE source_url = ? AND name = ?", (src_url, item["name"])).fetchone():
            continue  # already in the library
        meta = {
            **item,
            "license": cfg["license"],
            "author": cfg["author"],
            "source_url": src_url,
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
    used = int(parts.stats(conn, data_dir)["bytes"])
    budget = Budget(max(0, int(args.max_gb * 1e9) - used))  # the cap is for the whole library
    seen = parts.known_hashes(conn)
    if args.only in ("", "scad"):
        seed_scad(conn, data_dir, cfg["scad"])
    if args.only in ("", "github"):
        for src in cfg["github"]:  # list order = priority
            if budget.full:
                break
            try:
                seed_github(conn, data_dir, src, budget, seen)
            except (OSError, ValueError, KeyError, parts.PartsError) as exc:
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
    rp = sub.add_parser("remove")
    rp.add_argument("part_id", type=int)
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
        elif args.cmd == "remove":
            ok = parts.remove_part(parts.open_db(data_dir), data_dir, args.part_id)
            print("removed" if ok else "no such part")
        else:
            print(json.dumps(parts.stats(parts.open_db(data_dir), data_dir), indent=1))
    except (parts.PartsError, ValueError, OSError) as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
