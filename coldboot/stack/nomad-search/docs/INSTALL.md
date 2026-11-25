# Install on the P1 (no internet needed)

Python 3.12 from `~/.local/bin/python3.12` (uv-managed). No pip packages.

```bash
python3.12 -m venv ~/agent-stack/nomad-search/.venv
# shebangs on bin/nomad-search and bin/nomad-search-mcp should point at that venv
ln -sfn ~/agent-stack/nomad-search/bin/nomad-search ~/.local/bin/nomad-search
ln -sfn ~/agent-stack/nomad-search/bin/nomad-search-mcp ~/.local/bin/nomad-search-mcp
```

Unit tests:

```bash
~/agent-stack/nomad-search/.venv/bin/python -m unittest discover -s ~/agent-stack/nomad-search/tests -q
```
