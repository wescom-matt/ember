"""Code index per project: split source into function/file chunks, embed them with
nomic-embed-text (the same local embedder Nomad uses) and find the few chunks that
matter for a question.

Source is the bare mirror ~/git/<repo>.git (HEAD), so it works offline and doesn't
touch the build host. Re-indexing is incremental by git blob id and starts on its
own (in the background) when the mirror's HEAD changes.
"""

from __future__ import annotations

import array
import json
import logging
import math
import re
import shutil
import sqlite3
import subprocess  # nosec B404 - fixed git argument lists, no shell
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ember import config, projects
from ember.httpjson import call_json

LOG = logging.getLogger("ember.code_index")
EMBED_MODEL = "nomic-embed-text:v1.5"
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "
EXTS = {
    ".c": "c",
    ".h": "c",
    ".cpp": "c",
    ".hpp": "c",
    ".cc": "c",
    ".ino": "c",
    ".cs": "c",
    ".js": "c",
    ".jsx": "c",
    ".ts": "c",
    ".tsx": "c",
    ".mjs": "c",
    ".dart": "c",
    ".py": "py",
}
SKIP_DIRS = (
    "node_modules/",
    ".pio/",
    "build/",
    "dist/",
    "bin/",
    "obj/",
    ".dart_tool/",
    "vendor/",
    "third_party/",
    "lib/gen/",
    "generated/",
)
SKIP_SUFFIXES = (
    ".min.js",
    ".g.dart",
    ".freezed.dart",
    ".pb.dart",
    ".pbenum.dart",
    ".pbjson.dart",
    ".pbserver.dart",
    ".pb.h",
    ".pb.c",
    ".pb.cc",
    "_pb2.py",
    ".designer.cs",
)
MAX_FILE_BYTES = 200_000
MAX_FILES = 3000
MAX_CHUNKS = 12_000
CHUNK_LINES = 60
CHUNK_CHARS = 2400
MERGE_CHARS = 900
EMBED_BATCH = 16
EMBED_CHARS = 1500
GIT_TIMEOUT = 60
EMBED_TIMEOUT = 120
DEFAULT_K = 4
_LOCKS: dict[str, threading.Lock] = {}
_STATE: dict[str, str] = {}
_GUARD = threading.Lock()
GIT = shutil.which("git") or "/usr/bin/git"


@dataclass(frozen=True)
class Chunk:
    path: str
    start: int
    end: int
    name: str
    text: str


# ---------- chunking ----------
def _strip_noise(line: str) -> str:
    return re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//.*$', "", line)


def _blocks_c(lines: list[str]) -> list[tuple[int, int]]:
    """Top-level { } blocks (functions, classes) as (start, end) line indexes; rest is filler."""
    out: list[tuple[int, int]] = []
    depth, start, in_comment = 0, -1, False
    for i, raw in enumerate(lines):
        line = _strip_noise(raw)
        if in_comment:
            if "*/" not in line:
                continue
            line, in_comment = line.split("*/", 1)[1], False
        if "/*" in line and "*/" not in line.split("/*", 1)[1]:
            line, in_comment = line.split("/*", 1)[0], True
        opens, closes = line.count("{"), line.count("}")
        if depth == 0 and opens > closes:
            start = i
            while start > 0 and lines[start - 1].strip() and not lines[start - 1].rstrip().endswith((";", "}")):
                start -= 1  # pull in the signature and comments above
        depth = max(0, depth + opens - closes)
        if depth == 0 and start >= 0 and (opens or closes):
            out.append((start, i))
            start = -1
    return out


def _blocks_py(lines: list[str]) -> list[tuple[int, int]]:
    starts = [i for i, x in enumerate(lines) if re.match(r"(async\s+)?(def|class)\s|@", x)]
    clean: list[int] = []
    for s in starts:
        if clean and s == clean[-1] + 1 and lines[clean[-1]].startswith("@"):
            continue
        clean.append(s)
    return [(s, (clean[n + 1] if n + 1 < len(clean) else len(lines)) - 1) for n, s in enumerate(clean)]


def _name(lines: list[str], start: int, end: int) -> str:
    for x in lines[start : end + 1]:
        s = x.strip()
        if s and not s.startswith(("//", "/*", "*", "#", "@")):
            return s[:100]
    return lines[start].strip()[:100]


