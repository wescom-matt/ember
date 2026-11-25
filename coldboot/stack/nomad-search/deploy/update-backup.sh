#!/bin/bash
# Refresh ~/agent-stack-backup with nomad-search and the updated configs.
# Run on the P1 as matt. No sudo.
set -euo pipefail
SRC="$HOME/agent-stack/nomad-search"
KIT="$HOME/agent-stack-backup"
STAMP=$(date +%Y%m%d-%H%M%S)
[ -d "$SRC" ] || { echo "missing $SRC"; exit 1; }
[ -d "$KIT" ] || { echo "missing $KIT"; exit 1; }

# Copy tool code, without the venv or caches
rm -rf "$KIT/nomad-search"
mkdir -p "$KIT/nomad-search"
tar -C "$SRC" --exclude='.venv' --exclude='__pycache__' --exclude='docs/live-tests' -cf - . \
  | tar -C "$KIT/nomad-search" -xf -

# Configs and wrappers
cp -p "$HOME/.config/goose/config.yaml" "$KIT/configs/goose/config.yaml"
cp -p "$HOME/.local/bin/goose-lw" "$KIT/configs/wrappers/goose-lw"
cp -p "$HOME/.config/Open Interpreter/profiles/nomad.py" \
  "$KIT/configs/open-interpreter/profiles-Open Interpreter/nomad.py"
cp -p "$HOME/.config/Open Interpreter/profiles/default.yaml" \
  "$KIT/configs/open-interpreter/profiles-Open Interpreter/default.yaml"
if [ -f "$KIT/configs/open-interpreter/profiles-open-interpreter/default.yaml" ]; then
  cp -p "$HOME/.config/Open Interpreter/profiles/default.yaml" \
    "$KIT/configs/open-interpreter/profiles-open-interpreter/default.yaml"
fi
cp -p "$HOME/AI-AGENTS-README.md" "$KIT/docs/AI-AGENTS-README.md"

# Rebuild script: add step 4b once
if ! grep -q '4b. nomad-search' "$KIT/rebuild.sh"; then
  python3 - << 'PY'
from pathlib import Path
p = Path.home() / "agent-stack-backup" / "rebuild.sh"
t = p.read_text()
needle = 'say "5. Ollama"'
step = '''say "4b. nomad-search (Python stdlib only, no wheels)"
mkdir -p "$HOME/agent-stack"
rm -rf "$HOME/agent-stack/nomad-search"
cp -a "$K/nomad-search" "$HOME/agent-stack/nomad-search"
rm -rf "$HOME/agent-stack/nomad-search/.venv" "$HOME/agent-stack/nomad-search/nomad_search/__pycache__" "$HOME/agent-stack/nomad-search/tests/__pycache__"
( cd "$HOME/agent-stack/nomad-search" && PYTHON="$BIN/python3.12" bash ./install.sh )

'''
if needle not in t:
    raise SystemExit("rebuild.sh: could not find Ollama step")
p.write_text(t.replace(needle, step + needle, 1))
print("rebuild.sh updated")
PY
fi

# REBUILD.md notes
if ! grep -q 'nomad-search' "$KIT/REBUILD.md"; then
  python3 - << 'PY'
from pathlib import Path
p = Path.home() / "agent-stack-backup" / "REBUILD.md"
t = p.read_text()
row = "| `nomad-search/` | Knowledge-base search tool (stdlib only, no wheels), Goose MCP extension, CLI |\n"
# insert after docs row if present, else before export-models
if "| `docs/`" in t and row.strip() not in t:
    t = t.replace("| `docs/`", row + "| `docs/`", 1)
if "then test: `goose --version`" in t:
    t = t.replace(
        "then test: `goose --version`, `ai-interp`, `goose-lw \"make /tmp/hi.txt containing hi\"`.",
        "then test: `goose --version`, `nomad-search \"treat a minor burn\"`, `ai-interp`, `goose-lw \"make /tmp/hi.txt containing hi\"`.",
        1,
    )
p.write_text(t)
print("REBUILD.md updated")
PY
fi

# Size note and checksums
{
  echo "Updated $STAMP to add nomad-search (stdlib, no extra wheels)."
} >> "$KIT/SIZES.txt"
# Keep previous sums
cp -p "$KIT/SHA256SUMS" "$KIT/SHA256SUMS.bak-$STAMP"
# Recreate sums for every file except the sums file itself and its backups
( cd "$KIT" && find . -type f ! -name 'SHA256SUMS' ! -name 'SHA256SUMS.bak-*' ! -path './nomad-search/.venv/*' | sed 's|^\./||' | sort | xargs -d '\n' sha256sum > SHA256SUMS )
# drop the bak from the working set? leave it but it is excluded from SUMS
echo "Backup kit updated. Verify:"
( cd "$KIT" && sha256sum -c --quiet SHA256SUMS && echo "SHA256SUMS OK" )
du -sh "$KIT" "$KIT/nomad-search"
