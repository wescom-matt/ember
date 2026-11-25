"""Phase 2: command execution settings, permissions, and the tool the model may call.

- Master switch (admin only, default OFF) in the settings table.
- A user may run commands if they are an admin or an admin gave them 'can run commands'.
- Each chat also has its own Commands toggle and selected target.
- The model gets exactly one tool, run_command, which runs on the chat's selected
  target. It never sees credentials or target secrets.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ember.db import get_setting, set_setting

EXEC_KEY = "exec_enabled"

RUN_COMMAND_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": (
            "Run one shell command on the selected target computer and return its output and exit code. "
            "Linux targets use bash; Windows targets use PowerShell. Risky commands wait for the user to confirm."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The exact command line to run"},
                "reason": {"type": "string", "description": "One short sentence: why this command"},
            },
            "required": ["command"],
        },
    },
}


def master_on(conn: sqlite3.Connection) -> bool:
    return get_setting(conn, EXEC_KEY, "0") == "1"


def set_master(conn: sqlite3.Connection, on: bool) -> None:
    set_setting(conn, EXEC_KEY, "1" if on else "0")


def user_can_exec(conn: sqlite3.Connection, user_id: int) -> bool:
    row = conn.execute("SELECT is_admin, can_exec, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["is_active"] and (row["is_admin"] or row["can_exec"]))


def capabilities(conn: sqlite3.Connection, user_id: int) -> dict[str, bool]:
    on = master_on(conn)
    can = user_can_exec(conn, user_id)
    return {"exec": on and can, "master": on, "can_exec": can}


def exec_allowed(conn: sqlite3.Connection, user_id: int) -> bool:
    """Checked again right before every run, not only when the turn starts."""
    return master_on(conn) and user_can_exec(conn, user_id)
