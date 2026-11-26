"""Projects: each of Matt's repos with its build host, folder, board and commands.

Stored in data_dir/projects.json (seeded from coldboot/projects-seed.json the first
time). The agent gets a short summary so it can propose the right command; the
command still goes through run_command and the normal approval flow. Mirror status
comes from the bare repos in ~/git (see scripts/import-mirrors.sh).
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404 - fixed git argument lists, no shell
from pathlib import Path
from typing import Any

SEED = Path(__file__).resolve().parent.parent / "coldboot" / "projects-seed.json"
MAX_PROJECTS = 40
MAX_COMMANDS = 12
MAX_CMD_CHARS = 500
MAX_FIELD_CHARS = 300
TEXT_FIELDS = (
    "name",
    "repo",
    "language",
    "purpose",
    "host",
    "folder",
    "backup_host",
    "backup_folder",
    "board",
    "env",
    "serial_port",
    "notes",
)
GIT_TIMEOUT_SEC = 10
MAX_PROMPT_CHARS = 3000


class ProjectsError(ValueError):
    pass


def path(data_dir: Path) -> Path:
    return data_dir / "projects.json"


def git_dir() -> Path:
    return Path.home() / "git"


def validate(raw: Any) -> list[dict[str, Any]]:
    """Check and normalize a project list; raise ProjectsError on anything odd."""
    items = raw.get("projects") if isinstance(raw, dict) else raw
    if not isinstance(items, list) or len(items) > MAX_PROJECTS:
        raise ProjectsError(f"expected a list of at most {MAX_PROJECTS} projects")
    out: list[dict[str, Any]] = []
    names: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ProjectsError("each project must be an object")
        proj: dict[str, Any] = {}
        for key in TEXT_FIELDS:
            value = item.get(key, "")
            if not isinstance(value, str) or len(value) > MAX_FIELD_CHARS:
                raise ProjectsError(f"{key}: text up to {MAX_FIELD_CHARS} characters")
            proj[key] = value.strip()
        if not proj["name"] or proj["name"].lower() in names:
            raise ProjectsError("every project needs a unique name")
        names.add(proj["name"].lower())
        cmds = item.get("commands", [])
        if not isinstance(cmds, list) or len(cmds) > MAX_COMMANDS:
            raise ProjectsError(f"{proj['name']}: at most {MAX_COMMANDS} commands")
        proj["commands"] = []
        for c in cmds:
            if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not isinstance(c.get("cmd"), str):
                raise ProjectsError(f"{proj['name']}: each command needs name and cmd")
            if len(c["cmd"]) > MAX_CMD_CHARS or len(c["name"]) > 60:
                raise ProjectsError(f"{proj['name']}: command too long")
            proj["commands"].append({"name": c["name"].strip(), "cmd": c["cmd"].strip()})
        offline = item.get("offline", {})
        proj["offline"] = offline if isinstance(offline, dict) else {}
        out.append(proj)
    return out


def load(data_dir: Path) -> list[dict[str, Any]]:
    file = path(data_dir)
    source = file if file.is_file() else SEED
    try:
        return validate(json.loads(source.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ProjectsError):
        return validate(json.loads(SEED.read_text(encoding="utf-8")))


def save(data_dir: Path, items: Any) -> list[dict[str, Any]]:
    clean = validate(items)
    file = path(data_dir)
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "projects": clean}, indent=2), encoding="utf-8")
    tmp.replace(file)
    return clean


def mirror_status(repo: str) -> dict[str, str]:
    """Last commit of the bare mirror ~/git/<name>.git, or empty if there is none."""
    name = repo.rsplit("/", 1)[-1]
    bare = git_dir() / f"{name}.git"
    git = shutil.which("git")
    if not name or not bare.is_dir() or git is None:
        return {"mirror": "", "last": ""}
    try:
        res = subprocess.run(  # noqa: S603 # nosec B603 - fixed argument list
            [git, "-C", str(bare), "log", "-1", "--all", "--format=%h %cs %s"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"mirror": str(bare), "last": "unreadable"}
    return {"mirror": str(bare), "last": res.stdout.strip()[:120]}


def with_status(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**p, **mirror_status(p["repo"])} for p in items]


def prompt_text(data_dir: Path, only: str = "") -> str:
    """Short project list for the agent: host, folder, board and commands (one project if `only`)."""
    lines = []
    for p in load(data_dir):
        if not p["commands"] or (only and p["name"] != only):
            continue
        where = f"{p['host']}:{p['folder']}" if p["host"] else "no host"
        if p["backup_host"]:
            where += f" (backup {p['backup_host']}:{p['backup_folder']})"
        cmds = "; ".join(f"{c['name']}=`{c['cmd']}`" for c in p["commands"][:6])
        board = f" board {p['board']} env {p['env']} port {p['serial_port']}." if p["board"] else ""
        lines.append(f"- {p['name']} at {where}.{board} {cmds}")
    if not lines:
        return ""
    text = (
        "\nProjects (cd to the folder first; use these exact commands; flashing still asks the user; "
        "offline mirrors are on the P1 at ~/git/NAME.git):\n" + "\n".join(lines)
    )
    return text[:MAX_PROMPT_CHARS]
