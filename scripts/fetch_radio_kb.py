#!/usr/bin/env python3
"""Download the radio reference sources and build Ember's offline radio knowledge base.

Run while online (on the P1, from ~/ember):
    .venv/bin/python scripts/fetch_radio_kb.py               # fetch everything + build
    .venv/bin/python scripts/fetch_radio_kb.py --only amsat  # refresh the AMSAT pack (TLEs, SatNOGS) + build
    .venv/bin/python scripts/fetch_radio_kb.py --rebuild     # rebuild the index from saved files (offline)

Saved files: <data_dir>/radio-kb/raw/<id>.<ext>; TLE copies for Gpredict: radio-kb/tle/;
list of sources with licences: radio-kb/SOURCES.json; index: radio-kb/index.db.
Nothing here is invented: every passage is text from the listed source or Ember's own guides in docs/amsat/.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ember.config import load_settings  # noqa: E402
from ember.radio_kb import AMSAT_SOURCES, RADIO_SOURCES, SCHEMA, chunks, html_sections, index_path  # noqa: E402

UA = "Mozilla/5.0 (X11; Linux x86_64) Ember-offline-radio-kb/0.6 (personal offline reference)"
MAX_BYTES = 15_000_000
EXT = {"html": ".html", "tle": ".txt", "satnogs": ".json", "roff": ".txt", "text": ".txt", "local": ".md"}
MAX_TRANSMITTERS = 4000


def all_sources() -> list[dict[str, str]]:
    core = [{"id": i, "title": t, "url": u, "kind": "html", "pack": "core"} for i, t, u in RADIO_SOURCES]
    return core + [{**s, "pack": "amsat"} for s in AMSAT_SOURCES]


def fetch(url: str) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("https only")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310 # nosec B310 - fixed https source list
        return bytes(resp.read(MAX_BYTES))


def download(src: dict[str, str], raw: Path) -> int:
    path = raw / f"{src['id']}{EXT[src['kind']]}"
    if src["kind"] == "local":
        body = (REPO / src["url"]).read_bytes()
    elif src["kind"] == "satnogs":
        body = json.dumps(
            {"transmitters": json.loads(fetch(src["url"])), "satellites": json.loads(fetch(src["url2"]))}
        ).encode()
    else:
        body = fetch(src["url"])
    if src["kind"] == "tle" and b"1 " not in body[:400]:
        raise ValueError("not a TLE file")
    path.write_bytes(body)
    return len(body)


def roff_text(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = [("", "")]
    for line in text.splitlines():
        if line.startswith(('.\\"', "'\\\"", ".TH", ".de", ".if", ".ie", ".el")):
            continue
        m = re.match(r"\.S[HS]\s+\"?([^\"]+)\"?", line)
        if m:
            out.append((m.group(1).strip(), ""))
            continue
        line = re.sub(r"^\.(B|I|BR|IR|RB|BI|IB|TP|IP|PP|LP|P|RS|RE|EX|EE|nf|fi|br|sp|in|TH|ad|na|hy|ft)\b\s*", "", line)
        line = re.sub(r"\\f[BIRP]|\\\(..|\\[&e]", "", line).replace("\\-", "-").replace('"', "")
        if line.strip() and not line.startswith("."):
            h, body = out[-1]
            out[-1] = (h, body + line + "\n")
    return [(h, b) for h, b in out if b.strip()]


def md_sections(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = [("", "")]
    for line in text.splitlines():
        if line.startswith("#"):
            out.append((line.lstrip("# ").strip(), ""))
        else:
            out[-1] = (out[-1][0], out[-1][1] + line + "\n")
    return [(h, b) for h, b in out if b.strip()]


def tle_sections(text: str, title: str) -> list[tuple[str, str]]:
    lines = [x.rstrip() for x in text.splitlines() if x.strip()]
    out = []
    for i in range(len(lines) - 2):
        if lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            name = lines[i].strip()
            out.append((f"TLE {name}", f"{name} two-line elements ({title}):\n{lines[i + 1]}\n{lines[i + 2]}"))
    return out


def _mhz(hz: Any) -> str:
    return f"{hz / 1e6:.4f}" if isinstance(hz, (int, float)) and hz else ""


def satnogs_sections(data: dict[str, Any]) -> list[tuple[str, str]]:
    sats = {s.get("sat_id"): s for s in data.get("satellites", []) if isinstance(s, dict)}
    by_sat: dict[str, list[str]] = {}
    for t in data.get("transmitters", [])[: MAX_TRANSMITTERS * 3]:
        if not isinstance(t, dict) or not t.get("alive") or t.get("service") != "Amateur":
            continue
        sat = sats.get(t.get("sat_id")) or {}
        if t.get("status") != "active" or sat.get("status") != "in orbit":
            continue
        down = "-".join(x for x in (_mhz(t.get("downlink_low")), _mhz(t.get("downlink_high"))) if x)
        up = "-".join(x for x in (_mhz(t.get("uplink_low")), _mhz(t.get("uplink_high"))) if x)
        bits = [
            str(t.get("description") or "")[:80],
            f"downlink {down} MHz" if down else "",
            f"uplink {up} MHz" if up else "",
            f"mode {t.get('mode')}" if t.get("mode") else "",
            f"{t.get('baud')} baud" if t.get("baud") else "",
            "inverting" if t.get("invert") else "",
            f"status {t.get('status')}" if t.get("status") else "",
        ]
        by_sat.setdefault(str(t.get("sat_id")), []).append("; ".join(b for b in bits if b))
    out = []
    for sid, lines in by_sat.items():
        sat = sats.get(sid) or {}
        names = ", ".join(x for x in (sat.get("name"), sat.get("names")) if x)
        heard = sat.get("reception_status") or "unknown"
        head = f"{names or sid} (NORAD {sat.get('norad_cat_id') or '?'}) - in orbit, reception {heard}"
        out.append((head, f"Satellite {head}. Transmitters:\n" + "\n".join(f"- {x}" for x in lines[:12])))
    return out


def sections_for(src: dict[str, str], path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    kind = src["kind"]
    if kind == "tle":
        return tle_sections(text, src["title"])
    if kind == "satnogs":
        return satnogs_sections(json.loads(text))
    if kind == "roff":
        return roff_text(text)
    if kind in ("local", "text"):
        return md_sections(text)
    return html_sections(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rebuild", action="store_true", help="only rebuild the index from saved files")
    ap.add_argument("--only", choices=["core", "amsat"], help="fetch only one pack (the index always has both)")
    args = ap.parse_args()
    data_dir = load_settings().data_dir
    kb = data_dir / "radio-kb"
    raw = kb / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    sources = all_sources()
    for src in sources:
        if args.rebuild or (args.only and src["pack"] != args.only):
            continue
        try:
            size = download(src, raw)
        except (OSError, ValueError) as exc:
            print(f"  ! {src['id']}: {exc} (keeping any older copy)")
            continue
        (raw / f"{src['id']}.date").write_text(today)
        print(f"  ok {src['id']}: {size:,} bytes")
        time.sleep(1)
    tle_dir = kb / "tle"
    tle_dir.mkdir(exist_ok=True)
    tmp = index_path(data_dir).with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)
    total, listing = 0, []
    for src in sources:
        path = raw / f"{src['id']}{EXT[src['kind']]}"
        if not path.is_file():
            continue
        data = path.read_bytes()
        date_file = raw / f"{src['id']}.date"
        retrieved = date_file.read_text().strip() if date_file.is_file() else today
        digest = hashlib.sha256(data).hexdigest()
        url = src["url"] if src["kind"] != "local" else f"ember repo: {src['url']}"
        conn.execute("INSERT INTO sources VALUES (?, ?, ?, ?, ?)", (src["id"], src["title"], url, retrieved, digest))
        parts = chunks(sections_for(src, path))
        conn.executemany(
            "INSERT INTO passages(source_id, heading, body) VALUES (?, ?, ?)", [(src["id"], h, b) for h, b in parts]
        )
        if src["kind"] == "tle":
            shutil.copy2(path, tle_dir / f"{src['id']}.txt")
        total += len(parts)
        listing.append(
            {
                "id": src["id"],
                "pack": src["pack"],
                "title": src["title"],
                "url": url,
                "retrieved": retrieved,
                "sha256": digest,
                "bytes": len(data),
                "passages": len(parts),
            }
        )
    conn.commit()
    conn.close()
    tmp.replace(index_path(data_dir))
    (kb / "SOURCES.json").write_text(json.dumps(listing, indent=1))
    print(f"Radio KB: {len(listing)} sources, {total} passages -> {index_path(data_dir)}")
    return 0 if listing else 1


if __name__ == "__main__":
    raise SystemExit(main())
