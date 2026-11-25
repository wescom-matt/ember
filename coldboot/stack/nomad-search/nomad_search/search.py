"""Embed a query with the same model Nomad used, then search Qdrant read-only."""

from __future__ import annotations

from typing import Any

from nomad_search import config
from nomad_search.httpjson import post_json


def embed_query(query: str) -> list[float]:
    """Embed with nomic-embed-text:v1.5 and Nomad's search_query prefix."""
    url = f"{config.ollama_url()}/api/embeddings"
    payload = {
        "model": config.EMBED_MODEL,
        "prompt": config.QUERY_PREFIX + query,
        "keep_alive": config.EMBED_KEEP_ALIVE,
    }
    data = post_json(url, payload, config.HTTP_TIMEOUT_SEC)
    vector = data.get("embedding")
    if not isinstance(vector, list) or len(vector) != config.VECTOR_SIZE:
        got = len(vector) if isinstance(vector, list) else type(vector).__name__
        raise RuntimeError(f"unexpected embedding size: {got}")
    out: list[float] = []
    for item in vector:
        if not isinstance(item, (int, float)):
            raise RuntimeError("embedding contained a non-number")
        out.append(float(item))
    return out


def search_points(vector: list[float], top_k: int) -> list[dict[str, Any]]:
    """Cosine search of nomad_knowledge_base. Filter to active chunks only."""
    url = f"{config.qdrant_url()}/collections/{config.COLLECTION}/points/search"
    payload = {
        "vector": vector,
        "limit": top_k,
        "with_payload": True,
        "with_vector": False,
        "filter": {"must": [{"key": "active", "match": {"value": True}}]},
    }
    data = post_json(url, payload, config.HTTP_TIMEOUT_SEC)
    result = data.get("result")
    if not isinstance(result, list):
        raise RuntimeError("Qdrant search returned no result list")
    hits: list[dict[str, Any]] = []
    for item in result:
        if isinstance(item, dict):
            hits.append(item)
    return hits


def search_knowledge(query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    """Return ranked snippets with titles and sources."""
    clean = config.sanitize_query(query)
    k = config.clamp_top_k(top_k)
    vector = embed_query(clean)
    # Fetch a few extras so path-dedup can still fill top_k.
    fetch_k = k + 4
    if fetch_k > 12:
        fetch_k = 12
    hits = search_points(vector, fetch_k)
    snippets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        item = _snippet(0, hit)
        key = item["path"] or (item["title"] + "\n" + item["text"][:80])
        if key in seen:
            continue
        seen.add(key)
        item["rank"] = len(snippets) + 1
        snippets.append(item)
        if len(snippets) >= k:
            break
    return snippets


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _snippet(rank: int, hit: dict[str, Any]) -> dict[str, Any]:
    payload = hit.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    score = hit.get("score")
    try:
        score_f = float(score) if score is not None else 0.0
    except (TypeError, ValueError):
        score_f = 0.0
    title = (
        _as_text(payload.get("full_title"))
        or _as_text(payload.get("article_title"))
        or _as_text(payload.get("section_title"))
        or "Untitled"
    )
    corpus = _as_text(payload.get("archive_title"))
    section = _as_text(payload.get("section_title"))
    path = _as_text(payload.get("article_path"))
    source_path = _as_text(payload.get("source"))
    source = corpus or _basename(source_path) or "unknown source"
    text = _trim_nav(_as_text(payload.get("text")))
    if len(text) > config.MAX_SNIPPET_CHARS:
        text = text[: config.MAX_SNIPPET_CHARS].rstrip() + "..."
    return {
        "rank": rank,
        "score": round(score_f, 4),
        "title": title,
        "section": section,
        "source": source,
        "path": path,
        "text": text,
    }



def _trim_nav(text: str) -> str:
    """Drop leading US .gov / MedlinePlus navigation boilerplate when present."""
    start = text[:80]
    if "Skip navigation" not in start and "Official websites use .gov" not in start:
        return text
    cut = -1
    for marker in ("URL of this page:", "You Are Here:"):
        i = text.find(marker)
        if i == -1:
            continue
        href = text.find(".htm", i)
        if href != -1:
            cut = max(cut, href + 4)
            continue
        nl = text.find("\n", i)
        if nl != -1:
            cut = max(cut, nl + 1)
    if cut <= 0 or cut >= len(text):
        return text
    return text[cut:].lstrip(" -:\t")

def _basename(path: str) -> str:
    if not path:
        return ""
    trimmed = path.rstrip("/")
    name = trimmed.rsplit("/", 1)[-1]
    return name
