"""Phase 2: command execution settings, permissions, and the tool the model may call.

- Master switch (admin only, default OFF) in the settings table.
- A user may run commands if they are an admin or an admin gave them 'can run commands'.
- Each chat also has its own Commands toggle and selected target.
- The model gets run_command and write_file (on the chat's target, the radio
  host, or the build host) and, if a printer is set up, printer. It never sees
  credentials or target secrets.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ember.db import get_setting, set_setting

EXEC_KEY = "exec_enabled"

ON_HOST = {"type": "string", "enum": ["chat", "radio", "build"],
           "description": "Which computer: chat (this chat's target), radio (radio host), build (build host)"}

RUN_COMMAND_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": "Run one shell command (bash on Linux, PowerShell on Windows). Risky ones wait for the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The exact command line"},
                "reason": {"type": "string", "description": "Why, in one short sentence"},
                "on": ON_HOST,
            },
            "required": ["command"],
        },
    },
}

WRITE_FILE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Create or replace a text file (config, sketch, script). The user sees a diff and confirms.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path, e.g. ~/proj/src/main.cpp"},
                "content": {"type": "string", "description": "The complete new file content"},
                "reason": {"type": "string"},
                "on": ON_HOST,
            },
            "required": ["path", "content"],
        },
    },
}

EDIT_FILE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "edit_file",
        "description": "Change part of an existing file with SEARCH/REPLACE blocks or a small unified diff. "
        "Preferred over write_file. The user sees the diff and confirms.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "patch": {
                    "type": "string",
                    "description": "<<<<<<< SEARCH\nexact old lines\n=======\nnew lines\n>>>>>>> REPLACE",
                },
                "reason": {"type": "string"},
                "on": ON_HOST,
            },
            "required": ["path", "patch"],
        },
    },
}

UPDATE_NOTES_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_notes",
        "description": "Replace this project's notes (purpose, board, pins, commands, key decisions). Shown as a diff.",
        "parameters": {
            "type": "object",
            "properties": {"content": {"type": "string", "description": "The complete new notes, short"},
                           "reason": {"type": "string"}},
            "required": ["content"],
        },
    },
}

PRINTER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "printer",
        "description": "3D printer: status, files, pause; start/resume/cancel need the user to confirm.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "files", "pause", "start", "resume", "cancel"]},
                "file": {"type": "string", "description": "G-code file name on the printer (for start)"},
            },
            "required": ["action"],
        },
    },
}


def offered_tools(has_printer: bool, has_project: bool = False) -> list[dict[str, Any]]:
    """Few, small schemas: the default model has a 4k-token context."""
    out = [RUN_COMMAND_TOOL, EDIT_FILE_TOOL, WRITE_FILE_TOOL]
    if has_project:
        out.append(UPDATE_NOTES_TOOL)
    if has_printer:
        out.append(PRINTER_TOOL)
    return out


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
