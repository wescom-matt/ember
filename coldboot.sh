#!/usr/bin/env bash
# ColdBoot: rebuild the P1 agent stack and Ember from this repo (+ optional offline cache).
# Plain guide: COLDBOOT.md.  Runs as your normal user; sudo steps are only ever printed.
#
#   ./coldboot.sh check                      is everything healthy?
#   ./coldboot.sh install [--cache DIR] [--dry-run]
#   ./coldboot.sh install --system           print/write the few steps that need sudo
#   ./coldboot.sh install --build-host [--cache DIR] [--radio|--build]   radio/build host tools
#   ./coldboot.sh backup [--out DIR]         Ember DB + secret key + configs -> .tar.gz + SHA256SUMS
#   ./coldboot.sh restore ARCHIVE [--to DIR] [--dry-run] [--yes]
#   ./coldboot.sh cache DIR [--skip-models] [--skip-buildtools] [--only-buildtools]
#                     [--skip-projects] [--only-projects]    (projects: repos, toolchains, wheels, npm, NuGet)
#                     [--with-arduino-core] [--parts-gb N]   fill an offline cache (USB disk)
set -euo pipefail
umask 022

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CB="$REPO/coldboot"
STACK="$CB/stack"
SPEC="$CB/models.json"
PINS="$CB/pins.txt"
BIN="$HOME/.local/bin"
KIT="${COLDBOOT_KIT:-$HOME/agent-stack-backup}"
QDRANT_URL="${COLDBOOT_QDRANT_URL:-http://127.0.0.1:6333}"
OLLAMA_URL="${COLDBOOT_OLLAMA_URL:-http://127.0.0.1:11434}"
NOMAD_STORE="/opt/project-nomad/storage/ollama/models"
SUDO_FILE="$HOME/coldboot-sudo-steps.sh"
STAMP="$(date +%Y%m%d-%H%M%S)"
GOOSE_VERSION="1.59.1"
OLLAMA_VERSION="0.40.14"
OI_VERSION="0.4.3"
PY_VERSION="3.12"
MAX_ARCHIVE_FILES=200
DRY=0
CACHE=""
WITH_ARDUINO_CORE=""
PARTS_GB="3"
SUDO_LINES=()
N_PASS=0
N_WARN=0
N_FAIL=0
export PATH="$BIN:$PATH"
export COLDBOOT_OLLAMA_URL="$OLLAMA_URL"

