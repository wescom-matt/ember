"""Offline 3D parts library: printable models + repair guides, searchable from chat.

Store: <data_dir>/parts/library.db (metadata + FTS5 search) and
       <data_dir>/parts/files/<part_id>/<file>  (STL/3MF/STEP/SCAD...).
Only openly licensed items are accepted (license is required and checked
against LICENSE_OK); attribution (author, source URL, license) is kept for each.
Add items with scripts/parts_import.py.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

MODEL_EXT = (".stl", ".3mf", ".step", ".stp", ".obj", ".scad")
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_SNIPPET = 700
NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,119}$")
# Open licenses only. NC/ND variants are fine for a personal offline library (recorded as-is).
LICENSE_OK = re.compile(
    r"^(CC0(-1\.0)?|CC-BY(-SA|-NC|-ND|-NC-SA|-NC-ND)?(-[0-9.]+)?|GPL-[23]\.0(-only|-or-later)?|LGPL-[0-9.]+.*|"
    r"AGPL-3\.0.*|MIT|BSD-[0-9]-Clause|Apache-2\.0|CERN-OHL-[A-Z]-2\.0|Public-Domain)$"
)
CATEGORIES = (
    "printer-parts",
    "corexy",
    "household",
    "off-grid",
    "electronics-enclosure",
    "antenna-radio",
    "tools",
    "storage",
    "other",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS parts(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, source_url TEXT NOT NULL,
  license TEXT NOT NULL, author TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', files TEXT NOT NULL DEFAULT '[]',
  added_at INTEGER NOT NULL, UNIQUE(source_url, name));
CREATE TABLE IF NOT EXISTS guides(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL UNIQUE,
  license TEXT NOT NULL, author TEXT NOT NULL DEFAULT '', body TEXT NOT NULL, added_at INTEGER NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(kind UNINDEXED, ref UNINDEXED, title, body, tokenize='porter');
"""


class PartsError(Exception):
    """Message is safe to show."""


def root(data_dir: Path) -> Path:
    return data_dir / "parts"


def open_db(data_dir: Path) -> sqlite3.Connection:
    root(data_dir).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root(data_dir) / "library.db", timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def check_license(lic: str) -> str:
    lic = (lic or "").strip()
    if not LICENSE_OK.fullmatch(lic):
        raise PartsError(f"license '{lic or 'none'}' is not an accepted open license (CC/GPL/MIT/BSD/PD); skipped")
    return lic


def safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9 ._()+-]", "_", base)[:120].lstrip(".") or "file"
    if not NAME_OK.fullmatch(base):
        raise PartsError("bad file name")
    return base


