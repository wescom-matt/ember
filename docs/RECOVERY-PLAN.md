# The P1 AI system: description and recovery plan

Written for Matt. Plain words, no expert knowledge needed.
Repo: https://github.com/wescom-matt/ember (private). This file: `docs/RECOVERY-PLAN.md`.
Step-by-step rebuild guide: [`COLDBOOT.md`](../COLDBOOT.md).

---

## Part 1. What the system is

### The computer
- **Lenovo ThinkPad P1** ("Nomad box"), hostname `think-pad-p1`, user `matt`.
- Home network address **192.168.1.177**.
- Ubuntu Linux, NVIDIA T1000 graphics card (4 GB), 500 GB disk.
- Everything runs on this one machine and works **without internet**.

### The layers, bottom to top

| Layer | What it does | Where |
|---|---|---|
| **Nomad** (Project Nomad) | The offline library: medical, repair, radio, outdoors and more. Runs in Docker. | `/opt/project-nomad` |
| **Qdrant** (part of Nomad) | The search index for the library. Collection `nomad_knowledge_base`, about 3.6 million passages. | `127.0.0.1:6333` (P1 only) |
| **Ollama** (part of Nomad) | Runs the AI models on the P1. | `127.0.0.1:11434` (P1 only) |
| **Models** | `qwen3.5-9b-4k` (main, can use tools), `llama3.2-4k` and `llama3.2-1b-4k` (small, fast), `nomic-embed-text:v1.5` (used by the library search). The "4k" models are copies of `qwen3.5:9b`, `llama3.2` and `llama3.2:1b` with a smaller memory window so they fit the 4 GB card. Extras: `gemma4:26b`, `llama3.1:8b`. | Nomad's model folder |
| **nomad-search** | A small tool that searches the library and returns sources. Also plugs into Goose. | `~/agent-stack/nomad-search`, command `nomad-search "question"` |
| **Goose 1.59.1** | A terminal AI agent. Set to **ask before every action**. | command `goose` |
| **goose-lw** | Goose in two steps: one model writes a plan, then a worker carries it out, asking before each command. | command `goose-lw "task"` |
| **ai-interp** | Open Interpreter with the local Nomad profile. Asks before running any code. | command `ai-interp` |
| **Ember** | The web chat app, like Grok Bot but offline. Used from any browser on the home network. | `~/ember`, **https://192.168.1.177:8600** |
| **ColdBoot** | The rebuild, backup and restore tool for all of the above (except Nomad itself). | `~/ember/coldboot.sh` |

### Ember in more detail

**Phase 1, chat (0.1.0)**
- Logins with passwords. Admins add users; there is no public sign-up.
- Each person's chats are saved and private. You can rename, delete and search them.
- Replies stream in as they are written. You can pick the model.
- Pick **Nomad** as the knowledge base to get answers with sources from the library.
- Code is highlighted and has a Copy button. Think mode for models that support it.

**Phase 2, running commands (0.2.0)**
- Ember can run commands on the P1 itself, and over SSH on other computers (Linux or Windows).
- An admin must turn on the **master switch** ("Command running"). It is off by default.
- Admins add **targets** (computers) and **credentials** (an SSH key Ember makes, or a password). Credentials are stored encrypted.
- In a chat, tick **Commands** and pick a target. Simple read-only commands run on their own. Anything risky (deleting, formatting, sudo, installing, shutting down, flashing, writing outside the home folder, or anything unknown) shows a card and waits for you to click **Run** or **Cancel**.
- Every command, login and admin change goes into the **audit log**.
- Limits: up to 4 commands per reply, 2 minutes each, output trimmed.

**Phase 3, ColdBoot (0.3.0)**
- `./coldboot.sh check`: tells you if every part is healthy.
- `./coldboot.sh install`: rebuilds everything that is missing. It is safe to run any time.
- `./coldboot.sh backup` / `restore`: saves and brings back Ember's data.
- `./coldboot.sh cache`: puts everything needed for an offline rebuild on a USB disk.

