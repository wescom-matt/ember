"""Users, password hashing (argon2id), sessions, and login throttling."""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import threading
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ember import config
from ember.db import audit, now

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,31}$")
_HASHER = PasswordHasher()
# Used to keep login timing similar for unknown usernames.
_DUMMY_HASH = _HASHER.hash(secrets.token_urlsafe(16))

MAX_FAILS = 5
LOCK_SECONDS = 300
MAX_TRACKED = 1_000


class AuthError(Exception):
    """Login or permission failure. Message is safe to show the user."""


def clean_username(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("username must be text")
    name = raw.strip().lower()
    if not USERNAME_RE.fullmatch(name):
        raise ValueError("username: 2-32 chars, a-z 0-9 . _ - (start with a letter or digit)")
    return name


def check_password_rules(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("password must be text")
    if len(raw) < config.MIN_PASSWORD:
        raise ValueError(f"password must be at least {config.MIN_PASSWORD} characters")
    if len(raw) > config.MAX_PASSWORD:
        raise ValueError("password is too long")
    return raw


def hash_password(password: str) -> str:
    return _HASHER.hash(check_password_rules(password))


def verify_password(pw_hash: str, password: str) -> bool:
    try:
        return _HASHER.verify(pw_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


class LoginThrottle:
    """Bounded in-memory lockout after repeated failures, per username."""

    def __init__(self) -> None:
        self._fails: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def locked(self, key: str) -> bool:
        with self._lock:
            count, since = self._fails.get(key, (0, 0.0))
            if count < MAX_FAILS:
                return False
            if time.monotonic() - since > LOCK_SECONDS:
                self._fails.pop(key, None)
                return False
            return True

    def fail(self, key: str) -> None:
        with self._lock:
            if len(self._fails) >= MAX_TRACKED and key not in self._fails:
                oldest = min(self._fails, key=lambda k: self._fails[k][1])
                self._fails.pop(oldest, None)
            count, _ = self._fails.get(key, (0, 0.0))
            self._fails[key] = (count + 1, time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._fails.clear()


THROTTLE = LoginThrottle()


def create_user(conn: sqlite3.Connection, username: str, password: str, is_admin: bool) -> int:
    name = clean_username(username)
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count >= config.MAX_USERS:
        raise ValueError("user limit reached")
    exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (name,)).fetchone()
    if exists:
        raise ValueError("that username is taken")
    cur = conn.execute(
        "INSERT INTO users(username, pw_hash, is_admin, is_active, created_at) VALUES (?, ?, ?, 1, ?)",
        (name, hash_password(password), 1 if is_admin else 0, now()),
    )
    user_id = int(cur.lastrowid or 0)
    if user_id <= 0:
        raise RuntimeError("user insert failed")
    return user_id


def authenticate(conn: sqlite3.Connection, username: object, password: object) -> sqlite3.Row:
    """Return the user row or raise AuthError with a generic message."""
    generic = AuthError("wrong username or password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise generic
    key = username.strip().lower()[: config.MAX_USERNAME]
    if THROTTLE.locked(key):
        audit(conn, None, "login_locked", key)
        raise AuthError("too many attempts; wait 5 minutes")
    if len(password) > config.MAX_PASSWORD:
        raise generic
    row = conn.execute(
        "SELECT id, username, pw_hash, is_admin, is_active FROM users WHERE username = ?", (key,)
    ).fetchone()
    if row is None:
        verify_password(_DUMMY_HASH, password)
        THROTTLE.fail(key)
        audit(conn, None, "login_fail", key)
        raise generic
    if not verify_password(row["pw_hash"], password) or not row["is_active"]:
        THROTTLE.fail(key)
        audit(conn, row["id"], "login_fail", key)
        raise generic
    THROTTLE.clear(key)
    _maybe_rehash(conn, row, password)
    user: sqlite3.Row = row
    return user


def _maybe_rehash(conn: sqlite3.Connection, row: sqlite3.Row, password: str) -> None:
    if _HASHER.check_needs_rehash(row["pw_hash"]):
        conn.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (_HASHER.hash(password), row["id"]))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session(conn: sqlite3.Connection, user_id: int) -> str:
    """Create a session; only the SHA-256 of the token is stored."""
    token = secrets.token_urlsafe(32)
    t = now()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (t,))
    conn.execute(
        "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (_token_hash(token), user_id, t, t + config.SESSION_HOURS * 3600),
    )
    conn.execute(
        "DELETE FROM sessions WHERE user_id = ? AND token_hash NOT IN "
        "(SELECT token_hash FROM sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?)",
        (user_id, user_id, config.MAX_SESSIONS_PER_USER),
    )
    return token


def session_user(conn: sqlite3.Connection, token: str | None) -> sqlite3.Row | None:
    if not token or len(token) > 128:
        return None
    row: sqlite3.Row | None = conn.execute(
        "SELECT u.id, u.username, u.is_admin FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = 1",
        (_token_hash(token), now()),
    ).fetchone()
    return row


def end_session(conn: sqlite3.Connection, token: str | None) -> None:
    if token and len(token) <= 128:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def end_all_sessions(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def set_password(conn: sqlite3.Connection, user_id: int, password: str) -> None:
    cur = conn.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (hash_password(password), user_id))
    if cur.rowcount != 1:
        raise ValueError("no such user")
    end_all_sessions(conn, user_id)


def active_admin_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1 AND is_active = 1").fetchone()[0])