def chunk_file(path: str, text: str) -> list[Chunk]:
    kind = EXTS.get(Path(path).suffix.lower())
    if kind is None:
        return []
    lines = text.splitlines()
    blocks = _blocks_py(lines) if kind == "py" else _blocks_c(lines)
    spans: list[tuple[int, int, bool]] = []  # (start, end, is a function/class block)
    pos = 0
    for s, e in blocks:
        if s > pos:
            spans.append((pos, s - 1, False))
        spans.append((s, e, True))
        pos = e + 1
    if pos < len(lines):
        spans.append((pos, len(lines) - 1, False))
    out: list[Chunk] = []
    prev_block = False
    for s, e, is_block in spans:
        for ws in range(s, e + 1, CHUNK_LINES):  # split long blocks into windows
            we = min(e, ws + CHUNK_LINES - 1)
            body = "\n".join(lines[ws : we + 1])[:CHUNK_CHARS]
            if not body.strip():
                continue
            prev = out[-1] if out else None
            small = prev and len(prev.text) + len(body) < MERGE_CHARS and prev.end == ws
            if prev and small and not (prev_block and is_block):  # never glue two functions together
                name = prev.name if prev_block or not is_block else _name(lines, ws, we)
                out[-1] = Chunk(path, prev.start, we + 1, name, prev.text + "\n" + body)
            else:
                out.append(Chunk(path, ws + 1, we + 1, _name(lines, ws, we), body))
            prev_block = is_block
    return out


