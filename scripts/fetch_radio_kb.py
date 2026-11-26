#!/usr/bin/env python3
"""Download the radio reference sources and build Ember's offline radio knowledge base.

Run while online (on the P1, from ~/ember):
    .venv/bin/python scripts/fetch_radio_kb.py            # fetch + build
    .venv/bin/python scripts/fetch_radio_kb.py --rebuild  # rebuild index from the saved pages (offline)

Saved pages: <data_dir>/radio-kb/raw/<id>.html ; index: <data_dir>/radio-kb/index.db
Nothing here is invented: every passage is text from the listed public source.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ember.config import load_settings  # noqa: E402
from ember.radio_kb import RADIO_SOURCES, SCHEMA, chunks, html_sections, index_path  # noqa: E402

UA = "Mozilla/5.0 (X11; Linux x86_64) Ember-offline-radio-kb/0.4 (personal offline reference)"
MAX_BYTES = 15_000_000


def fetch(url: str) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("https only")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 # nosec B310 - fixed https source list
        return bytes(resp.read(MAX_BYTES))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rebuild", action="store_true", help="only rebuild the index from saved pages")
    args = ap.parse_args()
    data_dir = load_settings().data_dir
    raw = data_dir / "radio-kb" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    meta: dict[str, str] = {}
    for sid, _title, url in RADIO_SOURCES:
        path = raw / f"{sid}.html"
        if args.rebuild:
            continue
        try:
            body = fetch(url)
        except (OSError, ValueError) as exc:
            print(f"  ! {sid}: {exc} (keeping any older copy)")
            continue
        path.write_bytes(body)
        (raw / f"{sid}.date").write_text(today)
        print(f"  ok {sid}: {len(body):,} bytes")
        time.sleep(1)
    tmp = index_path(data_dir).with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)
    total = 0
    for sid, title, url in RADIO_SOURCES:
        path = raw / f"{sid}.html"
        if not path.is_file():
            continue
        data = path.read_bytes()
        date_file = raw / f"{sid}.date"
        meta[sid] = date_file.read_text().strip() if date_file.is_file() else today
        conn.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?)", (sid, title, url, meta[sid], hashlib.sha256(data).hexdigest())
        )
        parts = chunks(html_sections(data.decode("utf-8", "replace")))
        conn.executemany(
            "INSERT INTO passages(source_id, heading, body) VALUES (?, ?, ?)", [(sid, h, b) for h, b in parts]
        )
        total += len(parts)
    conn.commit()
    conn.close()
    tmp.replace(index_path(data_dir))
    print(f"Radio KB: {len(meta)} sources, {total} passages -> {index_path(data_dir)}")
    return 0 if meta else 1


if __name__ == "__main__":
    raise SystemExit(main())
