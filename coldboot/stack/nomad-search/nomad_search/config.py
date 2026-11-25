"""Local-only settings for Nomad knowledge search. No secrets live here."""

from __future__ import annotations

import os
from urllib.parse import urlparse

COLLECTION = "nomad_knowledge_base"
EMBED_MODEL = "nomic-embed-text:v1.5"
QUERY_PREFIX = "search_query: "
VECTOR_SIZE = 768
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
HTTP_TIMEOUT_SEC = 45
EMBED_KEEP_ALIVE = "5m"
MAX_QUERY_CHARS = 500
DEFAULT_TOP_K = 5
MAX_TOP_K = 8
MAX_SNIPPET_CHARS = 800
MAX_RESPONSE_CHARS = 8000
MAX_HTTP_BYTES = 2_000_000
MAX_MCP_BYTES = 1_000_000
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})


def require_local_http_url(url: str, name: str) -> str:
    """Accept only loopback HTTP URLs, with no credentials."""
    raw = (url or "").strip()
    if not raw:
        raise ValueError(f"{name} is empty")
    parsed = urlparse(raw)
    if parsed.scheme != "http":
        raise ValueError(f"{name} must use http")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"{name} must point at 127.0.0.1")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{name} must not contain credentials")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError(f"{name} must be an origin only, no path")
    port = parsed.port
    if port is None:
        return "http://127.0.0.1"
    return f"http://127.0.0.1:{port}"


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def qdrant_url() -> str:
    return require_local_http_url(_env("NOMAD_QDRANT_URL", DEFAULT_QDRANT_URL), "NOMAD_QDRANT_URL")


def ollama_url() -> str:
    return require_local_http_url(_env("NOMAD_OLLAMA_URL", DEFAULT_OLLAMA_URL), "NOMAD_OLLAMA_URL")


def clamp_top_k(raw: object) -> int:
    if raw is None or raw == "":
        return DEFAULT_TOP_K
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("top_k must be an integer") from exc
    if value < 1:
        return 1
    if value > MAX_TOP_K:
        return MAX_TOP_K
    return value


def sanitize_query(raw: object) -> str:
    if raw is None:
        raise ValueError("query is required")
    if not isinstance(raw, str):
        raise ValueError("query must be text")
    text = " ".join(raw.split())
    if not text:
        raise ValueError("query is empty")
    if len(text) > MAX_QUERY_CHARS:
        text = text[:MAX_QUERY_CHARS].rstrip()
    return text
