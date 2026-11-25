# Nomad AI agents on the P1

Two local agents are installed in your user account. They talk to the
Ollama already running on this laptop (`http://127.0.0.1:11434`) and
default to **qwen3.5:9b**, which is the best of your models at calling
tools. They stay **offline** and **ask before running any command**.

They can also search the Nomad knowledge base through `nomad-search`
(and the Goose `search_knowledge` tool). That index is local and
read-only: medicine, first aid, repair, DIY, ham radio, and more.

Do not start, stop, or reconfigure Ollama or the Nomad containers
unless you mean to. The search tool itself only reads Qdrant.

## How to launch

On the P1 itself, open a terminal and run:

```bash
nomad-search "how do I treat a minor burn"   # search the knowledge base
ai-interp          # Open Interpreter (recommended wrapper)
interpreter        # same defaults via the default profile
goose              # Goose CLI (can call search_knowledge)
goose-lw "task"    # lead/worker: Qwen plans, Qwen carries out, approval on
```

From Los Gatos (you need `-t` so approval prompts work):

```bash
ssh -t matt@192.168.1.177 'export PATH="$HOME/.local/bin:$PATH"; nomad-search "how do I treat a minor burn"'
ssh -t matt@192.168.1.177 'export PATH="$HOME/.local/bin:$PATH"; ai-interp'
ssh -t matt@192.168.1.177 'export PATH="$HOME/.local/bin:$PATH"; interpreter'
ssh -t matt@192.168.1.177 'export PATH="$HOME/.local/bin:$PATH"; goose'
```

### Access: CLI, desktop app, optional web UI

- **Open Interpreter** is a terminal chat. Optional built-in server (not
  started for you): `interpreter --server`. That gives a local web UI;
  only use it on the P1 or a trusted LAN. For factual questions it should
  run `nomad-search "..."`, and you still approve that command.
- **Goose CLI** is also terminal chat (`goose`, then talk). Ask a factual
  question and it should call the `search_knowledge` tool.
- **Goose desktop** is a Linux app. The installer is already in
  `~/Downloads` but needs your password:

```bash
sudo apt install ./Downloads/goose_1.59.1_amd64.deb
```

After that, launch "Goose" from the app menu. It uses the same config
as the CLI (`~/.config/goose/config.yaml`).

## How to switch models

Your installed chat models:

- `qwen3.5:9b` / `qwen3.5-9b-4k` (default, best at tool calling)
- `llama3.1:8b`
- `llama3.2:latest` / `llama3.2-4k` (fastest, weakest at multi-step work)
- `gemma4:26b` (smartest, slowest)

Open Interpreter, one session:

```bash
ai-interp --model ollama/llama3.1:8b
```

Or edit `~/.config/Open Interpreter/profiles/default.yaml` and
`~/.config/Open Interpreter/profiles/nomad.py` (change the `model`
line). The name must stay in `ollama/<model>` form.

Goose, one session:

```bash
GOOSE_MODEL=llama3.1:8b goose
```

Or inside a Goose session, use `/model`. To change the default, edit
`GOOSE_MODEL` in `~/.config/goose/config.yaml`.

The 4 GB GPU may already be holding `nomic-embed-text:v1.5` after a
knowledge search (about 320 MiB). A 9B or 26B chat model may still run
on CPU/RAM, which is slower. After a heavy session, if something looks
stalled, you can reload the embedder without restarting Ollama:

```bash
curl -s http://127.0.0.1:11434/api/embed -d '{"model":"nomic-embed-text:v1.5","input":"warmup","keep_alive":"1h"}'
```

## Safety

- Approval is **on** by default. You will be asked before any shell
  command or file change. Do not pass `interpreter -y` / `--auto_run`,
  and do not set `GOOSE_MODE: auto`, unless you really mean it.
  `nomad-search` itself is read-only (no writes to Qdrant or Nomad).
- A dedicated SSH key was created at `~/.ssh/agent_ed25519` (no
  passphrase). Install **only the public key** (`~/.ssh/agent_ed25519.pub`)
  on a limited, non-root account on target hosts. Do not put it in
  `root` authorized_keys and do not use your personal key for the agent.
  Example, from the P1, once you have chosen a limited user on a host:

```bash
ssh-copy-id -i ~/.ssh/agent_ed25519.pub limiteduser@that-host
```

  Then tell the agent to use that key, for example:

```bash
ssh -i ~/.ssh/agent_ed25519 limiteduser@that-host
```

- These tools can run any command you approve. Stay at the keyboard.

## Where things live

- Open Interpreter 0.4.3: `~/.local/bin/interpreter` (uv tool, Python 3.12)
- Wrapper: `~/.local/bin/ai-interp`
- Goose CLI 1.59.1: `~/.local/bin/goose` (lead/worker wrapper: `~/.local/bin/goose-lw`)
- Goose desktop package: `~/Downloads/goose_1.59.1_amd64.deb`
- uv / Python 3.12: `~/.local/bin/uv`, `~/.local/bin/python3.12`
- Nomad search: `~/agent-stack/nomad-search`, commands `nomad-search` and `nomad-search-mcp`
- Agent SSH key: `~/.ssh/agent_ed25519` and `.pub`

The system Python is 3.14 and has no pip; do not install these tools
with it. Use the uv-managed 3.12 environment already set up.

The official Goose install script (`download_cli.sh`) failed because
this Ubuntu image has no `bzip2`. The CLI was installed from the
matching official `.tar.gz` instead. To update Goose later, either
`sudo apt install bzip2` and rerun the official script, or download
the latest `goose-x86_64-unknown-linux-gnu.tar.gz` from
https://github.com/block/goose/releases and copy the `goose` binary
to `~/.local/bin/goose`.

## Lead/worker mode (added Nov 18 2026, worker fix Nov 25 2026)

`goose-lw` splits a job between two models and keeps approval ON:

- **Lead / planner: `qwen3.5-9b-4k`**. Writes a short numbered plan. It runs in
  Goose "chat" mode, so it has no tools and cannot run anything.
- **Worker: `qwen3.5-9b-4k`**. Carries out the plan in a normal Goose
  session. You approve every command and file change (Allow / Deny).

Llama 3.2 is no longer the default worker. In testing it did the first
step correctly, then only printed the next command as text instead of
running it. Qwen 3.5 9B is the model that reliably calls tools. You can
still try Llama with `WORKER=llama3.2-4k goose-lw "..."`.

```bash
goose-lw "make a folder ~/notes and put a file todo.txt in it"
LEAD=llama3.1:8b goose-lw "..."      # other models if you like
WORKER=llama3.2-4k goose-lw "..."    # old worker, often prints instead of running
GOOSE_LW_PLAN_ONLY=1 goose-lw "..."  # just show the plan
```

It shows the plan and asks before handing it to the worker. If the worker gets
confused, type `/model` in the session and switch to `qwen3.5-9b-4k`.

Why a wrapper: Goose 1.59.1 removed the old `GOOSE_LEAD_MODEL` setting, and
its built-in subagents only run in auto mode (no approvals). `config.yaml` also
has `GOOSE_SUBAGENT_MODEL: qwen3.5-9b-4k`, but it does nothing while
`GOOSE_MODE: approve` is on, which is intentional. Old config backup:
`~/.config/goose/config.yaml.bak-20261118-pre-leadworker`.

## Offline rebuild kit

`~/agent-stack-backup/` holds everything needed to reinstall this stack with
no internet. Start with `REBUILD.md`, then run `rebuild.sh`. Model files stay in
Nomad's store; use `export-models.sh` to copy them to a backup drive.
The knowledge-search tool is in `nomad-search/` (stdlib only, no wheels).
