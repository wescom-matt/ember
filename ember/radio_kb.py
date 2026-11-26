"""Offline radio knowledge base: public band plans and FCC rules, searchable with SQLite FTS5.

Built by scripts/fetch_radio_kb.py while online (sources listed in RADIO_SOURCES);
searched offline from data_dir/radio-kb/index.db. Every passage keeps its source URL
and retrieval date so answers can cite where a frequency came from.
"""

from __future__ import annotations

import re
import sqlite3
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

MAX_SNIPPET = 900
CHUNK_CHARS = 1400

# (id, title, url). Official sources first; Wikipedia only for general background (antennas, modes).
ECFR = "https://www.ecfr.gov/api/renderer/v1/content/enhanced/current/title-47"
RADIO_SOURCES: list[tuple[str, str, str]] = [
    ("arrl-band-plan", "ARRL Band Plan (US amateur bands, 2200 m to mm-wave)", "https://www.arrl.org/band-plan"),
    ("fcc-part97", "47 CFR Part 97 - Amateur Radio Service (eCFR)", f"{ECFR}?part=97"),
    ("fcc-part95", "47 CFR Part 95 - Personal Radio Services: GMRS, FRS, MURS, CB (eCFR)", f"{ECFR}?part=95"),
    ("fcc-80-371", "47 CFR 80.371 - Marine distress, urgency, safety frequencies (eCFR)", f"{ECFR}?section=80.371"),
    ("fcc-80-373", "47 CFR 80.373 - Marine private communications frequencies (eCFR)", f"{ECFR}?section=80.373"),
    (
        "uscg-vhf",
        "USCG NAVCEN - US VHF marine channel information",
        "https://www.navcen.uscg.gov/us-vhf-channel-information",
    ),
    ("fcc-87-173", "47 CFR 87.173 - Aviation frequencies (eCFR)", f"{ECFR}?section=87.173"),
    ("fcc-90-20", "47 CFR 90.20 - Public Safety Pool frequencies (eCFR)", f"{ECFR}?section=90.20"),
    ("nws-nwr", "NWS - NOAA Weather Radio All Hazards", "https://www.weather.gov/nwr/"),
    (
        "swpc-hf",
        "NOAA SWPC - HF radio communications and space weather",
        "https://www.swpc.noaa.gov/impacts/hf-radio-communications",
    ),
    ("swpc-scales", "NOAA SWPC - Space weather scales (R/S/G)", "https://www.swpc.noaa.gov/noaa-scales-explanation"),
    (
        "wiki-ctcss",
        "Wikipedia - CTCSS (sub-audible tones)",
        "https://en.wikipedia.org/wiki/Continuous_Tone-Coded_Squelch_System",
    ),
    ("wiki-repeater", "Wikipedia - Repeater (offsets, tones)", "https://en.wikipedia.org/wiki/Repeater"),
    ("wiki-dipole", "Wikipedia - Dipole antenna", "https://en.wikipedia.org/wiki/Dipole_antenna"),
    ("wiki-jpole", "Wikipedia - J-pole antenna", "https://en.wikipedia.org/wiki/J-pole_antenna"),
    ("wiki-yagi", "Wikipedia - Yagi-Uda antenna", "https://en.wikipedia.org/wiki/Yagi%E2%80%93Uda_antenna"),
    ("wiki-swr", "Wikipedia - Standing wave ratio", "https://en.wikipedia.org/wiki/Standing_wave_ratio"),
    ("wiki-propagation", "Wikipedia - Radio propagation", "https://en.wikipedia.org/wiki/Radio_propagation"),
    ("wiki-skywave", "Wikipedia - Skywave (HF propagation)", "https://en.wikipedia.org/wiki/Skywave"),
    ("wiki-ssb", "Wikipedia - Single-sideband modulation", "https://en.wikipedia.org/wiki/Single-sideband_modulation"),
    ("wiki-ft8", "Wikipedia - FT8", "https://en.wikipedia.org/wiki/FT8"),
    ("wiki-dmr", "Wikipedia - Digital Mobile Radio", "https://en.wikipedia.org/wiki/Digital_mobile_radio"),
    ("wiki-aprs", "Wikipedia - APRS", "https://en.wikipedia.org/wiki/Automatic_Packet_Reporting_System"),
]

