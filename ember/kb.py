"""Knowledge bases. Phase 1 ships 'none' and 'nomad' (live, read-only Qdrant search).

To add a knowledge base later: write a class with `id`, `label`, `description`,
and `search(query, top_k) -> list[dict]`, then add it in `build_registry`.
Search logic for Nomad is adapted from ~/agent-stack/nomad-search (same model,
same query prefix, same 'active' filter), so new Nomad content shows up
automatically because every question queries Qdrant live.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from ember.httpjson import call_json
from ember.parts import PartsKB
from ember.radio_kb import RadioKB

NOMAD_COLLECTION = "nomad_knowledge_base"
NOMAD_EMBED_MODEL = "nomic-embed-text:v1.5"
NOMAD_QUERY_PREFIX = "search_query: "
NOMAD_VECTOR_SIZE = 768
KB_TIMEOUT_SEC = 45
MAX_QUERY_CHARS = 500
MAX_SNIPPET_CHARS = 700
DEFAULT_TOP_K = 4
MAX_TOP_K = 8


class KnowledgeBase(Protocol):
    id: str
    label: str
    description: str

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]: ...


class NomadKB:
    id = "nomad"
    label = "Nomad"
    description = "Offline library: medicine, repair, radio, outdoors, Wikipedia and more"

    def __init__(self, ollama_url: str, qdrant_url: str) -> None:
        self._ollama = ollama_url
        self._qdrant = qdrant_url

    def _embed(self, query: str) -> list[float]:
        payload = {"model": NOMAD_EMBED_MODEL, "prompt": NOMAD_QUERY_PREFIX + query, "keep_alive": "5m"}
        data = call_json(f"{self._ollama}/api/embeddings", payload, KB_TIMEOUT_SEC)
        vector = data.get("embedding")
        if not isinstance(vector, list) or len(vector) != NOMAD_VECTOR_SIZE:
            raise RuntimeError("unexpected embedding size")
        if not all(isinstance(v, (int, float)) for v in vector):
            raise RuntimeError("embedding contained a non-number")
        return [float(v) for v in vector]

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        clean = " ".join(query.split())[:MAX_QUERY_CHARS]
        if not clean:
            return []
        k = max(1, min(int(top_k), MAX_TOP_K))
        payload = {
            "vector": self._embed(clean),
            "limit": min(k + 4, 12),
            "with_payload": True,
            "with_vector": False,
            "filter": {"must": [{"key": "active", "match": {"value": True}}]},
        }
        url = f"{self._qdrant}/collections/{NOMAD_COLLECTION}/points/search"
        result = call_json(url, payload, KB_TIMEOUT_SEC).get("result")
        if not isinstance(result, list):
            raise RuntimeError("Qdrant search returned no result list")
        return _dedupe([_snippet(h) for h in result if isinstance(h, dict)], k)


def _dedupe(items: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = item["path"] or (item["title"] + "\n" + item["text"][:80])
        if key in seen:
            continue
        seen.add(key)
        item["rank"] = len(out) + 1
        out.append(item)
        if len(out) >= k:
            break
    return out


def _text(value: object) -> str:
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()


def _snippet(hit: dict[str, Any]) -> dict[str, Any]:
    payload = hit.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    try:
        score = float(hit.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    title = (
        _text(payload.get("full_title"))
        or _text(payload.get("article_title"))
        or _text(payload.get("section_title"))
        or "Untitled"
    )
    source_path = _text(payload.get("source"))
    source = _text(payload.get("archive_title")) or source_path.rstrip("/").rsplit("/", 1)[-1] or "unknown source"
    text = _text(payload.get("text"))
    if len(text) > MAX_SNIPPET_CHARS:
        text = text[:MAX_SNIPPET_CHARS].rstrip() + "..."
    return {
        "rank": 0,
        "score": round(score, 4),
        "title": title[:200],
        "section": _text(payload.get("section_title"))[:200],
        "source": source[:200],
        "path": _text(payload.get("article_path"))[:300],
        "text": text,
    }


def build_registry(ollama_url: str, qdrant_url: str, data_dir: Path | None = None) -> dict[str, KnowledgeBase]:
    nomad = NomadKB(ollama_url, qdrant_url)
    out: dict[str, KnowledgeBase] = {nomad.id: nomad}
    if data_dir is not None:
        radio_kb = RadioKB(data_dir)
        out[radio_kb.id] = radio_kb
        parts_kb = PartsKB(data_dir)
        out[parts_kb.id] = parts_kb
    return out


def describe(registry: dict[str, KnowledgeBase]) -> list[dict[str, str]]:
    items = [{"id": "none", "label": "No knowledge base", "description": "Model only"}]
    for kb in registry.values():
        items.append({"id": kb.id, "label": kb.label, "description": kb.description})
    return items


def format_context(hits: list[dict[str, Any]]) -> str:
    """Numbered passages for the model to cite as [1], [2], ..."""
    if not hits:
        return "No matching passages were found in the knowledge base. Say so if it matters."
    lines = ["Knowledge base passages (cite as [n]; do not invent sources):"]
    for h in hits:
        lines.append(f"[{h['rank']}] {h['source']} — {h['title']}")
        lines.append(h["text"])
        lines.append("")
    return "\n".join(lines).rstrip()
