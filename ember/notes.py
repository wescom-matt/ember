"""Project notes: a short summary per project (purpose, board, pins, commands, key
decisions) that goes first into every turn about that project.

Auto-drafted from the Projects entry and the repo mirror (README, platformio.ini,
pin #defines) with no model call; editable in Workshop -> Projects; the agent can
propose changes with update_notes, which shows a diff and asks first.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from ember import code_index, projects

MAX_NOTES_CHARS = 2000
MAX_PINS = 14
PIN_RE = re.compile(
    r"^\s*(?:#define\s+(\w*(?:PIN|GPIO|SDA|SCL|NSS|_CS|RST|BUSY|DIO\d|LED|VEXT|MOSI|MISO|SCK)\w*)\s+(\d{1,2})\b"
    r"|(?:static\s+)?(?:constexpr|const)\s+\w+\s+(\w*(?:PIN|GPIO|NSS|RST|BUSY|DIO\d|LED|VEXT)\w*)\s*=\s*(\d{1,2})\s*;)",
    re.IGNORECASE,
)


def path(data_dir: Path, name: str) -> Path:
    return data_dir / "notes" / (code_index.db_path(data_dir, name).stem + ".md")


def _mirror_file(bare: Path, rel: str) -> str:
    try:
        return code_index._git(bare, "show", f"HEAD:{rel}")  # noqa: SLF001 - same package helper
    except (RuntimeError, OSError):
        return ""


def _readme_summary(text: str) -> str:
    for block in re.split(r"\n\s*\n", text):
        clean = " ".join(x.strip() for x in block.splitlines() if not x.lstrip().startswith(("#", "!", "[", "<", "|")))
        if len(clean) > 40:
            return clean[:300]
    return ""


def _pins(bare: Path) -> list[str]:
    found: dict[str, str] = {}
    try:
        files = [p for p, _b in code_index.source_files(bare) if p.endswith((".h", ".hpp", ".ino", ".cpp"))][:80]
    except (RuntimeError, OSError):
        return []
    for rel in files:
        for line in _mirror_file(bare, rel).splitlines():
            m = PIN_RE.match(line)
            if m:
                name, num = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
                if not re.search(r"_(H|W|WIDTH|HEIGHT)$", name, re.IGNORECASE):
                    found.setdefault(name, num)
            if len(found) >= MAX_PINS:
                return [f"{k}={v}" for k, v in found.items()]
    return [f"{k}={v}" for k, v in found.items()]


def _envs(ini: str) -> list[str]:
    out, env = [], ""
    for line in ini.splitlines():
        m = re.match(r"\[env:([^\]]+)\]", line.strip())
        if m:
            env = m.group(1)
            out.append(env)
        elif env and line.strip().startswith("board ="):
            out[-1] = f"{env} (board {line.split('=', 1)[1].strip()})"
    return out[:6]


def draft(data_dir: Path, name: str) -> str:
    proj = next((p for p in projects.load(data_dir) if p["name"] == name), None)
    if proj is None:
        return ""
    bare = code_index.mirror(proj["repo"]) if proj["repo"] else None
    lines = [f"# {name}", f"Purpose: {proj['purpose'] or '(add)'}"]
    if bare is not None:
        summary = _readme_summary(_mirror_file(bare, "README.md"))
        if summary:
            lines.append(f"From README: {summary}")
    where = f"{proj['host']}:{proj['folder']}" if proj["host"] else "(no build host)"
    lines.append(
        f"Build host: {where}"
        + (f"; backup {proj['backup_host']}:{proj['backup_folder']}" if proj["backup_host"] else "")
    )
    if proj["board"]:
        lines.append(f"Board: {proj['board']}; env {proj['env']}; port {proj['serial_port'] or '?'}")
    if bare is not None:
        envs = _envs(_mirror_file(bare, "platformio.ini"))
        if envs:
            lines.append("PlatformIO envs: " + ", ".join(envs))
        pins = _pins(bare)
        if pins:
            lines.append("Pins (from source): " + ", ".join(pins))
    for c in proj["commands"][:6]:
        lines.append(f"- {c['name']}: `{c['cmd']}`")
    if proj["notes"]:
        lines.append(f"Notes: {proj['notes']}")
    lines.append("Key decisions: (add)")
    return "\n".join(lines)[:MAX_NOTES_CHARS]


def get(data_dir: Path, name: str) -> dict[str, Any]:
    file = path(data_dir, name)
    if file.is_file():
        return {"text": file.read_text(encoding="utf-8").strip()[:MAX_NOTES_CHARS], "saved": True}
    return {"text": draft(data_dir, name), "saved": False}


def save(data_dir: Path, name: str, text: str) -> str:
    """Save notes (keeps the previous version as .bak). Returns the saved text."""
    if not any(p["name"] == name for p in projects.load(data_dir)):
        raise ValueError("unknown project")
    clean = text.replace("\r\n", "\n").strip()
    if not clean or len(clean) > MAX_NOTES_CHARS:
        raise ValueError(f"notes must be 1-{MAX_NOTES_CHARS} characters")
    file = path(data_dir, name)
    file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if file.is_file():
        file.with_suffix(f".bak-{time.strftime('%Y%m%d-%H%M%S')}").write_text(
            file.read_text(encoding="utf-8"), encoding="utf-8"
        )
        baks = sorted(file.parent.glob(file.stem + ".bak-*"))
        for old in baks[:-5]:
            old.unlink(missing_ok=True)
    tmp = file.with_suffix(".tmp")
    tmp.write_text(clean + "\n", encoding="utf-8")
    tmp.replace(file)
    return clean
