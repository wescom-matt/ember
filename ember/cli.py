"""Command line: serve, create-admin, list-users, reset-password, version.

Passwords are typed at a hidden prompt (getpass); they are never echoed,
printed, logged, or accepted as command-line arguments.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys

from ember import __version__, auth
from ember.config import load_settings
from ember.db import audit, connect, init_db

MAX_PROMPT_TRIES = 3


def _ask_password() -> str:
    for _ in range(MAX_PROMPT_TRIES):
        first = getpass.getpass("New password (10+ characters): ")
        second = getpass.getpass("Type it again: ")
        if first != second:
            print("Passwords did not match.", file=sys.stderr)
            continue
        try:
            return auth.check_password_rules(first)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
    raise SystemExit("Giving up after 3 tries.")


def cmd_create_admin(username: str) -> int:
    settings = load_settings()
    init_db(settings.db_path)
    name = auth.clean_username(username)
    password = _ask_password()
    with connect(settings.db_path) as conn:
        user_id = auth.create_user(conn, name, password, is_admin=True)
        audit(conn, user_id, "admin_created_cli")
    print(f"Admin '{name}' created. Sign in at the Ember page.")
    return 0


def cmd_reset_password(username: str) -> int:
    settings = load_settings()
    init_db(settings.db_path)
    name = auth.clean_username(username)
    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()
        if row is None:
            print(f"No user '{name}'.", file=sys.stderr)
            return 1
        auth.set_password(conn, int(row["id"]), _ask_password())
        audit(conn, int(row["id"]), "password_reset_cli")
    print(f"Password for '{name}' changed; their old sessions were signed out.")
    return 0


def cmd_list_users() -> int:
    settings = load_settings()
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        rows = conn.execute("SELECT username, is_admin, is_active FROM users ORDER BY username LIMIT 100").fetchall()
    if not rows:
        print("No users yet. Run: ember create-admin <name>")
    for r in rows:
        flags = ("admin " if r["is_admin"] else "") + ("" if r["is_active"] else "disabled")
        print(f"{r['username']:<32} {flags}".rstrip())
    return 0


def cmd_serve() -> int:
    import uvicorn

    from ember.app import create_app

    settings = load_settings()
    cert = os.environ.get("EMBER_TLS_CERT", "").strip()
    key = os.environ.get("EMBER_TLS_KEY", "").strip()
    if bool(cert) != bool(key):
        raise SystemExit("Set both EMBER_TLS_CERT and EMBER_TLS_KEY, or neither.")
    if not cert and settings.secure_cookies:
        raise SystemExit("No TLS configured: set EMBER_SECURE_COOKIES=0 for plain HTTP (localhost only).")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        ssl_certfile=cert or None,
        ssl_keyfile=key or None,
        proxy_headers=False,
        server_header=False,
        access_log=False,
        timeout_keep_alive=10,
        limit_concurrency=32,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ember", description="Ember offline chat")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run the web app (systemd uses this)")
    p = sub.add_parser("create-admin", help="create an admin account (asks for the password)")
    p.add_argument("username")
    p = sub.add_parser("reset-password", help="set a new password for a user (asks for it)")
    p.add_argument("username")
    sub.add_parser("list-users", help="list accounts")
    sub.add_parser("version", help="print the version")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "serve":
            return cmd_serve()
        if args.cmd == "create-admin":
            return cmd_create_admin(args.username)
        if args.cmd == "reset-password":
            return cmd_reset_password(args.username)
        if args.cmd == "list-users":
            return cmd_list_users()
        print(__version__)
        return 0
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