# ---------- output helpers ----------
say()  { printf '\n=== %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
pass() { printf '  PASS  %s\n' "$*"; N_PASS=$((N_PASS + 1)); }
warn() { printf '  WARN  %s\n' "$*"; N_WARN=$((N_WARN + 1)); }
fail() { printf '  FAIL  %s\n' "$*"; N_FAIL=$((N_FAIL + 1)); }
die()  { printf 'coldboot: %s\n' "$*" >&2; exit 1; }
sudo_step() { SUDO_LINES+=("$1"); }

# Temp dirs live under one private scratch dir that is removed on exit.
SCRATCH=""
cleanup() { if [[ -n "$SCRATCH" ]]; then rm -rf "$SCRATCH"; fi; }
trap cleanup EXIT
# SCRATCH is created once in main(), so subshells calling scratch_dir share it.
scratch_dir() { mktemp -d -p "$SCRATCH"; }

# act "what" cmd args...  -> runs the command, or only describes it with --dry-run.
act() {
  local what="$1"
  shift
  if [[ "$DRY" == "1" ]]; then
    info "[dry-run] would: $what"
    return 0
  fi
  info "$what"
  "$@"
}

append_file() { cat "$1" >> "$2"; }
copy_tree() { mkdir -p "$(dirname "$2")" && cp -a "$1" "$2"; }
have() { command -v "$1" >/dev/null 2>&1; }
sha_of() { sha256sum "$1" | cut -c1-64; }
http_ok() { curl -fsS --max-time "${2:-5}" "$1" >/dev/null 2>&1; }

# ---------- files ----------
# put_file SRC DEST MODE: install a file; keep a dated backup of a different existing one.
put_file() {
  local src="$1" dest="$2" mode="$3"
  if [[ -f "$dest" ]] && cmp -s "$src" "$dest"; then
    info "unchanged: ${dest/#$HOME/~}"
    return 0
  fi
  if [[ -e "$dest" ]]; then
    act "back up ${dest/#$HOME/~} -> .bak-coldboot-$STAMP" cp -p "$dest" "$dest.bak-coldboot-$STAMP"
  fi
  act "install ${dest/#$HOME/~}" install -D -m "$mode" "$src" "$dest"
}

# put_template SRC DEST MODE: like put_file, with __HOME__ replaced by $HOME.
put_template() {
  local tmp
  tmp="$(mktemp)"
  sed "s|__HOME__|$HOME|g" "$1" > "$tmp"
  put_file "$tmp" "$2" "$3"
  rm -f "$tmp"
}

# ---------- pinned downloads ----------
pin_field() { awk -v n="$1" -v f="$2" '$1 == n { print $f; exit }' "$PINS"; }

# find_pinned NAME -> path of a verified copy (cache, then old kit), or nothing.
find_pinned() {
  local rel sha dir
  rel="$(pin_field "$1" 3)"
  sha="$(pin_field "$1" 2)"
  [[ -n "$rel" ]] || die "no pin named $1"
  for dir in "$CACHE" "$KIT"; do
    if [[ -n "$dir" && -f "$dir/$rel" ]]; then
      if [[ "$(sha_of "$dir/$rel")" == "$sha" ]]; then
        echo "$dir/$rel"
        return 0
      fi
      printf '  WARN  checksum mismatch, ignoring %s\n' "$dir/$rel" >&2
    fi
  done
  return 0
}

# download_pinned NAME DEST: https only, sha256 must match the pin.
download_pinned() {
  local url sha
  url="$(pin_field "$1" 4)"
  sha="$(pin_field "$1" 2)"
  [[ -n "$url" && "$url" != "-" ]] || return 1
  info "downloading $url"
  install -d "$(dirname "$2")"
  curl -fL --proto '=https' --tlsv1.2 --max-time 3600 -o "$2.part" "$url" || return 1
  if [[ "$(sha_of "$2.part")" != "$sha" ]]; then
    rm -f "$2.part"
    die "checksum mismatch for $url (expected $sha)"
  fi
  mv "$2.part" "$2"
}

# get_pinned NAME -> verified local path; downloads to a temp dir if not cached.
get_pinned() {
  local found tmp
  found="$(find_pinned "$1")"
  if [[ -n "$found" ]]; then echo "$found"; return 0; fi
  tmp="$(scratch_dir)/$(basename "$(pin_field "$1" 3)")"
  download_pinned "$1" "$tmp" >&2 || return 1
  echo "$tmp"
}

# ---------- install steps (user level, no sudo) ----------
step_preflight() {
  say "0. Preflight"
  [[ "$(uname -m)" == "x86_64" ]] || die "x86_64 Linux only"
  [[ "$EUID" -ne 0 ]] || die "run as your normal user, not root"
  local tool missing=()
  for tool in curl tar sha256sum python3 openssl systemctl git cmp; do
    have "$tool" || missing+=("$tool")
  done
  [[ ${#missing[@]} -eq 0 ]] || die "missing tools: ${missing[*]} (sudo apt install ${missing[*]})"
  if ! have zstd; then
    warn "zstd missing (needed to unpack Python/Ollama from the cache)"
    sudo_step "sudo apt install -y zstd"
  fi
  if [[ -n "$CACHE" ]]; then
    [[ -f "$CACHE/SHA256SUMS" ]] || die "no SHA256SUMS in cache $CACHE"
    info "verifying cache checksums (large files take a minute)..."
    (cd "$CACHE" && sha256sum -c --quiet --strict SHA256SUMS) || die "cache checksum failure in $CACHE"
    info "cache OK: $CACHE"
  fi
  [[ "$REPO" == "$HOME/ember" ]] || warn "repo is at $REPO; Ember's service expects $HOME/ember"
}

step_uv() {
  say "1. uv"
  if have uv; then info "present: $(uv --version)"; return 0; fi
  local src
  src="$(find_pinned uv)"
  if [[ -n "$src" ]]; then
    act "install uv + uvx from $(dirname "$src")" install -m 755 "$src" "$(dirname "$src")/uvx" "$BIN/"
    return 0
  fi
  [[ "$DRY" == "0" ]] || { info "[dry-run] would download uv (no cache)"; return 0; }
  install_uv_online
}

install_uv_online() {
  local tmp url="https://github.com/astral-sh/uv/releases/download/0.13.8/uv-x86_64-unknown-linux-gnu.tar.gz"
  tmp="$(scratch_dir)"
  curl -fL --proto '=https' --max-time 600 -o "$tmp/uv.tgz" "$url"
  curl -fL --proto '=https' --max-time 60 -o "$tmp/uv.sha" "$url.sha256"
  [[ "$(sha_of "$tmp/uv.tgz")" == "$(cut -c1-64 "$tmp/uv.sha")" ]] || die "uv checksum mismatch"
  tar -C "$tmp" -xzf "$tmp/uv.tgz"
  install -D -m 755 "$tmp/uv-x86_64-unknown-linux-gnu/uv" "$tmp/uv-x86_64-unknown-linux-gnu/uvx" -t "$BIN"
  rm -rf "$tmp"
}

step_python() {
  say "2. Python $PY_VERSION (uv-managed)"
  local py=""
  if [[ -x "$BIN/python$PY_VERSION" ]]; then
    info "present: $BIN/python$PY_VERSION"
    return 0
  fi
  if have uv; then py="$(find_managed_python)"; fi
  if [[ -z "$py" ]]; then
    local tarball
    tarball="$(find_pinned cpython)"
    if [[ -n "$tarball" ]]; then
      act "unpack $(basename "$tarball")" unpack_python "$tarball"
    else
      act "download Python $PY_VERSION with uv" uv python install "$PY_VERSION"
    fi
    [[ "$DRY" == "1" ]] || py="$(find_managed_python)"
  fi
  info "python: ${py:-<after install>}"
  if [[ -n "$py" && ! -x "$BIN/python$PY_VERSION" ]]; then
    act "link $BIN/python$PY_VERSION" ln -sfn "$py" "$BIN/python$PY_VERSION"
  fi
}

find_managed_python() {
  uv python find --no-cache --no-project --managed-python "$PY_VERSION" 2>/dev/null || true
}

unpack_python() {
  local dest="$HOME/.local/share/uv/python" dir
  dir="$dest/$(basename "$1" .tar.zst)"
  install -d "$dest"
  zstd -dc "$1" | tar -C "$dest" -xf -
  ln -sfn "$dir" "$dest/cpython-$PY_VERSION-linux-x86_64-gnu"
  ln -sfn "$dir/bin/python$PY_VERSION" "$BIN/python$PY_VERSION"
}

step_ollama() {
  say "3. Ollama"
  local version
  version="$(curl -fsS --max-time 5 "$OLLAMA_URL/api/version" 2>/dev/null || true)"
  if [[ -n "$version" ]]; then
    info "answering on $OLLAMA_URL: $version (Nomad's container provides it; left alone)"
    [[ "$version" == *"$OLLAMA_VERSION"* ]] || warn "Ollama version differs from $OLLAMA_VERSION"
    return 0
  fi
  warn "no Ollama on $OLLAMA_URL. Install Nomad first (it brings Ollama), then re-run."
  if [[ -x "$BIN/ollama" ]]; then info "user-space ollama already at $BIN/ollama"; return 0; fi
  local tarball
  tarball="$(find_pinned ollama)"
  if [[ -n "$tarball" ]]; then
    act "unpack user-space Ollama $OLLAMA_VERSION to ~/.local/ollama" unpack_ollama "$tarball"
    info "Without Nomad, start it with:  ollama serve &   (or the system service in: coldboot install --system)"
  else
    info "no cached Ollama; 'coldboot cache' or install Nomad"
  fi
}

unpack_ollama() {
  install -d "$HOME/.local/ollama"
  zstd -dc "$1" | tar -C "$HOME/.local/ollama" -xf -
  ln -sfn "$HOME/.local/ollama/bin/ollama" "$BIN/ollama"
}

model_store() {
  if [[ -n "${COLDBOOT_OLLAMA_STORE:-}" ]]; then echo "$COLDBOOT_OLLAMA_STORE"
  elif [[ -d "$NOMAD_STORE" ]]; then echo "$NOMAD_STORE"
  else echo "$HOME/.ollama/models"; fi
}

step_models() {
  say "4. Ollama models"
  if ! http_ok "$OLLAMA_URL/api/version"; then
    warn "Ollama not running; skipping models (re-run after Ollama is up)"
    return 0
  fi
  local missing
  missing="$(python3 "$CB/cbmodels.py" missing --spec "$SPEC")" || die "could not list models"
  if [[ -z "$missing" ]]; then info "all models present"; return 0; fi
  info "missing: $(echo "$missing" | awk '{print $2}' | tr '\n' ' ')"
  import_cached_models
  missing="$(python3 "$CB/cbmodels.py" missing --spec "$SPEC")"
  local kind name
  while read -r kind name; do
    [[ -n "$kind" ]] || continue
    if [[ "$kind" == "base" ]]; then
      act "pull $name (internet)" python3 "$CB/cbmodels.py" pull "$name" || warn "pull $name failed"
    fi
  done <<< "$missing"
  while read -r kind name; do
    if [[ "$kind" == "custom" ]]; then
      act "create $name" python3 "$CB/cbmodels.py" create --spec "$SPEC" "$name" || warn "create $name failed"
    fi
  done <<< "$missing"
}

import_cached_models() {
  [[ -n "$CACHE" && -d "$CACHE/models/manifests" ]] || return 0
  local store
  store="$(model_store)"
  if [[ -w "$store" || ( ! -e "$store" && -w "$(dirname "$store")" ) ]]; then
    act "copy cached models into $store" python3 "$CB/cbmodels.py" import --src "$CACHE/models" --store "$store"
  else
    warn "model store $store is not writable by you"
    sudo_step "sudo python3 '$CB/cbmodels.py' import --src '$CACHE/models' --store '$store'"
  fi
}

step_goose() {
  say "5. Goose CLI $GOOSE_VERSION"
  if have goose && [[ "$(goose --version 2>/dev/null)" == *"$GOOSE_VERSION"* ]]; then
    info "present: goose $GOOSE_VERSION"
    return 0
  fi
  local bin
  bin="$(find_pinned goose)"
  if [[ -n "$bin" ]]; then
    act "install goose from $(dirname "$bin")" install -m 755 "$bin" "$BIN/goose"
  elif [[ "$DRY" == "1" ]]; then
    info "[dry-run] would download goose $GOOSE_VERSION (pinned sha256)"
  else
    install_goose_tarball
  fi
}

install_goose_tarball() {
  local tarball tmp
  tarball="$(get_pinned goose-tar)" || die "goose $GOOSE_VERSION not cached and download failed"
  tmp="$(scratch_dir)"
  tar -C "$tmp" -xjf "$tarball"
  install -m 755 "$(find "$tmp" -maxdepth 2 -type f -name goose | head -n 1)" "$BIN/goose"
  rm -rf "$tmp"
}

step_interpreter() {
  say "6. Open Interpreter $OI_VERSION"
  if [[ -x "$BIN/interpreter" ]]; then info "present: $BIN/interpreter"; return 0; fi
  local py lock="$STACK/requirements.lock.txt"
  py="$BIN/python$PY_VERSION"
  local wheels=""
  for dir in "$CACHE" "$KIT"; do
    if [[ -n "$dir" && -d "$dir/python/wheels" ]]; then wheels="$dir/python/wheels"; break; fi
  done
  if [[ -n "$wheels" ]]; then
    act "uv tool install open-interpreter (offline, $wheels)" env UV_OFFLINE=1 uv tool install --offline \
      --python "$py" --no-index --find-links "$wheels" --with-requirements "$lock" "open-interpreter==$OI_VERSION"
  else
    act "uv tool install open-interpreter (internet)" uv tool install --python "$py" \
      --with-requirements "$lock" "open-interpreter==$OI_VERSION"
  fi
}

step_configs() {
  say "7. Configs and wrappers (existing different files are backed up first)"
  local c="$STACK/configs" oi="$HOME/.config/Open Interpreter/profiles"
  put_template "$c/goose/config.yaml" "$HOME/.config/goose/config.yaml" 644
  put_file "$c/wrappers/goose-lw" "$BIN/goose-lw" 755
  put_file "$c/wrappers/ai-interp" "$BIN/ai-interp" 755
  put_file "$c/wrappers/env" "$BIN/env" 644
  put_file "$c/wrappers/env.fish" "$BIN/env.fish" 644
  put_file "$c/open-interpreter/nomad.py" "$oi/nomad.py" 644
  put_file "$c/open-interpreter/default.yaml" "$oi/default.yaml" 644
  put_file "$c/open-interpreter/default.yaml" "$HOME/.config/open-interpreter/profiles/default.yaml" 644
  put_file "$STACK/docs/AI-AGENTS-README.md" "$HOME/AI-AGENTS-README.md" 644
  if grep -q AI-AGENTS-PATH "$HOME/.bashrc" 2>/dev/null; then
    info "unchanged: ~/.bashrc PATH snippet"
  else
    act "add PATH snippet to ~/.bashrc" append_file "$c/wrappers/bashrc-snippet.sh" "$HOME/.bashrc"
  fi
}

nomad_search_same() {
  local dest="$1"
  [[ -d "$dest" && -x "$BIN/nomad-search" && -x "$BIN/nomad-search-mcp" ]] || return 1
  diff -rq --exclude=.venv --exclude=__pycache__ --exclude=bin --exclude=live-tests \
    "$STACK/nomad-search" "$dest" >/dev/null 2>&1
}

step_nomad_search() {
  say "8. nomad-search (+ Goose extension, configured in step 7)"
  local dest="$HOME/agent-stack/nomad-search"
  if nomad_search_same "$dest"; then info "present and matches repo: $dest"; return 0; fi
  if [[ -e "$dest" ]]; then
    act "move old copy to $dest.bak-coldboot-$STAMP" mv "$dest" "$dest.bak-coldboot-$STAMP"
  fi
  act "copy nomad-search to $dest" copy_tree "$STACK/nomad-search" "$dest"
  act "run nomad-search install.sh" env PYTHON="$BIN/python$PY_VERSION" bash "$dest/install.sh"
}

ember_current() {
  local stamp="$REPO/.venv/.coldboot-requirements.sha256"
  [[ -x "$REPO/.venv/bin/python" && -f "$stamp" ]] || return 1
  [[ "$(cat "$stamp")" == "$(sha_of "$REPO/requirements.txt")" ]] || return 1
  cmp -s "$REPO/deploy/ember.service" "$HOME/.config/systemd/user/ember.service" || return 1
  systemctl --user is-active --quiet ember.service
}

step_ember() {
  say "9. Ember (venv from hashed requirements, ember.service, linger)"
  if ember_current; then info "venv, unit and service are current"; return 0; fi
  local wheels=""
  if [[ -n "$CACHE" && -d "$CACHE/ember-wheels" ]]; then wheels="$CACHE/ember-wheels"; fi
  act "run install.sh${wheels:+ (offline wheels)}" env EMBER_WHEELS="$wheels" bash "$REPO/install.sh"
  [[ "$DRY" == "1" ]] || sha_of "$REPO/requirements.txt" > "$REPO/.venv/.coldboot-requirements.sha256"
}

step_radio_helper() {
  say "9b. CHIRP for Ember's radio helper, and the offline radio reference"
  local opts=(--chirp-only)
  if [[ -n "$CACHE" ]]; then opts+=(--cache "$CACHE"); fi
  if [[ "$DRY" == "1" ]]; then opts+=(--dry-run); fi
  bash "$CB/buildhost/install-buildhost.sh" "${opts[@]}" || warn "CHIRP helper install failed (radio screen will say so)"
  local parts_dir="$HOME/.local/share/ember/parts"
  if [[ ! -f "$parts_dir/library.db" && -n "$CACHE" && -f "$CACHE/parts/library.db" ]]; then
    act "copy parts library from cache" copy_tree "$CACHE/parts" "$parts_dir"
  fi
  local kb="$HOME/.local/share/ember/radio-kb"
  if [[ -f "$kb/index.db" ]]; then info "radio reference present"; return 0; fi
  if [[ -n "$CACHE" && -f "$CACHE/radio-kb/index.db" ]]; then
    act "copy radio reference from cache" copy_tree "$CACHE/radio-kb" "$kb"
  else
    info "radio reference not built: run '.venv/bin/python scripts/fetch_radio_kb.py' while online"
  fi
}

step_projects_restore() {
  say "9c. Project mirrors (~/git) and offline developer reference, from the cache"
  [[ -n "$CACHE" ]] || { info "no --cache: skipped"; return 0; }
  if [[ -d "$CACHE/repos" ]]; then
    act "import project mirrors into ~/git (never overwrites offline work)" bash "$REPO/scripts/import-mirrors.sh" "$CACHE/repos"
  fi
  local dk="$HOME/.local/share/ember/dev-kb"
  if [[ ! -f "$dk/index.db" && -f "$CACHE/dev-kb/index.db" ]]; then
    act "copy developer reference from cache" copy_tree "$CACHE/dev-kb" "$dk"
  fi
  if [[ -d "$CACHE/projects" ]]; then
    info "project caches: $CACHE/projects and $CACHE/buildhost/pio-envs (see README, Off-grid project work)"
  fi
}

step_nomad_check() {
  say "10. Nomad (reinstalled separately; read-only check)"
  check_qdrant
}

# ---------- the sudo part ----------
system_steps() {
  cat <<SUDO
#!/usr/bin/env bash
# ColdBoot steps that need sudo. Read each one; run only the ones you need.
# Run with:  bash $SUDO_FILE
set -euo pipefail

# 1. Tools ColdBoot uses (safe to re-run)
sudo apt install -y zstd curl git openssl sqlite3

# 2. Keep Ember running with nobody logged in (usually works without sudo too)
sudo loginctl enable-linger $USER

# 3. Firewall: let your home network reach Ember on port 8600 (only if ufw is active)
if sudo ufw status | grep -q 'Status: active'; then
  sudo ufw allow from 192.168.1.0/24 to any port 8600 proto tcp
fi

# 4. OPTIONAL Goose desktop app (needs the cache):
# sudo apt install ./CACHE/goose/goose_${GOOSE_VERSION}_amd64.deb

# 5. OPTIONAL system Ollama service. ONLY if this box has NO Nomad (Nomad brings its own Ollama):
# zstd -dc CACHE/ollama/ollama-linux-amd64.tar.zst | sudo tar -C /usr -xf -
# sudo useradd -r -s /bin/false -U -m -d /usr/share/ollama ollama
# sudo cp $STACK/ollama/ollama.service /etc/systemd/system/ollama.service
# sudo systemctl daemon-reload && sudo systemctl enable --now ollama
SUDO
  local line
  if [[ ${#SUDO_LINES[@]} -gt 0 ]]; then
    printf '\n# Found during this install run:\n'
    for line in "${SUDO_LINES[@]}"; do printf '%s\n' "$line"; done
  fi
}

write_system_steps() {
  if [[ "$DRY" == "1" ]]; then
    say "Sudo steps (dry-run: not written)"
    system_steps
    return 0
  fi
  system_steps > "$SUDO_FILE"
  chmod 700 "$SUDO_FILE"
  say "Sudo steps written to $SUDO_FILE"
  cat "$SUDO_FILE"
}

cmd_install() {
  local system=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --cache) CACHE="$(cd "${2:?--cache needs a dir}" && pwd)"; shift 2 ;;
      --dry-run) DRY=1; shift ;;
      --system) system=1; shift ;;
      --build-host) shift; exec bash "$CB/buildhost/install-buildhost.sh" ${CACHE:+--cache "$CACHE"} "$@" ;;
      *) die "install: unknown option $1" ;;
    esac
  done
  if [[ "$system" == "1" ]]; then write_system_steps; return 0; fi
  [[ "$DRY" == "0" ]] || say "DRY RUN: nothing will be changed"
  [[ "$DRY" == "1" ]] || install -d "$BIN"
  step_preflight
  step_uv
  step_python
  step_ollama
  step_models
  step_goose
  step_interpreter
  step_configs
  step_nomad_search
  step_ember
  step_radio_helper
  step_projects_restore
  step_nomad_check
  if [[ ${#SUDO_LINES[@]} -gt 0 ]]; then write_system_steps; fi
  say "Done. Next: ./coldboot.sh check   (open a new terminal first so PATH is fresh)"
}

# ---------- check ----------
check_qdrant() {
  local reply
  reply="$(curl -fsS --max-time 5 "$QDRANT_URL/collections/nomad_knowledge_base" 2>/dev/null || true)"
  if [[ -z "$reply" ]]; then
    fail "Qdrant at $QDRANT_URL or collection nomad_knowledge_base MISSING: reinstall Nomad and re-index its library"
    return 0
  fi
  local summary
  summary="$(printf '%s' "$reply" | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; print(r.get("status"), r.get("points_count"))')"
  if [[ "$summary" == green* ]]; then pass "Qdrant nomad_knowledge_base: $summary points"
  else warn "Qdrant nomad_knowledge_base: $summary"; fi
}

check_bins() {
  local b
  for b in uv "python$PY_VERSION" goose goose-lw ai-interp interpreter nomad-search nomad-search-mcp ember; do
    if [[ -x "$BIN/$b" ]] || have "$b"; then pass "command $b"; else fail "command $b missing"; fi
  done
  local gv
  gv="$(goose --version 2>/dev/null || true)"
  if [[ "$gv" == *"$GOOSE_VERSION"* ]]; then pass "goose version $GOOSE_VERSION"; else fail "goose version: ${gv:-none}"; fi
}

check_configs() {
  local g="$HOME/.config/goose/config.yaml"
  if grep -q '^GOOSE_MODE: approve' "$g" 2>/dev/null; then pass "goose approve mode"; else fail "goose config missing or not approve mode"; fi
  if grep -q 'nomad-search-mcp' "$g" 2>/dev/null; then pass "goose nomad-search extension"; else fail "goose nomad-search extension missing"; fi
  local tmp
  tmp="$(mktemp)"
  sed "s|__HOME__|$HOME|g" "$STACK/configs/goose/config.yaml" > "$tmp"
  cmp -s "$tmp" "$g" || warn "goose config differs from repo template (ok if you changed it on purpose)"
  rm -f "$tmp"
  local oi="$HOME/.config/Open Interpreter/profiles/nomad.py"
  if grep -q 'auto_run = False' "$oi" 2>/dev/null; then pass "Open Interpreter nomad profile (auto_run off)"
  else fail "Open Interpreter nomad profile missing"; fi
  if [[ -f "$HOME/AI-AGENTS-README.md" ]]; then pass "AI-AGENTS-README.md"; else warn "AI-AGENTS-README.md missing"; fi
  if nomad_search_same "$HOME/agent-stack/nomad-search"; then pass "nomad-search matches repo"
  else warn "nomad-search differs from repo copy or is missing"; fi
}

check_ollama() {
  local version
  version="$(curl -fsS --max-time 5 "$OLLAMA_URL/api/version" 2>/dev/null || true)"
  if [[ -z "$version" ]]; then fail "Ollama not answering on $OLLAMA_URL"; return 0; fi
  pass "Ollama $version"
  local line
  while read -r line; do
    case "$line" in
      PASS*) pass "${line#PASS }" ;;
      *) fail "${line#FAIL }" ;;
    esac
  done < <(python3 "$CB/cbmodels.py" check --spec "$SPEC" 2>&1 || true)
}

check_ember() {
  local conf="$HOME/.config/ember"
  if [[ -x "$REPO/.venv/bin/python" ]]; then pass "Ember venv"; else fail "Ember venv missing"; fi
  if systemctl --user is-active --quiet ember.service; then pass "ember.service active"; else fail "ember.service not active"; fi
  local port
  port="$(sed -n 's/^EMBER_PORT=//p' "$conf/ember.env" 2>/dev/null | head -n 1)"
  local ver
  ver="$(curl -fsSk --max-time 5 "https://127.0.0.1:${port:-8600}/api/version" 2>/dev/null || true)"
  if [[ -n "$ver" ]]; then pass "Ember answers: $ver"; else fail "Ember not answering on https://127.0.0.1:${port:-8600}"; fi
  check_mode "$conf/secret.key" "secret.key"
  check_mode "$conf/tls/ember.key" "TLS key"
  if [[ -f "$HOME/.local/share/ember/ember.db" ]]; then pass "ember.db"; else fail "ember.db missing"; fi
  if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || true)" == "yes" ]]; then pass "linger on"
  else warn "linger off (see: coldboot install --system)"; fi
  local users
  users="$(EMBER_HOME="$REPO" "$REPO/bin/ember" list-users 2>/dev/null | grep -c '[[:space:]]admin' || true)"
  if [[ "${users:-0}" -gt 0 ]]; then pass "Ember has an admin"; else warn "no Ember admin yet: run  ember create-admin matt"; fi
}

check_mode() {
  if [[ ! -f "$1" ]]; then fail "$2 missing"; return 0; fi
  if [[ "$(stat -c %a "$1")" == "600" ]]; then pass "$2 present, mode 600"; else fail "$2 mode is $(stat -c %a "$1"), want 600"; fi
}

cmd_check() {
  say "ColdBoot check ($(hostname), $(date '+%F %R %Z'))"
  check_bins
  check_configs
  check_ollama
  check_qdrant
  check_ember
  say "Result: $N_PASS pass, $N_WARN warn, $N_FAIL fail"
  [[ "$N_FAIL" -eq 0 ]]
}

# ---------- backup ----------
BACKUP_FILES=(
  ".config/ember/secret.key"
  ".config/ember/ember.env"
  ".config/ember/tls/ember.crt"
  ".config/ember/tls/ember.key"
  ".config/goose/config.yaml"
  ".config/Open Interpreter/profiles/nomad.py"
  ".config/Open Interpreter/profiles/default.yaml"
  ".local/bin/goose-lw"
  ".local/bin/ai-interp"
)
DB_REL=".local/share/ember/ember.db"

loud_warning() {
  cat <<'WARN'

  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  !!  THIS ARCHIVE CONTAINS EMBER'S SECRET KEY AND TLS PRIVATE KEY.   !!
  !!  Anyone with it can decrypt the saved SSH passwords/keys.        !!
  !!  Keep it OFFLINE (a USB stick in a drawer). Do not email it,     !!
  !!  upload it, or leave copies around.                              !!
  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
WARN
}

# safe online copy of a live SQLite database (WAL-aware), then an integrity check
sqlite_backup() {
  python3 - "$1" "$2" <<'PY'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
src.close(); dst.close()
sys.exit(0 if ok == "ok" else 1)
PY
}

write_manifest() {
  {
    echo "ColdBoot backup"
    echo "host: $(hostname)"
    echo "date: $(date '+%F %T %Z')"
    echo "ember: $(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$REPO/ember/__init__.py")"
    echo "commit: $(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    echo "restore: ./coldboot.sh restore <this archive>"
  } > "$1/MANIFEST.txt"
}

cmd_backup() {
  local out="$HOME/coldboot-backups"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --out) out="${2:?--out needs a dir}"; shift 2 ;;
      *) die "backup: unknown option $1" ;;
    esac
  done
  umask 077
  install -d -m 700 "$out"
  local stage rel archive
  stage="$(scratch_dir)"
  install -d "$stage/home"
  if [[ -f "$HOME/$DB_REL" ]]; then
    install -d "$stage/home/$(dirname "$DB_REL")"
    sqlite_backup "$HOME/$DB_REL" "$stage/home/$DB_REL" || die "database backup failed integrity check"
    info "ember.db (safe SQLite backup)"
  else
    warn "no ember.db at ~/$DB_REL"
  fi
  for rel in "${BACKUP_FILES[@]}"; do
    if [[ -f "$HOME/$rel" ]]; then
      install -d "$stage/home/$(dirname "$rel")"
      cp -p "$HOME/$rel" "$stage/home/$rel"
      info "$rel"
    else
      info "(not present: $rel)"
    fi
  done
  local extra
  for extra in "$HOME"/.local/share/ember/notes/*.md "$HOME/.local/share/ember/projects.json" \
    "$HOME/.local/share/ember/model-bench.json"; do
    [[ -f "$extra" ]] || continue
    rel="${extra#"$HOME/"}"
    install -d "$stage/home/$(dirname "$rel")"
    cp -p "$extra" "$stage/home/$rel"
    info "$rel"
  done
  write_manifest "$stage"
  (cd "$stage" && find home MANIFEST.txt -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
  archive="$out/ember-coldboot-$(hostname)-$STAMP.tar.gz"
  tar -C "$stage" -czf "$archive" SHA256SUMS MANIFEST.txt home
  chmod 600 "$archive"
  (cd "$out" && sha256sum "$(basename "$archive")" > "$(basename "$archive").sha256")
  say "Backup written: $archive"
  info "checksum: $archive.sha256"
  loud_warning
}

# ---------- restore ----------
# Refuse absolute paths, '..', links and anything outside the expected layout.
archive_is_safe() {
  local listing count
  listing="$(tar -tvzf "$1")" || return 1
  count="$(printf '%s\n' "$listing" | grep -c .)"
  [[ "$count" -le "$MAX_ARCHIVE_FILES" ]] || { echo "too many entries" >&2; return 1; }
  if printf '%s\n' "$listing" | grep -qv '^[-d]'; then echo "archive has links or special files" >&2; return 1; fi
  local name
  while IFS= read -r name; do
    case "$name" in
      /*|*../*|*/..|..) echo "unsafe path: $name" >&2; return 1 ;;
      SHA256SUMS|MANIFEST.txt|home|home/|home/*) ;;
      *) echo "unexpected entry: $name" >&2; return 1 ;;
    esac
  done < <(tar -tzf "$1")
}

verify_archive() {
  local archive="$1" dir="$2"
  if [[ -f "$archive.sha256" ]]; then
    [[ "$(sha_of "$archive")" == "$(cut -c1-64 "$archive.sha256")" ]] || die "archive checksum does NOT match $archive.sha256"
    info "archive checksum OK"
  else
    warn "no $archive.sha256 next to the archive; checking inner checksums only"
  fi
  archive_is_safe "$archive" || die "archive failed safety checks; not restoring"
  tar -C "$dir" --no-same-owner -xzf "$archive"
  (cd "$dir" && sha256sum -c --quiet --strict SHA256SUMS) || die "file checksums do NOT match; archive damaged or altered"
  local listed present
  listed="$(grep -c ' home/' "$dir/SHA256SUMS" || true)"
  present="$(find "$dir/home" -type f | grep -c . || true)"
  [[ "$listed" == "$present" ]] || die "archive has files not covered by SHA256SUMS"
  info "all $present file checksums OK"
}

restore_file() {
  local src="$1" dest="$2"
  if [[ -f "$dest" ]] && cmp -s "$src" "$dest"; then info "unchanged: $dest"; return 0; fi
  if [[ -e "$dest" ]]; then act "keep old copy $dest.pre-restore-$STAMP" mv "$dest" "$dest.pre-restore-$STAMP"; fi
  act "restore $dest" install -D -m "$(stat -c %a "$src")" "$src" "$dest"
}

cmd_restore() {
  local archive="" root="$HOME" yes=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --to) root="${2:?--to needs a dir}"; shift 2 ;;
      --dry-run) DRY=1; shift ;;
      --yes) yes=1; shift ;;
      -*) die "restore: unknown option $1" ;;
      *) archive="$1"; shift ;;
    esac
  done
  [[ -f "$archive" ]] || die "usage: coldboot restore ARCHIVE [--to DIR] [--dry-run] [--yes]"
  umask 077
  local tmp
  tmp="$(scratch_dir)"
  say "Verifying $archive"
  verify_archive "$archive" "$tmp"
  sed 's/^/    /' "$tmp/MANIFEST.txt"
  if [[ "$root" == "$HOME" && "$DRY" == "0" && "$yes" == "0" ]]; then
    read -r -p "Restore into your home ($HOME)? Existing files are kept as *.pre-restore-$STAMP. [y/N] " ok
    [[ "$ok" == "y" || "$ok" == "Y" ]] || die "cancelled"
  fi
  local was_running=0
  if [[ "$root" == "$HOME" ]] && systemctl --user is-active --quiet ember.service 2>/dev/null; then
    was_running=1
    act "stop ember.service" systemctl --user stop ember.service
  fi
  say "Restoring into $root"
  local f rel
  while IFS= read -r -d '' f; do
    rel="${f#"$tmp/home/"}"
    if [[ "$rel" == "$DB_REL" ]]; then
      for ext in -wal -shm; do
        if [[ -e "$root/$rel$ext" ]]; then
          act "set aside $root/$rel$ext" mv "$root/$rel$ext" "$root/$rel$ext.pre-restore-$STAMP"
        fi
      done
    fi
    restore_file "$f" "$root/$rel"
  done < <(find "$tmp/home" -type f -print0 | sort -z)
  if [[ "$was_running" == "1" ]]; then act "start ember.service" systemctl --user start ember.service; fi
  say "Restore finished"
  [[ "$DRY" == "0" ]] || info "(dry-run: nothing was changed)"
}

# ---------- offline cache ----------
cache_pinned() {
  local name="$1" dir="$2" rel src
  rel="$(pin_field "$name" 3)"
  if [[ -f "$dir/$rel" && "$(sha_of "$dir/$rel")" == "$(pin_field "$name" 2)" ]]; then info "have $rel"; return 0; fi
  src="$(CACHE="" find_pinned "$name")"
  if [[ -n "$src" ]]; then
    install -D -m 644 "$src" "$dir/$rel"
    info "copied $rel from kit"
  else
    download_pinned "$name" "$dir/$rel" || warn "could not get $rel (not in kit, no download URL or no internet)"
  fi
  case "$name" in uv|uvx|goose) chmod 755 "$dir/$rel" 2>/dev/null || true ;; esac
}

cache_python() {
  local dir="$1"
  install -D -m 644 "$STACK/requirements.lock.txt" "$dir/python/requirements.lock.txt"
  if [[ -d "$dir/python/wheels" ]] && compgen -G "$dir/python/wheels/*" >/dev/null; then info "have python/wheels"; return 0; fi
  install -d "$dir/python/wheels"
  if [[ -d "$KIT/python/wheels" ]]; then
    cp -p "$KIT/python/wheels/." "$dir/python/wheels/" 2>/dev/null || cp -rp "$KIT/python/wheels/." "$dir/python/wheels/"
    info "copied Open Interpreter wheels from kit"
  else
    "$BIN/python$PY_VERSION" -m pip download -q -r "$STACK/requirements.lock.txt" -d "$dir/python/wheels" \
      || warn "Open Interpreter wheel download failed"
  fi
}

cache_ember_wheels() {
  local dir="$1" venv
  install -d "$dir/ember-wheels"
  venv="$(scratch_dir)/pip"
  "$BIN/python$PY_VERSION" -m venv "$venv"
  "$venv/bin/python" -m pip download -q --require-hashes --only-binary=:all: \
    -r "$REPO/requirements.txt" -d "$dir/ember-wheels" || warn "Ember wheel download failed (internet needed once)"
}

cache_models() {
  local dir="$1" store names
  store="$(model_store)"
  names="$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print(" ".join(s["base"] + [c["name"] for c in s["custom"]]))' "$SPEC")"
  info "exporting models from $store (read-only): $names"
  # shellcheck disable=SC2086  # names is a space-separated list of model tags
  nice -n 19 python3 "$CB/cbmodels.py" export --store "$store" --dest "$dir/models" $names
}

# Build/radio/printer host tools. PlatformIO and Arduino ESP32 packages are Linux x86-64 only
# (Windows build hosts fetch theirs online the first time).
cache_buildtools() {
  local dir="$1" name venv py
  say "Build/radio host tools: CHIRP, slicers, arduino-cli, PlatformIO"
  for name in chirp orca-linux orca-win elegoo-linux elegoo-win arduino-cli-linux arduino-cli-win pio-udev; do
    cache_pinned "$name" "$dir"
  done
  py="$BIN/python$PY_VERSION"
  have "$py" || py="python3"
  venv="$(scratch_dir)/tools"
  "$py" -m venv "$venv"
  # Linux wheels/sdists only; Windows build hosts install CHIRP/PlatformIO online.
  "$venv/bin/pip" download -q --require-hashes -r "$CB/buildhost/chirp-requirements.txt" -d "$dir/chirp/wheels" \
    || warn "CHIRP wheel download failed"
  "$venv/bin/pip" download -q --require-hashes -r "$CB/buildhost/pio-requirements.txt" -d "$dir/buildhost/pio-wheels" \
    || warn "PlatformIO wheel download failed"
  say "PlatformIO ESP32 toolchains + LoRa libraries (Linux)"
  "$venv/bin/pip" install -q --require-hashes -r "$CB/buildhost/pio-requirements.txt" || { warn "pio install failed"; return 0; }
  cache_platformio "$dir" "$venv/bin/pio"
  say "arduino-cli LoRa libraries${WITH_ARDUINO_CORE:+ + ESP32 core} (Linux)"
  cache_arduino "$dir"
  say "Centauri Carbon 2 slicer profiles"
  if [[ -d "$dir/slicers/cc2-profiles/machine" ]]; then info "have CC2 profiles"
  else python3 "$CB/buildhost/cc2_profiles.py" "$dir/slicers/cc2-profiles" || warn "CC2 profiles failed"; fi
  cache_parts "$dir"
  if [[ -f "$HOME/.local/share/ember/radio-kb/index.db" ]]; then
    say "Offline radio reference"
    rm -rf "$dir/radio-kb" && cp -a "$HOME/.local/share/ember/radio-kb" "$dir/radio-kb"
  fi
}

LORA_LIBS=("jgromes/RadioLib" "mcci-catena/MCCI LoRaWAN LMIC library" "sandeepmistry/LoRa" "mikalhart/TinyGPSPlus" "olikraus/U8g2")
ARDUINO_LIBS=("RadioLib" "MCCI LoRaWAN LMIC library" "LoRa" "TinyGPSPlus" "U8g2")
ESP32_INDEX="https://espressif.github.io/arduino-esp32/package_esp32_index.json"

# Parts library: copied whole if it fits under --parts-gb (default 3), else skipped with a warning.
cache_parts() {
  local dir="$1" src="$HOME/.local/share/ember/parts" kb cap
  [[ -f "$src/library.db" ]] || { info "no parts library yet (scripts/parts_import.py seed)"; return 0; }
  kb="$(du -sk "$src" | cut -f1)"
  cap="$(awk -v g="$PARTS_GB" 'BEGIN { printf "%d", g * 1024 * 1024 }')"
  if (( kb > cap )); then warn "parts library is $((kb / 1024)) MB, over --parts-gb $PARTS_GB: not cached"; return 0; fi
  say "Parts library ($((kb / 1024)) MB)"
  rm -rf "$dir/parts" && cp -a "$src" "$dir/parts"
}

cache_platformio() {
  local dir="$1" pio="$2" proj lib
  proj="$(scratch_dir)/proj"
  mkdir -p "$proj/src"
  printf '#include <Arduino.h>\nvoid setup() {}\nvoid loop() {}\n' > "$proj/src/main.cpp"
  printf '[env:esp32dev]\nplatform = espressif32\nboard = esp32dev\nframework = arduino\n\n[env:esp32s3]\nplatform = espressif32\nboard = esp32-s3-devkitc-1\nframework = arduino\n' > "$proj/platformio.ini"
  export PLATFORMIO_CORE_DIR="$dir/buildhost/platformio"
  (cd "$proj" && "$pio" run -s) || warn "PlatformIO sample build failed (toolchains may be incomplete)"
  for lib in "${LORA_LIBS[@]}"; do "$pio" pkg install -g -l "$lib" -s || warn "pio lib $lib failed"; done
  unset PLATFORMIO_CORE_DIR
  rm -rf "$dir/buildhost/platformio/.cache"   # download leftovers; the installed packages are kept
}

cache_arduino() {
  local dir="$1" cli tgz lib
  tgz="$(get_pinned arduino-cli-linux)" || { warn "no arduino-cli"; return 0; }
  cli="$(scratch_dir)"
  tar -xzf "$tgz" -C "$cli" arduino-cli
  export ARDUINO_DIRECTORIES_DATA="$dir/buildhost/arduino15" ARDUINO_DIRECTORIES_USER="$dir/buildhost/Arduino"
  export ARDUINO_DIRECTORIES_DOWNLOADS="$dir/buildhost/arduino15/staging"
  "$cli/arduino-cli" core update-index --additional-urls "$ESP32_INDEX" >/dev/null || warn "arduino index failed"
  if [[ -n "$WITH_ARDUINO_CORE" ]]; then  # ~7 GB (all ESP32 chip toolchains); PlatformIO already covers ESP32
    "$cli/arduino-cli" core install esp32:esp32 --additional-urls "$ESP32_INDEX" >/dev/null || warn "esp32 core failed"
    rm -rf "$ARDUINO_DIRECTORIES_DOWNLOADS"
  fi
  for lib in "${ARDUINO_LIBS[@]}"; do "$cli/arduino-cli" lib install "$lib" >/dev/null || warn "arduino lib $lib failed"; done
  unset ARDUINO_DIRECTORIES_DATA ARDUINO_DIRECTORIES_USER ARDUINO_DIRECTORIES_DOWNLOADS
}

# Matt's project repos + their build dependencies (coldboot/projects_cache.py) and the dev docs.
cache_projects() {
  local dir="$1" py venv uv
  say "Project repos, PlatformIO toolchains, wheels, npm and NuGet packages"
  cache_pinned node-linux "$dir"
  cache_pinned node-win "$dir"
  py="$BIN/python$PY_VERSION"
  have "$py" || py="python3"
  uv="$BIN/uv"
  have "$uv" || uv="uv"
  venv="$(scratch_dir)/projtools"
  "$py" -m venv "$venv"
  "$venv/bin/pip" install -q --require-hashes -r "$CB/buildhost/pio-requirements.txt" || warn "PlatformIO install failed"
  "$py" "$CB/projects_cache.py" --dest "$dir" --pio "$venv/bin/pio" --python "$venv/bin/python" --uv "$uv" \
    --node-tgz "$dir/$(pin_field node-linux 3)" || warn "project cache had problems (see $dir/projects/MANIFEST.json)"
  if [[ -f "$HOME/.local/share/ember/dev-kb/index.db" ]]; then
    say "Offline developer reference"
    rm -rf "$dir/dev-kb" && cp -a "$HOME/.local/share/ember/dev-kb" "$dir/dev-kb"
  else
    warn "no dev reference yet (run: .venv/bin/python scripts/fetch_dev_kb.py)"
  fi
}

cmd_cache() {
  local dir="" skip_models=0 buildtools=1 only_tools=0 projects=1 only_projects=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --skip-models) skip_models=1; shift ;;
      --skip-buildtools) buildtools=0; shift ;;
      --only-buildtools) only_tools=1; shift ;;
      --skip-projects) projects=0; shift ;;
      --only-projects) only_projects=1; shift ;;
      --with-arduino-core) WITH_ARDUINO_CORE=1; shift ;;
      --parts-gb) PARTS_GB="${2:?--parts-gb needs a number}"; shift 2 ;;
      -*) die "cache: unknown option $1" ;;
      *) dir="$1"; shift ;;
    esac
  done
  [[ -n "$dir" ]] || die "usage: coldboot cache DIR [--skip-models] [--skip-buildtools] [--only-buildtools] [--skip-projects] [--only-projects]"
  install -d "$dir"
  dir="$(cd "$dir" && pwd)"
  info "free space at $dir: $(df -h --output=avail "$dir" | tail -n 1 | tr -d ' ') (full cache needs about 28 GB, or 20 GB with --skip-projects; +9 GB with --with-arduino-core)"
  if [[ "$only_tools" == "1" ]]; then cache_buildtools "$dir"; cache_sums "$dir"; return 0; fi
  if [[ "$only_projects" == "1" ]]; then cache_projects "$dir"; cache_sums "$dir"; return 0; fi
  say "Pinned binaries (Ollama, Goose, uv, Python)"
  local name
  for name in ollama goose goose-deb uv uvx cpython; do cache_pinned "$name" "$dir"; done
  say "Python wheels"
  cache_python "$dir"
  cache_ember_wheels "$dir"
  if [[ "$skip_models" == "0" ]]; then say "Models"; cache_models "$dir"; fi
  if [[ "$buildtools" == "1" ]]; then cache_buildtools "$dir"; fi
  if [[ "$projects" == "1" ]]; then cache_projects "$dir"; fi
  say "Ember repo copy (git bundle) and guide"
  git -C "$REPO" bundle create "$dir/ember.bundle" --all 2>/dev/null || warn "git bundle failed"
  cp -p "$REPO/COLDBOOT.md" "$dir/" 2>/dev/null || true
  cache_sums "$dir"
}

cache_sums() {
  local dir="$1" sums
  say "Checksums"
  sums="$(scratch_dir)/SHA256SUMS"
  (cd "$dir" && find . -type f ! -name SHA256SUMS ! -name '*.part' -printf '%P\0' | sort -z | xargs -0 sha256sum > "$sums")
  mv "$sums" "$dir/SHA256SUMS"
  say "Cache ready: $dir ($(du -sh "$dir" | cut -f1))"
}

usage() {
  sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
}

main() {
  local cmd="${1:-}"
  [[ $# -eq 0 ]] || shift
  SCRATCH="$(mktemp -d -t coldboot.XXXXXX)"
  case "$cmd" in
    install) cmd_install "$@" ;;
    check)   cmd_check ;;
    backup)  cmd_backup "$@" ;;
    restore) cmd_restore "$@" ;;
    cache)   cmd_cache "$@" ;;
    ""|-h|--help|help) usage ;;
    *) usage; die "unknown command: $cmd" ;;
  esac
}

main "$@"