SKIP_TAGS = frozenset({"script", "style", "nav", "header", "footer", "noscript", "svg", "form", "button"})
BLOCK_TAGS = frozenset({"p", "div", "li", "tr", "br", "section", "article", "dd", "dt", "pre", "table"})
HEADINGS = frozenset({"h1", "h2", "h3", "h4"})


class _TextParser(HTMLParser):
    """HTML -> list of (heading, text) sections. Tables become 'a | b | c' lines."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[tuple[str, list[str]]] = [("", [])]
        self._skip = 0
        self._in_heading = False
        self._heading: list[str] = []
        self._line: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag in HEADINGS:
            self._flush()
            self._in_heading, self._heading = True, []
        elif tag in ("td", "th") and self._line:
            self._line.append(" | ")
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in HEADINGS and self._in_heading:
            self._in_heading = False
            self.sections.append((" ".join("".join(self._heading).split())[:200], []))
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        (self._heading if self._in_heading else self._line).append(data)

    def _flush(self) -> None:
        line = " ".join("".join(self._line).split())
        self._line = []
        if line:
            self.sections[-1][1].append(line)


def html_sections(html: str) -> list[tuple[str, str]]:
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    parser._flush()
    return [(h, "\n".join(lines)) for h, lines in parser.sections if lines]


def chunks(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Split long sections at line breaks into ~CHUNK_CHARS passages."""
    out: list[tuple[str, str]] = []
    for heading, text in sections:
        buf: list[str] = []
        size = 0
        for line in text.splitlines():
            if size + len(line) > CHUNK_CHARS and buf:
                out.append((heading, "\n".join(buf)))
                buf, size = [], 0
            buf.append(line[:CHUNK_CHARS])
            size += len(line) + 1
        if buf and size > 40:
            out.append((heading, "\n".join(buf)))
    return out


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, title TEXT, url TEXT, retrieved TEXT, sha256 TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(source_id UNINDEXED, heading, body, tokenize='porter');
"""


def index_path(data_dir: Path) -> Path:
    return data_dir / "radio-kb" / "index.db"


class RadioKB:
    id = "radio"
    label = "Radio reference (offline)"
    description = "US band plans, FCC Part 95/97, marine, aviation, NOAA weather, antennas"

    def __init__(self, data_dir: Path) -> None:
        self.path = index_path(data_dir)

    def available(self) -> bool:
        return self.path.is_file()

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        if not self.available():
            raise RuntimeError("radio knowledge base is not built yet (run scripts/fetch_radio_kb.py while online)")
        words = re.findall(r"[A-Za-z0-9.]+", query.lower())[:12]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5)
        try:
            rows = conn.execute(
                "SELECT p.heading, p.body, s.title, s.url, s.retrieved, bm25(passages) AS score "
                "FROM passages p JOIN sources s ON s.id = p.source_id WHERE passages MATCH ? "
                "ORDER BY score LIMIT ?",
                (match, max(1, min(top_k, 8))),
            ).fetchall()
        finally:
            conn.close()
        out = []
        for heading, body, title, url, retrieved, score in rows:
            text = body if len(body) <= MAX_SNIPPET else body[:MAX_SNIPPET].rstrip() + "..."
            out.append(
                {
                    "rank": 0,
                    "score": round(-float(score), 3),
                    "title": heading or title,
                    "section": heading,
                    "source": f"{title} (retrieved {retrieved})",
                    "path": url,
                    "text": text,
                }
            )
        for i, item in enumerate(out, 1):
            item["rank"] = i
        return out
