"""Chat turn: retrieve from the knowledge base, stream from Ollama, save the reply."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from ember import config
from ember.db import connect, now
from ember.kb import DEFAULT_TOP_K, KnowledgeBase, format_context
from ember.ollama import stream_chat
from ember.prompts import SYSTEM_PROMPT

LOG = logging.getLogger("ember.chat")


@dataclass(frozen=True)
class Turn:
    conversation_id: int
    model: str
    kb_id: str
    think: bool
    question: str


def history(conn: sqlite3.Connection, conversation_id: int) -> list[dict[str, str]]:
    """Most recent turns that fit the character budget, oldest first."""
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
        (conversation_id, config.HISTORY_MAX_TURNS * 2),
    ).fetchall()
    picked: list[dict[str, str]] = []
    used = 0
    for row in rows:
        size = len(row["content"])
        if picked and used + size > config.HISTORY_CHAR_BUDGET:
            break
        content = row["content"][-config.HISTORY_CHAR_BUDGET :]
        picked.append({"role": row["role"], "content": content})
        used += len(content)
    picked.reverse()
    return picked


def build_messages(past: list[dict[str, str]], context: str | None) -> list[dict[str, str]]:
    system = SYSTEM_PROMPT
    if context is not None:
        system = f"{SYSTEM_PROMPT}\n\n{context}"
    return [{"role": "system", "content": system}, *past]


def _event(kind: str, **fields: Any) -> bytes:
    return (json.dumps({"type": kind, **fields}, ensure_ascii=False) + "\n").encode("utf-8")


def _retrieve(kb: KnowledgeBase | None, question: str) -> tuple[list[dict[str, Any]], str | None, str]:
    """Return (hits, context, error). Errors degrade to a model-only answer."""
    if kb is None:
        return [], None, ""
    try:
        hits = kb.search(question, DEFAULT_TOP_K)
    except (RuntimeError, ValueError) as exc:
        LOG.warning("knowledge base search failed: %s", exc)
        return [], None, "Knowledge base search failed; answering without it."
    return hits, format_context(hits), ""


def run_turn(db_path: Any, ollama_url: str, kb: KnowledgeBase | None, turn: Turn) -> Iterator[bytes]:
    """Generator for a streaming response. Saves the reply even if the client leaves."""
    if kb is not None:
        yield _event("status", text=f"Searching {kb.label}…")
    hits, context, kb_error = _retrieve(kb, turn.question)
    if kb_error:
        yield _event("notice", text=kb_error)
    if kb is not None:
        yield _event("sources", sources=hits)
    with connect(db_path) as conn:
        past = history(conn, turn.conversation_id)
    reply: list[str] = []
    thinking: list[str] = []
    sizes = [0, 0]
    try:
        yield _event("status", text="Thinking…" if turn.think else "Writing…")
        for kind, piece in stream_chat(ollama_url, turn.model, build_messages(past, context), turn.think):
            idx = 0 if kind == "content" else 1
            if sizes[idx] + len(piece) > config.MAX_REPLY_CHARS:
                yield _event("notice", text="Reply hit the length limit and was cut off.")
                break
            sizes[idx] += len(piece)
            (reply if idx == 0 else thinking).append(piece)
            yield _event("token" if idx == 0 else "think", t=piece)
        yield _event("done")
    except RuntimeError as exc:
        LOG.warning("chat stream failed: %s", exc)
        yield _event("error", message="The model stopped with an error. Check that Ollama is running.")
    finally:
        _save_reply(db_path, turn, "".join(reply), "".join(thinking), hits)


def _save_reply(db_path: Any, turn: Turn, text: str, thinking: str, hits: list[dict[str, Any]]) -> None:
    if not text.strip() and not thinking.strip():
        text = "_(no reply)_"
    with connect(db_path) as conn:
        t = now()
        conn.execute(
            "INSERT INTO messages(conversation_id, role, content, thinking, sources, model, created_at) "
            "VALUES (?, 'assistant', ?, ?, ?, ?, ?)",
            (turn.conversation_id, text, thinking, json.dumps(hits, ensure_ascii=False), turn.model, t),
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (t, turn.conversation_id))
