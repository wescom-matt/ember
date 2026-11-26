"""SQLite storage. Every query uses bound parameters (CERT / CWE-89)."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    model TEXT NOT NULL,
    kb TEXT NOT NULL DEFAULT 'none',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    thinking TEXT NOT NULL DEFAULT '',
    sources TEXT NOT NULL DEFAULT '[]',
    model TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    at INTEGER NOT NULL,
    user_id INTEGER,
    event TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""

MAX_AUDIT_ROWS = 20_000
MAX_ACTION_ROWS = 20_000

# Phase 2: command targets, credentials, actions, settings.
SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind TEXT NOT NULL CHECK (kind IN ('key', 'password')),
    public_key TEXT NOT NULL DEFAULT '',
    secret_enc TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS targets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind TEXT NOT NULL CHECK (kind IN ('local', 'ssh', 'printer')),
    host TEXT NOT NULL DEFAULT '',
    port INTEGER NOT NULL DEFAULT 22,
    username TEXT NOT NULL DEFAULT '',
    os TEXT NOT NULL DEFAULT 'linux' CHECK (os IN ('linux', 'windows')),
    credential_id INTEGER REFERENCES credentials(id) ON DELETE SET NULL,
    host_fingerprint TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    roles TEXT NOT NULL DEFAULT 'general',
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    after_message_id INTEGER NOT NULL DEFAULT 0,
    user_id INTEGER NOT NULL,
    target_id INTEGER,
    target_name TEXT NOT NULL,
    command TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    risk TEXT NOT NULL,
    risk_reasons TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('pending', 'ran', 'cancelled', 'blocked', 'expired', 'failed')),
    mode TEXT NOT NULL DEFAULT 'auto' CHECK (mode IN ('auto', 'confirmed', 'none')),
    exit_code INTEGER,
    output TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    finished_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_actions_conv ON actions(conversation_id, id);
"""

# Phase 4: radios and their stored images (files live under data_dir/radios/<id>/).
SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS radios (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    model_key TEXT NOT NULL,
    port TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS radio_images (
    id INTEGER PRIMARY KEY,
    radio_id INTEGER NOT NULL REFERENCES radios(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('backup', 'edited', 'uploaded', 'snapshot')),
    file_name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    parent_id INTEGER,
    note TEXT NOT NULL DEFAULT '',
    user_id INTEGER,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_radio_images ON radio_images(radio_id, id);
"""

TARGETS_V3_REBUILD = """
CREATE TABLE targets_v3 (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind TEXT NOT NULL CHECK (kind IN ('local', 'ssh', 'printer')),
    host TEXT NOT NULL DEFAULT '',
    port INTEGER NOT NULL DEFAULT 22,
    username TEXT NOT NULL DEFAULT '',
    os TEXT NOT NULL DEFAULT 'linux' CHECK (os IN ('linux', 'windows')),
    credential_id INTEGER REFERENCES credentials(id) ON DELETE SET NULL,
    host_fingerprint TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    roles TEXT NOT NULL DEFAULT 'general',
    created_at INTEGER NOT NULL
);
INSERT INTO targets_v3(id, name, kind, host, port, username, os, credential_id, host_fingerprint, enabled, created_at)
    SELECT id, name, kind, host, port, username, os, credential_id, host_fingerprint, enabled, created_at FROM targets;
DROP TABLE targets;
ALTER TABLE targets_v3 RENAME TO targets;
"""


def now() -> int:
    return int(time.time())


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open a short-lived connection; commit on success, roll back on error."""
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("BEGIN")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    finally:
        conn.close()


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(str(path), timeout=10)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        conn.executescript(SCHEMA_V2)
        _migrate_targets_v3(conn)
        conn.executescript(SCHEMA_V3)
        _add_column(conn, "users", "can_exec", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "conversations", "exec_on", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "conversations", "target_id", "INTEGER")
        _add_column(conn, "conversations", "radio_target_id", "INTEGER")
        _add_column(conn, "conversations", "build_target_id", "INTEGER")
        _add_column(conn, "conversations", "printer_target_id", "INTEGER")
        _add_column(conn, "actions", "kind", "TEXT NOT NULL DEFAULT 'command'")
        _add_column(conn, "actions", "payload", "TEXT NOT NULL DEFAULT ''")
        _add_column(conn, "actions", "diff", "TEXT NOT NULL DEFAULT ''")
        _add_column(conn, "conversations", "project", "TEXT NOT NULL DEFAULT ''")
        _add_column(conn, "conversations", "small_steps", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "conversations", "summary", "TEXT NOT NULL DEFAULT ''")
        _add_column(conn, "conversations", "summary_upto", "INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION),))
        conn.commit()
    finally:
        conn.close()
    path.chmod(0o600)


_ALLOWED_COLUMNS = {
    ("users", "can_exec"),
    ("conversations", "exec_on"),
    ("conversations", "target_id"),
    ("conversations", "radio_target_id"),
    ("conversations", "build_target_id"),
    ("conversations", "printer_target_id"),
    ("actions", "kind"),
    ("actions", "payload"),
    ("actions", "diff"),
    ("conversations", "project"),
    ("conversations", "small_steps"),
    ("conversations", "summary"),
    ("conversations", "summary_upto"),
}


def _migrate_targets_v3(conn: sqlite3.Connection) -> None:
    """v2 -> v3: allow kind 'printer' and add roles. SQLite can't alter a CHECK, so rebuild the table."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(targets)")}
    if "roles" in cols:
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript("BEGIN;" + TARGETS_V3_REBUILD + "COMMIT;")


def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """Idempotent migration. Names come from the fixed allowlist above, never from input."""
    if (table, column) not in _ALLOWED_COLUMNS:
        raise ValueError("column not allowed")
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}  # noqa: S608 # nosec B608
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")  # nosec B608


def get_setting(conn: sqlite3.Connection, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row is not None else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def audit(conn: sqlite3.Connection, user_id: int | None, event: str, detail: str = "") -> None:
    """Record a security event. Never pass secrets in detail."""
    conn.execute(
        "INSERT INTO audit(at, user_id, event, detail) VALUES (?, ?, ?, ?)",
        (now(), user_id, event[:64], detail[:200]),
    )
    conn.execute(
        "DELETE FROM audit WHERE id <= (SELECT MAX(id) FROM audit) - ?",
        (MAX_AUDIT_ROWS,),
    )
