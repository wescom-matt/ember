# ColdBoot: rebuild the P1 after a disaster

ColdBoot puts the whole P1 agent setup back: Ollama models, Goose, Open Interpreter,
nomad-search and Ember. You need one USB disk and one command.

**Nomad is separate.** Reinstall Nomad first, the way you did originally. Nomad brings
Ollama and the knowledge base (Qdrant). ColdBoot checks them but never changes them.

---

## 1. What to keep on the USB disk (do this now, then again after big changes)

Use a 32 GB USB disk. Plug it into the P1. It shows up as something like
`/media/matt/USB`.

```bash
cd ~/ember
./coldboot.sh cache /media/matt/USB/coldboot-cache     # about 18 GB; takes 20-40 minutes
./coldboot.sh backup --out /media/matt/USB/backups     # a few MB
```

You end up with:

| On the USB | What it is | Size |
|---|---|---|
| `coldboot-cache/models/` | Ollama models: qwen3.5:9b, llama3.2, llama3.2:1b, nomic-embed-text and the 3 custom 4k models | ~10.2 GB |
| `coldboot-cache/ollama/` | Ollama 0.40.14 (only used if there is no Nomad) | ~1.5 GB |
| `coldboot-cache/goose/` | Goose 1.59.1 program and desktop .deb | ~0.35 GB |
| `coldboot-cache/python/` | uv, Python 3.12 and Open Interpreter's packages | ~0.2 GB |
| `coldboot-cache/ember-wheels/` | Ember's Python packages | ~0.03 GB |
| `coldboot-cache/buildtools/` | CHIRP, PlatformIO + ESP32 packages, esptool, arduino-cli, OrcaSlicer and ElegooSlicer, Centauri Carbon 2 profiles | ~5.4 GB |
| `coldboot-cache/parts/` | Parts library: openly licensed 3D models and iFixit guides (cap with `--parts-gb N`, default 3) | ~0.2 GB |
| `coldboot-cache/radio-kb/` | Radio reference library (band plan, FCC rules, channel lists) | ~7 MB |
| `coldboot-cache/arduino/` | Arduino ESP32 core, only with `--with-arduino-core` (then use a 64 GB disk) | ~9 GB |
| `coldboot-cache/ember.bundle` | A full copy of this repo (in case GitHub is unreachable) | small |
| `coldboot-cache/SHA256SUMS` | Checksums; install checks every file | small |
| `backups/ember-coldboot-*.tar.gz` + `.sha256` | Ember's database (users, chats, targets, saved logins), its **secret key**, TLS cert, Goose/Interpreter settings | small |

> **WARNING: the backup contains Ember's secret key.** With it, anyone can read the
> SSH passwords and keys Ember stores. Keep that USB disk in a drawer. Do not
> email or upload the backup. Delete old backups you no longer need.

Not on the USB, by design: your SSH keys (`~/.ssh`), the GitHub deploy key, passwords.
Make new ones after a rebuild (see section 6).

---

## 2. Fresh install, step by step

1. Install Ubuntu on the P1. Make the user `matt`. Connect to the home network.
2. Reinstall Nomad as before. Wait until its library is indexed.
3. Open a terminal and install the basic tools (this needs your password):
   ```bash
   sudo apt install -y git curl zstd openssl sqlite3
   ```
4. Get this repo. It must live at `~/ember`.
   - With internet: `git clone git@github.com:wescom-matt/ember.git ~/ember`
     (needs a GitHub key; easier: use the USB copy)
   - From the USB: `git clone /media/matt/USB/coldboot-cache/ember.bundle ~/ember`
5. Check first, without changing anything:
   ```bash
   cd ~/ember
   ./coldboot.sh install --cache /media/matt/USB/coldboot-cache --dry-run
   ```
6. Run it for real:
   ```bash
   ./coldboot.sh install --cache /media/matt/USB/coldboot-cache
   ```
   Without the USB (internet only): `./coldboot.sh install`. Models then download
   from the internet (~10 GB).
