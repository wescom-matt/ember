#!/bin/bash
# Install nomad-search on this machine (user-space, no sudo, no internet).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-$HOME/.local/bin/python3.12}"
BIN="$HOME/.local/bin"
VENV="$ROOT/.venv"

if [ ! -x "$PY" ]; then
  echo "Need Python 3.12 at $PY (the uv-managed interpreter)." >&2
  exit 1
fi

"$PY" -m venv "$VENV"
for name in nomad-search nomad-search-mcp; do
  src="$ROOT/bin/$name"
  tmp="$ROOT/bin/$name.tmp"
  {
    printf '#!%s\n' "$VENV/bin/python"
    tail -n +2 "$src"
  } > "$tmp"
  mv "$tmp" "$src"
  chmod 755 "$src"
done

mkdir -p "$BIN"
ln -sfn "$ROOT/bin/nomad-search" "$BIN/nomad-search"
ln -sfn "$ROOT/bin/nomad-search-mcp" "$BIN/nomad-search-mcp"

PYTHONPATH="$ROOT" "$VENV/bin/python" -m unittest discover -s "$ROOT/tests" -q
echo "Installed: $BIN/nomad-search  and  $BIN/nomad-search-mcp"
