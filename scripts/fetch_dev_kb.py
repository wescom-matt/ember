#!/usr/bin/env python3
"""Download the developer reference documents and build Ember's offline dev knowledge base.

Run while online (on the P1, from ~/ember):
    .venv/bin/python scripts/fetch_dev_kb.py                  # fetch + build (~70 MB)
    .venv/bin/python scripts/fetch_dev_kb.py --with-api-docs  # also the Flutter API docset (~105 MB)
    .venv/bin/python scripts/fetch_dev_kb.py --rebuild        # rebuild the index from saved files (offline)

Files: <data_dir>/dev-kb/raw/, list of sources: dev-kb/SOURCES.json, index: dev-kb/index.db.
PDF text needs `pdftotext` (poppler-utils, installed on Ubuntu desktops).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sqlite3
import subprocess  # nosec B404 - fixed argument lists, no shell
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ember.config import load_settings  # noqa: E402
from ember.dev_kb import API_DOCS, DEV_SOURCES, kb_dir  # noqa: E402
from ember.radio_kb import SCHEMA, chunks, html_sections  # noqa: E402

UA = "Mozilla/5.0 (X11; Linux x86_64) Ember-offline-dev-kb/0.5 (personal offline reference)"
MAX_BYTES = 120_000_000
TEXT_SUFFIXES = (".rst", ".md", ".txt")
MAX_FILES = 5000
CMD_TIMEOUT = 900


def fetch(url: str, dest: Path) -> int:
    if not url.startswith("https://"):
        raise ValueError("https only")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 # nosec B310 - fixed https source list
        if not resp.geturl().startswith("https://"):
            raise ValueError("redirected away from https")
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("file too large")
    dest.write_bytes(data)
    return len(data)


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=CMD_TIMEOUT, check=False)  # noqa: S603 # nosec B603


def get_git_docs(src: dict[str, str], dest: Path) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        res = run(
            [
                "git",
                "clone",
                "-q",
                "--depth",
                "1",
                "--filter=blob:none",
                "--sparse",
                "--branch",
                src["ref"],
                src["url"],
                str(repo),
            ]
        )
        if res.returncode != 0:
            raise OSError(res.stderr.strip()[:200])
        sparse = ["set", src["path"]] if src["path"] else ["disable"]
        res = run(["git", "-C", str(repo), "sparse-checkout", *sparse])
        if res.returncode != 0:
            raise OSError(res.stderr.strip()[:200])
        shutil.rmtree(dest, ignore_errors=True)
        keep = tuple(src.get("suffixes", " ".join(TEXT_SUFFIXES)).split())
        count = 0
        for f in sorted((repo / src["path"]).rglob("*")):
            if ".git" in f.parts:
                continue
            if f.is_file() and (f.suffix in keep or f.name in keep) and count < MAX_FILES:
                out = dest / f.relative_to(repo / src["path"])
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, out)
                count += 1
    return count


def get_headers(src: dict[str, str], dest: Path) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tgz = Path(tmp) / "src.tar.gz"
        fetch(src["url"], tgz)
        shutil.rmtree(dest, ignore_errors=True)
        count = 0
        with tarfile.open(tgz) as tar:
            for m in tar.getmembers():
                parts = Path(m.name).parts
                if not m.isfile() or ".." in parts or "src" not in parts or not m.name.endswith(".h"):
                    continue
                rel = Path(*parts[parts.index("src") :])
                fh = tar.extractfile(m)
                if fh is None or count >= MAX_FILES:
                    continue
                out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(fh.read())
                count += 1
    return count


def pdf_pages(path: Path) -> list[tuple[str, str]]:
    if shutil.which("pdftotext") is None:
        print(f"  ! pdftotext missing: {path.name} kept but not searchable")
        return []
    res = run(["pdftotext", "-layout", "-q", str(path), "-"])
    pages = res.stdout.split("\f")
    return [(f"page {i}", " ".join(p.split()) if len(p) < 200 else p) for i, p in enumerate(pages, 1) if p.strip()]


def text_files(folder: Path) -> list[tuple[str, str]]:
    out = []
    for f in sorted(folder.rglob("*")):
        if f.is_file() and f.suffix == ".pdf":
            out += [(f"{f.relative_to(folder)} {h}", t) for h, t in pdf_pages(f)]
        elif f.is_file():
            out.append((str(f.relative_to(folder)), f.read_text(encoding="utf-8", errors="replace")))
    return out


def sections_for(src: dict[str, str], raw: Path) -> list[tuple[str, str]]:
    kind, sid = src["kind"], src["id"]
    if kind == "pdf" and (raw / f"{sid}.pdf").is_file():
        return pdf_pages(raw / f"{sid}.pdf")
    if kind in ("git-docs", "tar-headers") and (raw / sid).is_dir():
        return text_files(raw / sid)
    if kind == "html" and (raw / f"{sid}.html").is_file():
        return html_sections((raw / f"{sid}.html").read_text(encoding="utf-8", errors="replace"))
    return []


def download(src: dict[str, str], raw: Path) -> str:
    kind, sid = src["kind"], src["id"]
    if kind == "git-docs":
        return f"{get_git_docs(src, raw / sid)} files"
    if kind == "tar-headers":
        return f"{get_headers(src, raw / sid)} headers"
    suffix = {"pdf": ".pdf", "html": ".html"}.get(kind, Path(src["url"]).suffix)
    return f"{fetch(src['url'], raw / (sid + suffix)):,} bytes"


def digest(raw: Path, sid: str) -> tuple[str, int]:
    files = [p for p in raw.iterdir() if p.is_file() and p.stem == sid]
    if (raw / sid).is_dir():
        files += sorted(p for p in (raw / sid).rglob("*") if p.is_file())
    h = hashlib.sha256()
    size = 0
    for f in files:
        data = f.read_bytes()
        h.update(data)
        size += len(data)
    return h.hexdigest(), size


def build_index(kb: Path, raw: Path, meta: dict[str, dict[str, object]]) -> int:
    tmp = kb / "index.tmp"
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)
    total = 0
    for src in DEV_SOURCES:
        info = meta.get(src["id"])
        if not info:
            continue
        conn.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?)",
            (src["id"], src["title"], src["url"], str(info["retrieved"]), str(info["sha256"])),
        )
        parts = chunks(sections_for(src, raw))
        conn.executemany(
            "INSERT INTO passages(source_id, heading, body) VALUES (?, ?, ?)", [(src["id"], h, b) for h, b in parts]
        )
        total += len(parts)
    conn.commit()
    conn.close()
    tmp.replace(kb / "index.db")
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rebuild", action="store_true", help="only rebuild the index from saved files")
    ap.add_argument("--with-api-docs", action="store_true", help="also download the Flutter API docset")
    args = ap.parse_args()
    kb = kb_dir(load_settings().data_dir)
    raw = kb / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    manifest = kb / "SOURCES.json"
    meta: dict[str, dict[str, object]] = json.loads(manifest.read_text()) if manifest.is_file() else {}
    today = dt.date.today().isoformat()
    for src in DEV_SOURCES if not args.rebuild else []:
        try:
            print(f"  ok {src['id']}: {download(src, raw)}")
            meta[src["id"]] = {"retrieved": today}
        except (OSError, ValueError, tarfile.TarError, subprocess.TimeoutExpired) as exc:
            print(f"  ! {src['id']}: {exc} (keeping any older copy)")
        time.sleep(1)
    for src in DEV_SOURCES:
        sha, size = digest(raw, src["id"])
        if size:
            entry = meta.setdefault(src["id"], {"retrieved": today})
            entry.update(
                {"title": src["title"], "url": src["url"], "terms": src["terms"], "sha256": sha, "bytes": size}
            )
        else:
            meta.pop(src["id"], None)
    if args.with_api_docs:
        api = kb / "api"
        api.mkdir(exist_ok=True)
        for src in API_DOCS:
            try:
                n = fetch(src["url"], api / Path(src["url"]).name)
                meta[src["id"]] = {
                    "title": src["title"],
                    "url": src["url"],
                    "terms": src["terms"],
                    "retrieved": today,
                    "bytes": n,
                    "indexed": False,
                }
                print(f"  ok {src['id']}: {n:,} bytes (browse only)")
            except (OSError, ValueError) as exc:
                print(f"  ! {src['id']}: {exc}")
    manifest.write_text(json.dumps(meta, indent=2))
    total = build_index(kb, raw, meta)
    print(f"Dev KB: {len(meta)} sources, {total} passages -> {kb / 'index.db'}")
    return 0 if meta else 1


if __name__ == "__main__":
    raise SystemExit(main())