7. If it printed "Sudo steps written to ~/coldboot-sudo-steps.sh", read that file and
   run it: `bash ~/coldboot-sudo-steps.sh`.
8. Bring back Ember's users, chats and targets:
   ```bash
   ./coldboot.sh restore /media/matt/USB/backups/ember-coldboot-<newest>.tar.gz
   ```
   It checks every checksum first and keeps any file it replaces as `*.pre-restore-<date>`.
9. Open a new terminal, then verify (section 4).

Running `install` again is safe. It skips what is already there and backs up
any setting it changes as `*.bak-coldboot-<date>`.

---

## 3. What needs sudo

Only these. `install` never runs sudo. `./coldboot.sh install --system` prints them
and saves them to `~/coldboot-sudo-steps.sh`:

- `sudo apt install -y zstd curl git openssl sqlite3`
- `sudo loginctl enable-linger matt` (keeps Ember running with nobody logged in; often works without sudo)
- Firewall, only if ufw is on: `sudo ufw allow from 192.168.1.0/24 to any port 8600 proto tcp`
- Optional: the Goose desktop app, `sudo apt install ./goose_1.59.1_amd64.deb`
- Optional, only if there is **no** Nomad: Ollama as a system service
- If the Nomad model folder is root-owned, copying cached models into it

---

## 4. How to verify

```bash
cd ~/ember && ./coldboot.sh check
```

Every line should say PASS. WARN means "look at this", FAIL means "broken".
The last line counts them. Then try:

- `goose --version` shows 1.59.1
- `nomad-search "treat a minor burn"` shows sources
- `goose-lw "make /tmp/hi.txt containing hi"` asks before it runs anything
- Open Ember in a browser: `ember url` prints the address

---

## 5. Recreate the Ember admin

If you restored a backup, your users are back. Otherwise:

```bash
ember create-admin matt        # asks for a password (10+ characters)
```

Forgot the password: `ember reset-password matt`. List accounts: `ember list-users`.

---

## 6. After the rebuild

- **Radio and build hosts** (Mint, Zorin, Los Gatos): on each Linux host run
  `bash ~/ember/coldboot/buildhost/install-buildhost.sh --cache /media/USB/coldboot-cache` (or `--radio`/`--build`
  online), then run the `~/buildhost-sudo-steps.sh` it writes (serial-port group, udev rules, slicer library).
  On Windows run `coldboot\buildhost\install-buildhost.ps1` (needs internet). On the P1, `./coldboot.sh install
  --cache DIR` puts back CHIRP, the radio library and the parts library.

- Agent SSH key: make a new one (`~/agent-stack-backup/ssh/AGENT-SSH-KEY.md` explains how).
  Ember's saved target logins come back with the restore.
- GitHub push key (for Matt's helper only): make a new deploy key and add it on GitHub.
- Make a fresh backup: `./coldboot.sh backup --out /media/matt/USB/backups`.

---

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| `cache checksum failure` | A file on the USB is damaged. Re-run `coldboot cache` from a working P1, or install without `--cache` (internet). |
| `no Ollama on http://127.0.0.1:11434` | Nomad isn't running yet. Start Nomad, wait a minute, run `install` again. |
| `Qdrant ... MISSING` | Nomad's knowledge base is gone. Reinstall Nomad and let it re-index. Ember chat still works; "Knowledge" answers won't. |
| `model store ... not writable` | Run the line it added to `~/coldboot-sudo-steps.sh`. |
| A model shows FAIL in `check` | Run `install` again; it creates missing 4k models from their base model. |
| `ember.service not active` | `ember logs` shows why. `ember restart` to retry. |
| Browser warns about the certificate | Expected (self-signed). Accept it once. |
| `archive checksum does NOT match` | That backup is damaged or was changed. Use an older one. |
| `repo is at ... expects ~/ember` | Move the repo: `mv <path> ~/ember`. |

Recipes for the custom models: `coldboot/Modelfiles.md`. Model list: `coldboot/models.json`.
The older kit `~/agent-stack-backup` (with `rebuild.sh`) still works; ColdBoot also reads
its files when you run `coldboot cache`.