# ---------- git ----------
def _git(bare: Path, *args: str) -> str:
    res = subprocess.run(  # noqa: S603 # nosec B603 - fixed argument list
        [GIT, "-C", str(bare), *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
        check=False,
        errors="replace",
    )
    if res.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {res.stderr.strip()[:200]}")
    return res.stdout


def mirror(repo: str) -> Path | None:
    name = repo.rsplit("/", 1)[-1]
    bare = projects.git_dir() / f"{name}.git"
    return bare if name and bare.is_dir() else None


def source_files(bare: Path) -> list[tuple[str, str]]:
    """(path, blob id) of indexable files at HEAD."""
    out = []
    for line in _git(bare, "ls-tree", "-r", "-l", "HEAD").splitlines():
        meta, _tab, path = line.partition("\t")
        parts = meta.split()
        if len(parts) < 4 or parts[1] != "blob" or not parts[3].isdigit():
            continue
        if Path(path).suffix.lower() not in EXTS or int(parts[3]) > MAX_FILE_BYTES:
            continue
        if any(d in f"/{path}" for d in ("/" + s for s in SKIP_DIRS)) or path.endswith(SKIP_SUFFIXES):
            continue
        out.append((path, parts[2]))
    return out[:MAX_FILES]


# ---------- embeddings ----------
def embed(ollama_url: str, texts: list[str]) -> list[list[float]]:
    data = call_json(
        f"{ollama_url}/api/embed", {"model": EMBED_MODEL, "input": texts, "keep_alive": "5m"}, EMBED_TIMEOUT
    )
    vecs = data.get("embeddings")
    if not isinstance(vecs, list) or len(vecs) != len(texts):
        raise RuntimeError("embedder returned no vectors")
    return [_norm([float(x) for x in v]) for v in vecs]


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


# ---------- store ----------
def db_path(data_dir: Path, project: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", project)[:60] or "project"
    return data_dir / "code-index" / f"{slug}.db"


def _open(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, blob TEXT NOT NULL);"
        "CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, path TEXT NOT NULL, start INTEGER, "
        "end_line INTEGER, name TEXT, text TEXT NOT NULL, vec BLOB NOT NULL);"
        "CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);"
    )
    return conn


def _meta(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else ""


def _find(data_dir: Path, name: str) -> dict[str, Any] | None:
    return next((p for p in projects.load(data_dir) if p["name"] == name), None)


def build(data_dir: Path, ollama_url: str, name: str) -> dict[str, Any]:
    """Bring the index up to date with the mirror's HEAD (incremental). Returns status."""
    proj = _find(data_dir, name)
    bare = mirror(proj["repo"]) if proj else None
    if bare is None:
        return {"state": "none", "detail": "no repo mirror in ~/git"}
    head = _git(bare, "rev-parse", "HEAD").strip()
    files = dict(source_files(bare))
    with _open(db_path(data_dir, name)) as conn:
        have = {r["path"]: r["blob"] for r in conn.execute("SELECT path, blob FROM files")}
        gone = [p for p in have if files.get(p) != have[p]]
        for p in gone:
            conn.execute("DELETE FROM chunks WHERE path = ?", (p,))
            conn.execute("DELETE FROM files WHERE path = ?", (p,))
        conn.commit()
        todo = [(p, b) for p, b in files.items() if have.get(p) != b]
        total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        for path, blob in todo:
            text = _git(bare, "cat-file", "-p", blob)
            chunks = chunk_file(path, text)[: max(0, MAX_CHUNKS - total)]
            for i in range(0, len(chunks), EMBED_BATCH):
                batch = chunks[i : i + EMBED_BATCH]
                vecs = embed(ollama_url, [f"{DOC_PREFIX}{c.path}: {c.name}\n{c.text[:EMBED_CHARS]}" for c in batch])
                conn.executemany(
                    "INSERT INTO chunks(path, start, end_line, name, text, vec) VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (c.path, c.start, c.end, c.name, c.text, array.array("f", v).tobytes())
                        for c, v in zip(batch, vecs, strict=True)
                    ],
                )
            total += len(chunks)
            conn.execute("INSERT OR REPLACE INTO files(path, blob) VALUES (?, ?)", (path, blob))
            conn.commit()
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('head', ?)", (head,))
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    return {"state": "ready", "chunks": int(count), "files": len(files), "head": head[:10], "updated": len(todo)}


def status(data_dir: Path, name: str) -> dict[str, Any]:
    path = db_path(data_dir, name)
    if _STATE.get(name) == "indexing":
        return {"state": "indexing"}
    if not path.is_file():
        return {"state": "none"}
    with _open(path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {"state": "ready", "chunks": int(count), "head": _meta(conn, "head")[:10]}


def _stale(data_dir: Path, name: str) -> bool:
    proj = _find(data_dir, name)
    bare = mirror(proj["repo"]) if proj else None
    if bare is None:
        return False
    try:
        head = _git(bare, "rev-parse", "HEAD").strip()
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return False
    path = db_path(data_dir, name)
    if not path.is_file():
        return True
    with _open(path) as conn:
        return _meta(conn, "head") != head


def refresh_async(data_dir: Path, ollama_url: str, name: str, force: bool = False) -> bool:
    """Start a background re-index if the mirror changed. Returns True if one started."""
    with _GUARD:
        lock = _LOCKS.setdefault(name, threading.Lock())
    if lock.locked() or not (force or _stale(data_dir, name)):
        return False

    def work() -> None:
        with lock:
            _STATE[name] = "indexing"
            try:
                LOG.info("code index %s: %s", name, json.dumps(build(data_dir, ollama_url, name)))
            except (RuntimeError, OSError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
                LOG.warning("code index %s failed: %s", name, exc)
            finally:
                _STATE.pop(name, None)

    threading.Thread(target=work, name=f"index-{name}", daemon=True).start()
    return True


def _boost(query: str, text: str) -> float:
    words = {w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", query) if not w.islower() or "_" in w}
    words |= {w for w in re.findall(r"`([^`]{3,40})`", query)}
    return min(0.15, 0.05 * sum(1 for w in words if w in text))


def search(
    data_dir: Path, ollama_url: str, name: str, query: str, max_chars: int, k: int = DEFAULT_K
) -> list[dict[str, Any]]:
    """Top chunks for the query that fit max_chars. Empty if there is no index yet."""
    path = db_path(data_dir, name)
    if not path.is_file() or max_chars <= 0:
        return []
    qv = array.array("f", embed(ollama_url, [QUERY_PREFIX + query[: config.MAX_SEARCH_CHARS * 5]])[0])
    scored: list[tuple[float, sqlite3.Row]] = []
    with _open(path) as conn:
        for row in conn.execute("SELECT path, start, end_line, name, text, vec FROM chunks LIMIT ?", (MAX_CHUNKS,)):
            v = array.array("f")
            v.frombytes(row["vec"])
            if len(v) != len(qv):
                continue
            score = sum(a * b for a, b in zip(qv, v, strict=True)) + _boost(query, row["text"])
            scored.append((score, row))
    scored.sort(key=lambda s: s[0], reverse=True)
    out: list[dict[str, Any]] = []
    used = 0
    for score, row in scored[: k * 3]:
        size = len(row["text"]) + 60
        if used + size > max_chars:
            continue
        out.append(
            {
                "path": row["path"],
                "start": row["start"],
                "end": row["end_line"],
                "name": row["name"],
                "score": round(score, 3),
                "text": row["text"],
            }
        )
        used += size
        if len(out) >= k:
            break
    return out


def format_chunks(chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return ""
    body = "\n".join(f"--- {c['path']} lines {c['start']}-{c['end']}\n{c['text']}" for c in chunks)
    return "Relevant code from the project (repo mirror on the P1; may lag the build host):\n" + body


def file_text(data_dir: Path, name: str, path: str) -> str | None:
    """A file from the mirror by path or path suffix (for build-error source lines)."""
    proj = _find(data_dir, name)
    bare = mirror(proj["repo"]) if proj else None
    if bare is None:
        return None
    want = path.replace("\\", "/").lstrip("./")
    try:
        names = [p for p, _b in source_files(bare)]
        match = next((p for p in names if p == want or want.endswith("/" + p) or p.endswith("/" + want)), None)
        return _git(bare, "show", f"HEAD:{match}") if match else None
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return None