def add_part(conn: sqlite3.Connection, data_dir: Path, meta: dict[str, Any], files: list[Path]) -> int:
    """Copy files into the store and index them. meta: name, category, source_url, license, author, tags,
    notes, description."""
    lic = check_license(str(meta.get("license", "")))
    name = str(meta.get("name") or "").strip()[:120]
    category = str(meta.get("category") or "other")
    if not name or category not in CATEGORIES:
        raise PartsError(f"name required; category one of {', '.join(CATEGORIES)}")
    src = str(meta.get("source_url") or "local").strip()[:500]
    good = [f for f in files if f.suffix.lower() in MODEL_EXT and 0 < f.stat().st_size <= MAX_FILE_BYTES]
    if not good:
        raise PartsError("no model files (stl/3mf/step/obj/scad, <=200 MB)")
    if conn.execute("SELECT 1 FROM parts WHERE source_url = ? AND name = ?", (src, name)).fetchone():
        raise PartsError(f"already in the library: {name}")
    cur = conn.execute(
        "INSERT INTO parts(name, category, source_url, license, author, tags, notes, description, added_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            name,
            category,
            src,
            lic,
            str(meta.get("author", ""))[:200],
            str(meta.get("tags", ""))[:300],
            str(meta.get("notes", ""))[:1000],
            str(meta.get("description", ""))[:4000],
            int(time.time()),
        ),
    )
    part_id = int(cur.lastrowid or 0)
    dest = root(data_dir) / "files" / str(part_id)
    dest.mkdir(parents=True, exist_ok=True)
    stored: list[dict[str, Any]] = []
    for f in good[:100]:
        target = dest / safe_name(f.name)
        shutil.copyfile(f, target)
        stored.append(
            {
                "name": target.name,
                "size": target.stat().st_size,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    conn.execute("UPDATE parts SET files = ? WHERE id = ?", (json.dumps(stored), part_id))
    body = " ".join(str(meta.get(k, "")) for k in ("category", "tags", "notes", "description", "author"))
    conn.execute(
        "INSERT INTO search(kind, ref, title, body) VALUES ('part', ?, ?, ?)",
        (part_id, name, body + " " + " ".join(s["name"] for s in stored)),
    )
    conn.commit()
    return part_id


def add_guide(conn: sqlite3.Connection, meta: dict[str, Any], body: str) -> int:
    lic = check_license(str(meta.get("license", "")))
    url = str(meta.get("source_url") or "").strip()[:500]
    if not url or not body.strip():
        raise PartsError("guide needs a source URL and text")
    if conn.execute("SELECT 1 FROM guides WHERE source_url = ?", (url,)).fetchone():
        raise PartsError("guide already in the library")
    title = str(meta.get("title") or "Guide")[:200]
    cur = conn.execute(
        "INSERT INTO guides(title, category, source_url, license, author, body, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            title,
            str(meta.get("category", ""))[:60],
            url,
            lic,
            str(meta.get("author", ""))[:200],
            body[:200_000],
            int(time.time()),
        ),
    )
    guide_id = int(cur.lastrowid or 0)
    conn.execute("INSERT INTO search(kind, ref, title, body) VALUES ('guide', ?, ?, ?)", (guide_id, title, body))
    conn.commit()
    return guide_id


def get_part(conn: sqlite3.Connection, part_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM parts WHERE id = ?", (part_id,)).fetchone()
    if row is None:
        raise PartsError("no such part")
    item = dict(row)
    item["files"] = json.loads(item["files"] or "[]")
    return item


def part_file(data_dir: Path, conn: sqlite3.Connection, part_id: int, name: str) -> Path:
    part = get_part(conn, part_id)
    names = {f["name"] for f in part["files"]}
    if name not in names:
        raise PartsError("no such file in this part")
    return root(data_dir) / "files" / str(part_id) / name


def search(conn: sqlite3.Connection, query: str, limit: int) -> list[dict[str, Any]]:
    words = re.findall(r"[A-Za-z0-9]+", query.lower())[:12]
    if not words:
        rows = conn.execute("SELECT 'part' AS kind, id AS ref FROM parts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT kind, ref FROM search WHERE search MATCH ? ORDER BY bm25(search) LIMIT ?",
            (" OR ".join(f'"{w}"' for w in words), max(1, min(limit, 50))),
        ).fetchall()
    out = []
    for r in rows:
        if r["kind"] == "part":
            p = get_part(conn, int(r["ref"]))
            out.append(
                {
                    "kind": "part",
                    **{
                        k: p[k]
                        for k in ("id", "name", "category", "license", "author", "source_url", "tags", "notes", "files")
                    },
                }
            )
        else:
            g = conn.execute(
                "SELECT id, title, category, license, author, source_url, substr(body, 1, 600) AS body "
                "FROM guides WHERE id = ?",
                (int(r["ref"]),),
            ).fetchone()
            if g:
                out.append({"kind": "guide", **dict(g)})
    return out


def stats(conn: sqlite3.Connection, data_dir: Path) -> dict[str, Any]:
    files = root(data_dir) / "files"
    size = sum(f.stat().st_size for f in files.rglob("*") if f.is_file()) if files.is_dir() else 0
    cats = {r[0]: r[1] for r in conn.execute("SELECT category, COUNT(*) FROM parts GROUP BY category")}
    return {
        "parts": sum(cats.values()),
        "by_category": cats,
        "guides": conn.execute("SELECT COUNT(*) FROM guides").fetchone()[0],
        "bytes": size,
    }


class PartsKB:
    """Knowledge-base view of the library for chat (citations include license and source)."""

    id = "parts"
    label = "3D parts library + repair guides"
    description = "Printable parts (open licenses) and repair/maintenance guides, stored on the P1"

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        if not (root(self.data_dir) / "library.db").is_file():
            raise RuntimeError("parts library is empty (run scripts/parts_import.py seed)")
        conn = open_db(self.data_dir)
        try:
            hits = search(conn, query, top_k)
        finally:
            conn.close()
        out = []
        for i, h in enumerate(hits, 1):
            if h["kind"] == "part":
                files = ", ".join(f["name"] for f in h["files"][:6])
                text = (
                    f"Part #{h['id']} ({h['category']}). Files: {files}. Tags: {h['tags']}. {h['notes']} "
                    f"Slice/send it from the Parts screen."
                )
                title = h["name"]
            else:
                text, title = h["body"], h["title"]
            out.append(
                {
                    "rank": i,
                    "score": 0.0,
                    "title": title[:200],
                    "section": h["kind"],
                    "source": f"{h['author'] or 'unknown'} - {h['license']}",
                    "path": h["source_url"],
                    "text": text[:MAX_SNIPPET],
                }
            )
        return out