**Phase 3b, workshop (0.4.0)**
- Ember's main jobs are now radio programming, code/build/flash, the 3D printer, and installing and fixing computers. Chat still works.
- **Hosts:** each computer gets roles (radio, build, printer). You pick which one is the active radio or build host (Workshop → Hosts), for everyone or one chat.
- **Radios:** CHIRP on the radio host. Always backs up first, shows a diff, and asks before uploading. Works for the Baofengs; the AnyTone D868UV and Kenwood TK-271 aren't supported by CHIRP; the IC-7300 is read-only.
- **Radio library:** band plan, FCC rules and channel lists, offline, with sources.
- **Printer:** ELEGOO Centauri Carbon 2 on the LAN (LAN-only mode + access code). Status and pause run straight away; start, resume, cancel and upload ask first. Slicing runs offline on the build host.
- **Parts library:** openly licensed 3D models and iFixit repair guides on the P1. Search, slice, send to the printer.
- **Fixing:** reads logs, edits config files (shows a diff and keeps a `.bak-ember` copy), restarts services, installs packages; risky steps always ask.
- **Safety line:** no autonomous weapon targeting or firing code.

### Important files

| File | Why it matters |
|---|---|
| `~/.local/share/ember/ember.db` | All Ember users, chats, targets, saved logins (encrypted) and the audit log |
| `~/.config/ember/secret.key` | The key that unlocks the saved logins. **Never share it.** |
| `~/.config/ember/ember.env` | Ember settings (port, model). No secrets. |
| `~/.config/ember/tls/` | Ember's web certificate |
| `~/.config/goose/config.yaml` | Goose settings |
| `~/AI-AGENTS-README.md` | Short how-to for the agents on the P1 |
| `~/agent-stack-backup/` | The older rebuild kit (still works) |

---

## Part 2. The USB disk: your insurance

Keep one **32 GB USB disk** (64 GB if you add the Arduino core) in a drawer. Refresh it after big changes, and at least every few months.

On the P1, with the USB plugged in (it appears as something like `/media/matt/USB`):

```bash
cd ~/ember
./coldboot.sh cache  /media/matt/USB/coldboot-cache     # about 19 GB, 20-40 minutes
./coldboot.sh backup --out /media/matt/USB/backups      # a few MB, do this often
```

What ends up on it:
- `coldboot-cache/`: the AI models (~10 GB), Ollama, Goose, Python packages, the build and radio tools (~5.4 GB), the parts library and radio library, a full copy of the Ember repo (`ember.bundle`), the guide, and checksums for everything.
- `backups/ember-coldboot-<date>.tar.gz` and its `.sha256` file: Ember's database and secret key.

> **The backup holds Ember's secret key.** Anyone who has it can read the saved SSH
> passwords and keys. Do not email it, upload it, or leave copies lying around.

Not on the USB, on purpose: your SSH keys, the GitHub key and passwords. You make new ones after a rebuild.

Also keep Nomad's own installer and library files, the way you set Nomad up originally.

---

## Part 3. What to do when something breaks

Always start with:

```bash
cd ~/ember && ./coldboot.sh check
```

PASS = fine, WARN = have a look, FAIL = broken. The FAIL lines tell you which part.

### Scenario A: Ember is broken but the P1 is fine

1. `ember status` and `ember logs` show what's wrong.
2. Try `ember restart`.
3. Still broken: `cd ~/ember && ./coldboot.sh install`. It repairs Ember without touching your data.
4. Data damaged or lost: `./coldboot.sh restore /media/matt/USB/backups/<newest>.tar.gz`.
5. Run `./coldboot.sh check` again.

### Scenario B: Ubuntu reinstalled on the same P1 (disk wiped)

1. Install Ubuntu with the user `matt`. Connect to the home network.
2. Reinstall Nomad (Part 3, scenario C).
3. `sudo apt install -y git curl zstd openssl sqlite3`
4. `git clone /media/matt/USB/coldboot-cache/ember.bundle ~/ember`
5. `cd ~/ember && ./coldboot.sh install --cache /media/matt/USB/coldboot-cache --dry-run` (just shows the plan)
6. `./coldboot.sh install --cache /media/matt/USB/coldboot-cache`
7. If it says so, run `bash ~/coldboot-sudo-steps.sh`.
8. `./coldboot.sh restore /media/matt/USB/backups/<newest>.tar.gz`
9. Open a new terminal, then run `./coldboot.sh check`.

### Scenario C: Nomad needs reinstalling

