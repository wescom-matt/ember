# Ember

Ember is an offline chat assistant with a Grok Bot-style interface. It runs on the Nomad box (ThinkPad P1) and you use it from a browser on the home network. It uses the local Ollama models and the Nomad knowledge base, and it never contacts the internet.

**Phase 1 (this version, 0.1.0):** logins with admin roles, saved chats per user (rename, delete, search), streaming replies, a model picker, a Nomad knowledge-base picker with sources, code blocks with highlighting and a Copy button, and an optional Think mode for models that support it.

**Later:** phase 2 adds commands on the P1 and over SSH to selectable targets, with a master on/off switch and confirmation for risky commands. Phase 3 is **ColdBoot**, a full rebuild installer and guide.

## Open it

- On the home network, go to `https://192.168.1.177:8600`. The certificate is self-signed, so the browser will warn you the first time. Accept it once.
- From away, use an SSH tunnel: `ssh -L 8600:127.0.0.1:8600 matt@<p1>`, then open `https://localhost:8600`.

## Everyday commands (on the P1)

| Command | What it does |
|---|---|
| `ember status` | Shows whether it's running |
| `ember start` / `ember stop` / `ember restart` | Starts, stops, or restarts the service (`systemctl --user ... ember`) |
| `ember logs` | Shows the last 50 log lines |
| `ember url` | Prints the LAN address |
| `ember create-admin NAME` | Creates the first admin account. It asks for the password at a hidden prompt |
| `ember reset-password NAME` | Sets a new password if someone is locked out |
| `ember list-users` | Lists accounts |

Admins add users, grant or revoke admin, disable accounts, and reset passwords from **Users & admin** in the sidebar. There is no open sign-up, and Ember always keeps at least one active admin.

## Install or reinstall (no sudo)

```bash
git clone <repo> ~/ember     # or copy the folder
cd ~/ember && ./install.sh    # venv, pinned packages, config, TLS cert, systemd --user unit
ember create-admin matt
```

The installer needs `uv` and Python 3.12 (both already on the P1), plus Ollama on 127.0.0.1:11434 and Qdrant on 127.0.0.1:6333. If it can't turn on "linger" (which keeps Ember running when nobody is logged in), it writes `~/ember-sudo-steps.sh` for you to run once.

## Where things live

| What | Where |
|---|---|
| Code | `~/ember` (this repo) |
| Settings | `~/.config/ember/ember.env` (port, default model, URLs; no secrets) |
| TLS certificate and key | `~/.config/ember/tls/` (mode 600, never committed) |
| Chats and users | `~/.local/share/ember/ember.db` (SQLite; back up this file) |

## Design notes

- **SQLite instead of Postgres:** a handful of users and one process means one file, no extra server, nothing to keep running, and a trivial backup. That matters on a box built for power-limited, off-grid use.
- **Knowledge bases** are listed in `ember/kb.py`. Nomad queries Qdrant live with the same embedding model and `search_query:` prefix that Nomad itself uses, so anything new indexed into Nomad shows up automatically. To add a knowledge base, write a class with a `search()` method and register it in `build_registry`.
- **Security:** argon2id password hashes. Sessions are random tokens stored only as SHA-256 hashes, in HttpOnly, SameSite=Strict, Secure cookies. A custom request header blocks cross-site writes, plus a strict CSP with no inline scripts or CDN. Logins lock for 5 minutes after 5 failed attempts. Backend URLs are forced to loopback, and every SQL query uses bound parameters. Security events go to an audit table without secrets.
- **Coding rules:** `.cursor/rules/power-of-10.mdc` and `.cursor/rules/secure-coding.mdc`.

## Development

```bash
EMBER_DEV=1 ./install.sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check . && .venv/bin/mypy ember && .venv/bin/bandit -q -r ember -c pyproject.toml
.venv/bin/pip-audit -r requirements.txt
.venv/bin/python scripts/make_preview.py ~/Desktop/ember-preview   # static design previews
```

Dependencies are pinned with hashes in `requirements.txt`. To regenerate them, run `uv pip compile requirements.in --generate-hashes`. highlight.js 11.11.1 (BSD-3-Clause) is vendored in `ember/static/vendor/`.
