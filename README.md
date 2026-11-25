# Ember and ColdBoot

**Version 0.3.1** · private repo `wescom-matt/ember` · runs on the Nomad box (ThinkPad P1, `think-pad-p1`, 192.168.1.177)

- **Ember** is an offline chat assistant with a Grok Bot-style web interface. You use it from any browser on the home network. It talks to the local Ollama models and the Nomad knowledge base and never contacts the internet. It can also run commands on the P1 and on other computers, with safety checks.
- **ColdBoot** (`coldboot.sh`) rebuilds the whole P1 agent stack and Ember with one command, even offline from a USB disk. It also checks health and backs up and restores Ember's data.

| Document | What's in it |
|---|---|
| [docs/RECOVERY-PLAN.md](docs/RECOVERY-PLAN.md) | Full description of the system and a plain disaster recovery plan for each scenario |
| [COLDBOOT.md](COLDBOOT.md) | Step-by-step rebuild guide: USB contents, fresh install, sudo steps, troubleshooting |
| [coldboot/Modelfiles.md](coldboot/Modelfiles.md) | Recipes for the custom 4k models |

---

## Contents
1. [The system on the P1](#1-the-system-on-the-p1)
2. [Ember features](#2-ember-features)
3. [Architecture](#3-architecture)
4. [Install](#4-install)
5. [Using Ember](#5-using-ember)
6. [Running commands safely](#6-running-commands-safely)
7. [Security model](#7-security-model)
8. [ColdBoot](#8-coldboot)
9. [Backup and restore](#9-backup-and-restore)
10. [Offline cache](#10-offline-cache)
11. [Where things live](#11-where-things-live)
12. [Repo layout](#12-repo-layout)
13. [Development](#13-development)
14. [Version history](#14-version-history)

---

## 1. The system on the P1

| Part | Role | Address / command |
|---|---|---|
| Nomad (Project Nomad, Docker) | Offline library; installed separately from this repo | `/opt/project-nomad` |
| Qdrant (in Nomad) | Library search index, collection `nomad_knowledge_base` (~3.6M passages) | `127.0.0.1:6333` |
| Ollama 0.40.14 (in Nomad) | Runs the models | `127.0.0.1:11434` |
| Models | `qwen3.5-9b-4k` (default, tools), `llama3.2-4k`, `llama3.2-1b-4k`, `nomic-embed-text:v1.5` (embedder); bases `qwen3.5:9b`, `llama3.2`, `llama3.2:1b`; optional `gemma4:26b`, `llama3.1:8b` | |
| nomad-search | Library search CLI and Goose MCP extension | `nomad-search "question"` |
| Goose 1.59.1 | Terminal agent, approve mode | `goose`, `goose-lw "task"` (planner + worker) |
| Open Interpreter 0.4.3 | Code agent with the Nomad profile, auto-run off | `ai-interp` |
| Ember | Web chat (this repo) | `https://192.168.1.177:8600` |

The 4k models are the base models with `num_ctx 4096` so they fit the 4 GB T1000 graphics card.

## 2. Ember features

**Chat (phase 1, 0.1.0)**
- Accounts with passwords and admin roles. No open sign-up; admins create users.
- Saved chats per user: rename, delete, search.
- Streaming replies, model picker (embedding models are hidden), optional Think mode for models that support it.
- Knowledge-base picker: **None** or **Nomad**. Nomad answers cite their sources. Search is live against Qdrant, so new Nomad content appears automatically.
- Safe Markdown rendering, code highlighting (vendored highlight.js 11.11.1) and a Copy button.

**Commands (phase 2, 0.2.0)**
- Run commands on the P1 (**This computer**) or over SSH on Linux (bash) and Windows (PowerShell) computers.
- Admin-managed targets and credentials. Ember generates SSH keys and shows only the public key; passwords and private keys are encrypted.
- A risk classifier: read-only commands run automatically, risky ones wait for **Run** / **Cancel**.
- Master switch (off by default), per-user **Run commands** permission, and an audit log.

**ColdBoot (phase 3, 0.3.0):** rebuild, health check, backup/restore and offline cache (sections 8-10).

## 3. Architecture

```
Browser (home network)
   │  HTTPS :8600 (self-signed TLS)
   ▼
Ember  ── FastAPI + uvicorn, one process, systemd --user service "ember"
   ├── SQLite (WAL) ~/.local/share/ember/ember.db: users, sessions, chats, targets, credentials, actions, audit
   ├── Vault: Fernet key in ~/.config/ember/secret.key encrypts credentials
   ├── Ollama   http://127.0.0.1:11434  (chat, tool calls)       ┐ loopback only;
   ├── Qdrant   http://127.0.0.1:6333   (Nomad knowledge base)   ┘ enforced in config
   └── Runner: local bash (argument list, no shell=True) or SSH via paramiko
```

- Python 3.12 (uv-managed), FastAPI, uvicorn, argon2-cffi, paramiko, cryptography. Packages are pinned with hashes.
- Front end: plain HTML/CSS/JS in `ember/static/`, no CDN and no build step.
- **SQLite rather than Postgres:** a few users and one process means one file, no extra server and an easy backup. That suits a power-limited, off-grid box.
- **Knowledge bases** live in `ember/kb.py`. To add one, write a class with `search()` and register it in `build_registry`.
- A command-enabled chat turn (`ember/agent.py`): the model may call `run_command` up to 4 times. A risky command pauses the turn. The context is saved on the pending action, and the turn resumes after Run or Cancel. Credentials never enter the model's context.

## 4. Install

**Full machine rebuild:** use ColdBoot. See [COLDBOOT.md](COLDBOOT.md).

**Ember alone (no sudo):**

```bash
git clone git@github.com:wescom-matt/ember.git ~/ember    # must live at ~/ember
cd ~/ember && ./install.sh
ember create-admin matt
```

`install.sh` does the following:
- creates `.venv` with Python 3.12 and installs `requirements.txt` with `--require-hashes` (`EMBER_WHEELS=/dir` installs offline from wheels)
- writes `~/.config/ember/ember.env`
- makes a 10-year self-signed certificate
- installs and starts `ember.service`
- turns on linger, or writes `~/ember-sudo-steps.sh` if that needs sudo

It needs `uv`, Python 3.12, Ollama and Qdrant on loopback.

Settings (`~/.config/ember/ember.env`, no secrets): `EMBER_HOST`, `EMBER_PORT` (8600), `EMBER_DEFAULT_MODEL` (qwen3.5-9b-4k), `EMBER_OLLAMA_URL`, `EMBER_QDRANT_URL`, `EMBER_DATA_DIR`, `EMBER_TLS_CERT`, `EMBER_TLS_KEY`, `EMBER_SECURE_COOKIES`.

## 5. Using Ember

**Open it**
- On the home network: `https://192.168.1.177:8600`. The certificate is self-signed, so accept the browser warning once.
- From away (until Tailscale is set up): `ssh -L 8600:127.0.0.1:8600 matt@192.168.1.177`, then open `https://localhost:8600`.

**The `ember` command (on the P1)**

| Command | What it does |
|---|---|
| `ember status` / `start` / `stop` / `restart` | Controls the service (`systemctl --user ... ember`) |
| `ember logs [N]` | Last N log lines (default 50) |
| `ember url` | The LAN address |
| `ember create-admin NAME` | Creates an admin; the password is typed at a hidden prompt (10+ characters) |
| `ember reset-password NAME` | Sets a new password |
| `ember list-users` | Lists accounts |
| `ember version` | Prints the version |

Passwords are never accepted as command-line arguments, printed or logged.

**Admin (sidebar → Users & admin)**
- **Users:** add users, grant or revoke admin, give **Run commands** permission, disable accounts and reset passwords. Ember always keeps at least one active admin. There is a limit of 50 users.
- **Targets & credentials:** the master switch, credentials, targets, Test and Reset key.
- **Audit:** logins, failed logins and lockouts, user and admin changes, the master switch, credential and target changes, and every command with its risk, decision and exit code.

## 6. Running commands safely

1. **Users & admin → Targets & credentials.** Turn on **Command running** (the master switch; it is off by default).
2. To add an SSH target:
   - Add a credential and choose **Generate SSH key**. Click **Copy public key** and add it as one line to `~/.ssh/authorized_keys` on that computer. On Windows, use `C:\Users\<you>\.ssh\authorized_keys`, or `administrators_authorized_keys` for admin accounts. A password credential also works.
   - Add the target with its host, port, user, Linux or Windows, and the credential.
   - Click **Test**. The first connection stores the host key's SHA-256 fingerprint. If the key ever changes, Ember refuses to connect until an admin clicks **Reset key**.
3. The P1 itself: add a target of type **This computer**. No key is needed.
4. Non-admins need **Run commands** ticked.
5. In a chat, tick **Commands**, pick a target and ask. The model must support tools; the default `qwen3.5-9b-4k` does. If commands are off, there's no target, or the model lacks tools, Ember just answers and says why.

**Limits:** 4 commands per reply, a 120-second timeout each, commands up to 2,000 characters. Output is stored up to 8,000 characters, and the model sees 2,500. Known secrets are redacted from output.

**Risky commands always ask first** (the classifier fails closed):
- recursive delete, `dd`, `mkfs`
- shutdown or reboot
- recursive chmod or chown, `sudo`, package installs
- writes outside your home folder, command substitution
- flashing (`esptool write_flash`, `arduino-cli upload`, `pio -t upload`)
- PowerShell `Remove-Item -Recurse`, `Format-*`, `Stop-Computer`
- unknown or unparseable commands

Ember never installs anything on other computers. ESP32 tools are used only if already installed there.

## 7. Security model

- **Offline:** backend URLs must be `http://127.0.0.1`; anything else is refused at startup.
- **Passwords:** argon2id. Logins lock for 5 minutes after 5 failures.
- **Sessions:** random tokens stored only as SHA-256 hashes. Cookies are HttpOnly, SameSite=Strict and Secure, and last 7 days, with at most 10 sessions per user.
- **Web:** an `X-Ember: 1` header is required on writes (blocks cross-site requests). Strict Content-Security-Policy with no inline scripts and no CDN. Markdown is rendered safely.
- **Data:** bound SQL parameters everywhere, and every list and input has a size cap.
- **Credentials:** Fernet-encrypted with `~/.config/ember/secret.key` (mode 600, kept outside the database). A copied database alone reveals nothing.
- **Commands:** run through argument lists, never `shell=True`. Gated by the master switch, per-user permission, the classifier and Confirm cards, with timeouts and output caps. SSH host keys are trust-on-first-use, and a changed key is refused.
- **Service:** `systemd --user` with `UMask=0077` and `NoNewPrivileges`.
- **Secrets never go in the repo** (`.gitignore` covers `*.key`, `*.env`, `*.db`, `*.pem`).
- **Coding rules:** `.cursor/rules/power-of-10.mdc` and `.cursor/rules/secure-coding.mdc` (NASA Power of 10, SEI CERT, Bandit).

## 8. ColdBoot

```bash
cd ~/ember
./coldboot.sh check                         # PASS/WARN/FAIL for every part; exit 1 on any FAIL
./coldboot.sh install [--cache DIR] [--dry-run]
./coldboot.sh install --system              # print + save the sudo-only steps
./coldboot.sh backup [--out DIR]
./coldboot.sh restore ARCHIVE [--to DIR] [--dry-run] [--yes]
./coldboot.sh cache DIR [--skip-models]
```

`install` runs as your normal user, never uses sudo, and is safe to re-run. It skips anything already correct and saves any file it changes as `*.bak-coldboot-<date>`. Its steps:

1. **Preflight:** x86_64, not root, required tools; verifies the cache checksums.
2. **uv**, then **Python 3.12**.
3. **Ollama:** uses Nomad's if running; otherwise unpacks a user-space copy from the cache.
4. **Models:** copies missing ones from the cache (checksummed) or pulls them, then rebuilds the 4k models from `coldboot/models.json`.
5. **Goose 1.59.1**, pinned by SHA-256.
6. **Open Interpreter 0.4.3** from cached wheels or the lock file.
7. **Configs:** Goose `config.yaml` (no secrets), `goose-lw`, `ai-interp`, the Interpreter profiles (`nomad.py`, `default.yaml`), `AI-AGENTS-README.md` and the PATH snippet.
8. **nomad-search** and its Goose extension.
9. **Ember:** venv from hashed requirements, `ember.service`, linger.
10. **Nomad check:** read-only. It reports clearly if Qdrant or `nomad_knowledge_base` is missing. ColdBoot never changes Qdrant data.

The sudo-only steps go in `~/coldboot-sudo-steps.sh` for you to read and run:
- `apt install zstd curl git openssl sqlite3`
- linger
- a ufw rule for port 8600 from 192.168.1.0/24
- optional: the Goose desktop `.deb`
- optional: a system Ollama service, only without Nomad

Downloads are https-only and must match the SHA-256 values in `coldboot/pins.txt`. There is no `curl | sh`.

ColdBoot replaces `~/agent-stack-backup/rebuild.sh`. That kit still works, and `coldboot cache` reuses its files.

## 9. Backup and restore

- `backup` writes `ember-coldboot-<host>-<date>.tar.gz` (mode 600) plus a `.sha256` file. Inside are:
  - `ember.db`, copied safely with SQLite's backup API while Ember runs, then integrity-checked. It holds users, chats, targets, host fingerprints, encrypted credentials and the audit log.
  - `secret.key`, `ember.env`, and the TLS cert and key
  - the Goose config, the Interpreter profiles, `goose-lw` and `ai-interp`
  - `MANIFEST.txt` and `SHA256SUMS`
- **The archive contains the secret key.** Keep it offline (a USB stick in a drawer). The key is never printed.
- Before writing anything, `restore` checks:
  - the archive checksum and every file checksum
  - that there are no absolute paths, `..`, links or files missing from `SHA256SUMS`

  It then stops Ember, keeps replaced files as `*.pre-restore-<date>`, restores and starts Ember again. `--to DIR` restores into a test folder, and `--dry-run` only verifies.

## 10. Offline cache

`./coldboot.sh cache /media/matt/USB/coldboot-cache` fills a folder (USB disk) with:

| Folder | Contents | Size |
|---|---|---|
| `models/` | Ollama manifests and blobs for all base and 4k models (exported read-only from Nomad's store, checksummed) | ~10.2 GB |
| `ollama/` | Ollama 0.40.14 tarball | ~1.5 GB |
| `goose/` | Goose 1.59.1 binary and desktop `.deb` | ~0.34 GB |
| `python/` | uv, uvx, CPython 3.12.16, Open Interpreter wheels and lock file | ~0.21 GB |
| `ember-wheels/` | Ember's hashed wheels | ~0.01 GB |
| `ember.bundle` | Full git copy of this repo | <1 MB |
| `COLDBOOT.md`, `SHA256SUMS` | Guide and checksums | |

**Total about 12.5 GB.** Use a 32 GB USB disk. Then rebuild offline with `./coldboot.sh install --cache /media/matt/USB/coldboot-cache`.

## 11. Where things live

| What | Where |
|---|---|
| Code | `~/ember` (this repo; the service expects this path) |
| Settings | `~/.config/ember/ember.env` (no secrets) |
| TLS cert and key | `~/.config/ember/tls/` (mode 600) |
| Credential key | `~/.config/ember/secret.key` (mode 600; back it up with the database) |
| Database | `~/.local/share/ember/ember.db` |
| Service | `~/.config/systemd/user/ember.service` |
| ColdBoot backups (default) | `~/coldboot-backups/` |
| Sudo steps | `~/coldboot-sudo-steps.sh`, `~/ember-sudo-steps.sh` |
| Goose config | `~/.config/goose/config.yaml` |
| nomad-search | `~/agent-stack/nomad-search` |
| Older rebuild kit | `~/agent-stack-backup/` |

## 12. Repo layout

```
ember/                 app code
  app.py               web routes (login, chats, admin users, models, KBs)
  routes_exec.py       targets, credentials, master switch, confirm/cancel, audit
  chat.py agent.py     plain chat turn / tool-calling turn
  classifier.py        command risk rules (fail closed)
  runner.py            local and SSH execution (paramiko)
  targets.py vault.py  targets/credentials, Fernet vault, SSH key generation
  auth.py deps.py      passwords, sessions, throttling, request checks
  db.py config.py      SQLite schema and migrations, settings and limits
  kb.py ollama.py httpjson.py prompts.py cli.py
  static/              index.html, app.css, app.js, markdown.js, vendor/highlight.js
bin/ember              helper command
deploy/                ember.service, ember.env.example
install.sh             Ember installer (no sudo)
coldboot.sh            ColdBoot
coldboot/              models.json, Modelfiles.md, pins.txt, cbmodels.py (model export/import/create)
coldboot/stack/        templates of the P1 tool configs and a copy of nomad-search
docs/RECOVERY-PLAN.md  system description and recovery plan
COLDBOOT.md            rebuild guide
scripts/make_preview.py  static design previews
tests/                 pytest: app, exec, units, coldboot
requirements*.in/.txt  pinned, hashed dependencies
```

## 13. Development

```bash
EMBER_DEV=1 ./install.sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check . && .venv/bin/mypy ember coldboot/cbmodels.py
.venv/bin/bandit -q -c pyproject.toml -r ember coldboot
.venv/bin/shellcheck -x coldboot.sh install.sh bin/ember
.venv/bin/pip-audit -r requirements.txt
.venv/bin/python scripts/make_preview.py ~/Desktop/ember-preview
```

To regenerate the pins: `uv pip compile requirements.in --python-version 3.12 --generate-hashes -o requirements.txt` (and the same for `-dev`). highlight.js 11.11.1 (BSD-3-Clause) is vendored in `ember/static/vendor/`.

## 14. Version history

| Version | What changed |
|---|---|
| 0.1.0 | Offline chat: logins, history, model picker, Nomad knowledge base, streaming UI |
| 0.2.0 | Commands: targets, encrypted credentials, risk classifier, confirm cards, audit log |
| 0.3.0 | ColdBoot: rebuild, check, backup/restore, offline cache, COLDBOOT.md |
| 0.3.1 | Full README, docs/RECOVERY-PLAN.md |