1. Reinstall Nomad the way you did originally. Let it re-index the library. This can take hours; leave it alone while it works.
2. Nomad brings Ollama and Qdrant back. The models may need restoring: run
   `cd ~/ember && ./coldboot.sh install --cache /media/matt/USB/coldboot-cache`.
   It copies missing models from the USB and rebuilds the 4k models.
3. `./coldboot.sh check` should show the Qdrant line as PASS.

ColdBoot never changes Nomad's data. If the Qdrant line says MISSING, Nomad's library needs re-indexing.

### Scenario D: The P1 is dead (new or different computer)

- Any x86_64 Linux PC with an NVIDIA card works. More graphics memory is better. Ubuntu is easiest.
- Follow Scenario B on the new machine.
- Different address on the network? Ember's certificate was made for the old address, so the browser will warn you. That's expected; accept it once. Then use `ember url` for the new address.
- If the old P1's disk still works, copy `~/.local/share/ember/ember.db` and `~/.config/ember/secret.key` off it. That's as good as a backup.

### Scenario E: `secret.key` is lost (but the database is fine)

- Users, chats and the audit log still work.
- **Saved logins (SSH keys and passwords for targets) can't be unlocked.** That is by design.
- Fix it:
  1. Keep the database. Restart Ember with `ember restart`. When it finds no key file, it makes a new one by itself.
  2. In Ember, go to **Users & admin → Targets & credentials** and delete the old credentials (they can't be unlocked any more).
  3. Make new ones and put the new public keys on the target computers (Part 4).

---

## Part 4. After any rebuild

### Make the admin account
If you restored a backup, your accounts are back. If not:

```bash
ember create-admin matt       # asks for a password, 10+ characters
```

Forgot the password: `ember reset-password matt`. List accounts: `ember list-users`.

### Radio, build and printer hosts

Run `coldboot/buildhost/install-buildhost.sh` on each Linux radio/build host (offline with `--cache`), then the sudo steps file it writes. Re-add the printer target (LAN IP + access code) if the database wasn't restored.

### Re-add targets and SSH keys (only if not restored)
1. In Ember: **Users & admin → Targets & credentials**. Turn on **Command running**.
2. Add a credential and choose **Generate SSH key**. Click **Copy public key**.
3. On the other computer, add that key as one line to `~/.ssh/authorized_keys` (Windows: `C:\Users\<you>\.ssh\authorized_keys`). Use a normal account, never root.
4. Add the target (host, user, Linux or Windows, that credential) and click **Test**.
5. For the P1 itself, add a target of type **This computer**. No key is needed.

### The agent's own SSH key (for Goose / Open Interpreter)
Make a new one: `ssh-keygen -t ed25519 -N "" -C "nomad-agent@$(hostname)" -f ~/.ssh/agent_ed25519`.
Put only the `.pub` file on limited accounts. Details: `~/agent-stack-backup/ssh/AGENT-SSH-KEY.md`.

### Check everything
- `./coldboot.sh check` shows no FAIL.
- `goose --version` shows 1.59.1.
- `nomad-search "treat a minor burn"` shows sources.
- Open Ember in the browser, log in and ask a question with the Nomad knowledge base.
- Make a fresh backup to the USB.

---

## Part 5. Later: Tailscale (remote access)

Tailscale is not installed yet. A local helper is setting it up. When it is:
- Ember stays on the home network address; Tailscale just gives a private route to it from away.
- Until then, use an SSH tunnel from a computer that can reach the P1:
  `ssh -L 8600:127.0.0.1:8600 matt@192.168.1.177`, then open `https://localhost:8600`.
- After a rebuild, Tailscale must be installed and logged in again (it needs sudo and your Tailscale account). Nothing in ColdBoot touches it.

---

## Quick card

| I want to... | Command |
|---|---|
| See if everything works | `cd ~/ember && ./coldboot.sh check` |
| Fix missing parts | `./coldboot.sh install` |
| Back up Ember | `./coldboot.sh backup --out /media/matt/USB/backups` |
| Restore Ember | `./coldboot.sh restore <file>.tar.gz` |
| Refresh the USB cache | `./coldboot.sh cache /media/matt/USB/coldboot-cache` |
| Restart Ember | `ember restart` |
| Ember's address | `ember url` |
| See the sudo steps | `./coldboot.sh install --system` |
