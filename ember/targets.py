"""Targets (where commands run) and credentials (how to log in). Admin-managed."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from ember import config
from ember.db import now
from ember.runner import Secret, TargetSpec
from ember.vault import Vault, generate_ssh_key

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}$")
HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$|^[0-9a-fA-F:]{2,39}$")
USER_RE = re.compile(r"^[A-Za-z0-9._\\-]{1,64}$")
TARGET_COLS = "id, name, kind, host, port, username, os, credential_id, host_fingerprint, enabled"


def clean_name(raw: str, what: str) -> str:
    name = (raw or "").strip()
    if not NAME_RE.fullmatch(name):
        raise ValueError(f"{what} name: 1-40 letters, digits, space . _ -")
    return name


def list_credentials(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, name, kind, public_key, created_at FROM credentials ORDER BY name LIMIT ?",
        (config.MAX_CREDENTIALS,),
    ).fetchall()
    return [dict(r) for r in rows]


def _check_credential_room(conn: sqlite3.Connection, name: str) -> None:
    if conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0] >= config.MAX_CREDENTIALS:
        raise ValueError("credential limit reached")
    if conn.execute("SELECT 1 FROM credentials WHERE name = ?", (name,)).fetchone():
        raise ValueError("a credential with that name exists")


def add_key_credential(conn: sqlite3.Connection, vault: Vault, raw_name: str) -> dict[str, Any]:
    name = clean_name(raw_name, "credential")
    _check_credential_room(conn, name)
    private, public = generate_ssh_key(f"ember-{name.replace(' ', '-')}")
    cur = conn.execute(
        "INSERT INTO credentials(name, kind, public_key, secret_enc, created_at) VALUES (?, 'key', ?, ?, ?)",
        (name, public, vault.encrypt(private), now()),
    )
    return {"id": int(cur.lastrowid or 0), "name": name, "kind": "key", "public_key": public}


def add_password_credential(conn: sqlite3.Connection, vault: Vault, raw_name: str, password: str) -> dict[str, Any]:
    name = clean_name(raw_name, "credential")
    if not password or len(password) > config.MAX_PASSWORD:
        raise ValueError("password is empty or too long")
    _check_credential_room(conn, name)
    cur = conn.execute(
        "INSERT INTO credentials(name, kind, public_key, secret_enc, created_at) VALUES (?, 'password', '', ?, ?)",
        (name, vault.encrypt(password), now()),
    )
    return {"id": int(cur.lastrowid or 0), "name": name, "kind": "password", "public_key": ""}


def list_targets(conn: sqlite3.Connection, enabled_only: bool) -> list[dict[str, Any]]:
    sql = f"SELECT {TARGET_COLS} FROM targets"  # noqa: S608 # nosec B608
    if enabled_only:
        sql += " WHERE enabled = 1"
    rows = conn.execute(sql + " ORDER BY name LIMIT ?", (config.MAX_TARGETS,)).fetchall()
    return [dict(r) for r in rows]


def validate_target(body: dict[str, Any]) -> dict[str, Any]:
    kind = body.get("kind")
    if kind not in ("local", "ssh"):
        raise ValueError("kind must be local or ssh")
    os_type = body.get("os") or "linux"
    if os_type not in ("linux", "windows"):
        raise ValueError("os must be linux or windows")
    out = {"name": clean_name(str(body.get("name") or ""), "target"), "kind": kind, "os": os_type,
           "host": "", "port": 22, "username": "", "credential_id": None}
    if kind == "local":
        out["os"] = "linux"
        return out
    host = str(body.get("host") or "").strip()
    user = str(body.get("username") or "").strip()
    port = int(body.get("port") or 22)
    if not HOST_RE.fullmatch(host):
        raise ValueError("host must be a hostname or IP address")
    if not USER_RE.fullmatch(user):
        raise ValueError("user name has invalid characters")
    if port < 1 or port > 65535:
        raise ValueError("port must be 1-65535")
    cred = body.get("credential_id")
    out.update(host=host, username=user, port=port, credential_id=int(cred) if cred else None)
    return out


def save_target(conn: sqlite3.Connection, data: dict[str, Any], target_id: int | None) -> int:
    cred = data["credential_id"]
    if cred is not None and not conn.execute("SELECT 1 FROM credentials WHERE id = ?", (cred,)).fetchone():
        raise ValueError("unknown credential")
    args = (data["name"], data["kind"], data["host"], data["port"], data["username"], data["os"], data["credential_id"])
    clash = conn.execute("SELECT id FROM targets WHERE name = ?", (data["name"],)).fetchone()
    if clash and clash["id"] != target_id:
        raise ValueError("a target with that name exists")
    if target_id is None:
        if conn.execute("SELECT COUNT(*) FROM targets").fetchone()[0] >= config.MAX_TARGETS:
            raise ValueError("target limit reached")
        cur = conn.execute(
            "INSERT INTO targets(name, kind, host, port, username, os, credential_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (*args, now()),
        )
        return int(cur.lastrowid or 0)
    cur = conn.execute(
        "UPDATE targets SET name = ?, kind = ?, host = ?, port = ?, username = ?, os = ?, credential_id = ?, "
        "host_fingerprint = '' WHERE id = ?", (*args, target_id),
    )
    if cur.rowcount != 1:
        raise ValueError("no such target")
    return target_id


def resolve(conn: sqlite3.Connection, vault: Vault, target_id: int) -> tuple[TargetSpec, Secret | None]:
    row = conn.execute(
        "SELECT t.id, t.name, t.kind, t.host, t.port, t.username, t.os, t.host_fingerprint, t.enabled, "  # noqa: S608
        "c.kind AS ckind, c.secret_enc FROM targets t LEFT JOIN credentials c ON c.id = t.credential_id "
        "WHERE t.id = ?", (target_id,),
    ).fetchone()
    if row is None or not row["enabled"]:
        raise ValueError("target is missing or disabled")
    spec = TargetSpec(int(row["id"]), row["name"], row["kind"], row["host"], int(row["port"]),
                      row["username"], row["os"], row["host_fingerprint"])
    secret = Secret(row["ckind"], vault.decrypt(row["secret_enc"])) if row["secret_enc"] else None
    return spec, secret


def remember_fingerprint(conn: sqlite3.Connection, target_id: int, fingerprint: str) -> None:
    conn.execute(
        "UPDATE targets SET host_fingerprint = ? WHERE id = ? AND host_fingerprint = ''", (fingerprint[:200], target_id)
    )
