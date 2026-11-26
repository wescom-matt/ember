"""Target roles and the active host for each role.

Every target carries a comma-separated list of roles. Roles are user-defined
words; four have meaning to Ember:
  radio    - has the programming cable(s); runs chirpc
  build    - compiles/flashes boards and slices 3D models
  printer  - a LAN 3D printer (kind 'printer')
  general  - anything else

The active host for a role is picked in this order: the chat's own choice,
then the admin's global choice, then the first enabled target with that role
(ranked by the default candidate names below).
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from ember.db import get_setting, set_setting

ROLE_RE = re.compile(r"^[a-z][a-z0-9-]{0,19}$")
MAX_ROLES = 8
KNOWN_ROLES = ("radio", "build", "printer", "general")
ACTIVE_ROLES = ("radio", "build", "printer")
# Matt's defaults: which machines usually have the radio cables / the toolchains.
DEFAULT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "radio": ("mint", "zorin", "los gatos"),
    "build": ("los gatos", "mint"),
    "printer": ("centauri", "cc2", "printer"),
}
# Quick-fill presets for the Add target form. Hosts/users are filled in by the admin.
PRESETS: list[dict[str, Any]] = [
    {"name": "Mint", "kind": "ssh", "os": "linux", "roles": "radio,build"},
    {"name": "Zorin", "kind": "ssh", "os": "linux", "roles": "radio", "username": "mwescom"},
    {"name": "Los Gatos", "kind": "ssh", "os": "windows", "roles": "radio,build"},
    {"name": "Centauri Carbon 2", "kind": "printer", "os": "linux", "roles": "printer", "port": 1883},
]
COLUMN = {"radio": "radio_target_id", "build": "build_target_id", "printer": "printer_target_id"}


def parse_roles(raw: str) -> list[str]:
    """Normalize 'Radio, build' -> ['radio', 'build']; reject anything odd."""
    out: list[str] = []
    for part in (raw or "").split(",")[: MAX_ROLES * 2]:
        word = part.strip().lower().replace(" ", "-")
        if not word:
            continue
        if not ROLE_RE.fullmatch(word):
            raise ValueError("roles: words of a-z, 0-9 and - (max 20 chars)")
        if word not in out:
            out.append(word)
    if len(out) > MAX_ROLES:
        raise ValueError(f"at most {MAX_ROLES} roles")
    return out or ["general"]


def roles_text(roles: list[str]) -> str:
    return ",".join(roles)


def _setting_key(role: str) -> str:
    if role not in ACTIVE_ROLES:
        raise ValueError("unknown role")
    return f"active_{role}_host"


def global_active(conn: sqlite3.Connection, role: str) -> int:
    value = get_setting(conn, _setting_key(role), "0")
    return int(value) if value.isdigit() else 0


def set_global_active(conn: sqlite3.Connection, role: str, target_id: int) -> None:
    if target_id and not _has_role(conn, target_id, role):
        raise ValueError(f"that target does not have the '{role}' role")
    set_setting(conn, _setting_key(role), str(int(target_id)))


def _has_role(conn: sqlite3.Connection, target_id: int, role: str) -> bool:
    row = conn.execute("SELECT roles FROM targets WHERE id = ? AND enabled = 1", (target_id,)).fetchone()
    return bool(row and role in str(row["roles"]).split(","))


def candidates(conn: sqlite3.Connection, role: str) -> list[dict[str, Any]]:
    """Enabled targets with the role, default candidates first."""
    rows = conn.execute(
        "SELECT id, name, kind, os, roles FROM targets WHERE enabled = 1 ORDER BY name LIMIT 100"
    ).fetchall()
    found = [dict(r) for r in rows if role in str(r["roles"]).split(",")]
    order = DEFAULT_CANDIDATES.get(role, ())

    def rank(item: dict[str, Any]) -> int:
        name = str(item["name"]).lower()
        for i, cand in enumerate(order):
            if cand in name:
                return i
        return len(order)

    return sorted(found, key=rank)


def active_host(conn: sqlite3.Connection, role: str, conv_choice: int | None) -> int:
    """Return the target id to use for a role, or 0 if none is set up."""
    for pick in (int(conv_choice or 0), global_active(conn, role)):
        if pick and _has_role(conn, pick, role):
            return pick
    found = candidates(conn, role)
    return int(found[0]["id"]) if found else 0


def chat_hosts(conn: sqlite3.Connection, conv_id: int) -> dict[str, int]:
    row = conn.execute(
        "SELECT radio_target_id, build_target_id, printer_target_id FROM conversations WHERE id = ?", (conv_id,)
    ).fetchone()
    return {role: active_host(conn, role, row[COLUMN[role]] if row else None) for role in ACTIVE_ROLES}


def set_chat_host(conn: sqlite3.Connection, conv_id: int, role: str, target_id: int) -> None:
    if role not in COLUMN:
        raise ValueError("unknown role")
    if target_id and not _has_role(conn, target_id, role):
        raise ValueError(f"that target does not have the '{role}' role")
    column = COLUMN[role]  # fixed allowlist, never user text
    conn.execute(f"UPDATE conversations SET {column} = ? WHERE id = ?", (target_id or None, conv_id))  # noqa: S608 # nosec B608
