# nomad-search

Read-only search of the Nomad knowledge base on the P1. It uses the same
embedding setup Nomad used when it indexed the collection, then queries
Qdrant locally. No cloud APIs, no writes to Qdrant or Nomad.

## How it matches Nomad

- Embedding model: `nomic-embed-text:v1.5` via Ollama at `http://127.0.0.1:11434`
- Query prefix: `search_query: ` (Nomad stored chunks as `search_document: `)
- Vector size: 768, cosine distance
- Collection: `nomad_knowledge_base` on Qdrant at `http://127.0.0.1:6333`
- Payload fields used: `text`, `full_title` / `article_title`, `section_title`,
  `archive_title`, `article_path`, `source`, `active`
- Only chunks with `active: true` are returned

## Commands

```bash
nomad-search "how do I treat a minor burn"
nomad-search -k 8 "ham radio 18 metre band"
nomad-search --json "fix a leaky faucet"
```

From Goose (approval stays on for shell commands):

```bash
goose
# then ask a factual question; Goose should call the search_knowledge tool
```

Lead/worker mode still uses `goose-lw`. The default worker is Qwen 3.5 9B,
because Llama 3.2 often printed commands instead of running them.

Open Interpreter (`ai-interp`) is told to run `nomad-search "question"`
before answering factual questions. You still approve that command.

## Layout

- Code: `~/agent-stack/nomad-search/`
- Venv (stdlib only): `~/agent-stack/nomad-search/.venv`
- Wrappers: `~/.local/bin/nomad-search` and `~/.local/bin/nomad-search-mcp`
- Goose extension: `nomad-search` in `~/.config/goose/config.yaml`

Safety: HTTP calls have timeouts and size caps, URLs must be 127.0.0.1,
and the tool only does search (no upserts, no deletes, no container changes).
