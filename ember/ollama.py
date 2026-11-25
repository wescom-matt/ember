"""Ollama client: list models and stream chat replies."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ember import config
from ember.httpjson import call_json, stream_ndjson

EMBED_HINTS = ("embed", "bge-", "minilm")
MAX_MODELS = 100


def list_models(base_url: str) -> list[dict[str, Any]]:
    """Chat-capable models only (embedding models are hidden)."""
    data = call_json(f"{base_url}/api/tags", None, config.OLLAMA_CONNECT_TIMEOUT_SEC)
    models = data.get("models")
    if not isinstance(models, list):
        raise RuntimeError("Ollama returned no model list")
    out: list[dict[str, Any]] = []
    for item in models[:MAX_MODELS]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not name or any(h in name.lower() for h in EMBED_HINTS):
            continue
        size = item.get("size")
        out.append({"name": name, "size": int(size) if isinstance(size, int) else 0})
    out.sort(key=lambda m: m["name"])
    return out


def model_names(base_url: str) -> set[str]:
    return {m["name"] for m in list_models(base_url)}


def normalize_model(name: str, installed: set[str]) -> str | None:
    """Match 'qwen3.5-9b-4k' to 'qwen3.5-9b-4k:latest' and back."""
    if name in installed:
        return name
    if f"{name}:latest" in installed:
        return f"{name}:latest"
    return None


def supports_thinking(base_url: str, model: str) -> bool:
    data = call_json(f"{base_url}/api/show", {"model": model}, config.OLLAMA_CONNECT_TIMEOUT_SEC)
    caps = data.get("capabilities")
    return isinstance(caps, list) and "thinking" in caps


def stream_chat(base_url: str, model: str, messages: list[dict[str, str]], think: bool) -> Iterator[tuple[str, str]]:
    """Yield ('content'|'thinking', text) pieces until Ollama says done."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": think,
        "keep_alive": "10m",
    }
    stream = stream_ndjson(
        f"{base_url}/api/chat", payload, config.OLLAMA_STREAM_IDLE_TIMEOUT_SEC, config.OLLAMA_MAX_STREAM_LINES
    )
    for item in stream:
        if item.get("error"):
            raise RuntimeError(f"Ollama: {str(item['error'])[:200]}")
        msg = item.get("message")
        if isinstance(msg, dict):
            thinking = msg.get("thinking")
            if isinstance(thinking, str) and thinking:
                yield ("thinking", thinking)
            content = msg.get("content")
            if isinstance(content, str) and content:
                yield ("content", content)
        if item.get("done"):
            return
