"""Builds the model context for one turn inside the budget (ember.budget):

system prompt -> project notes -> reference passages (code chunks + knowledge base)
-> rolling summary of older turns -> the last few turns verbatim.

Older turns are compressed into a short summary once the history share is full;
the summary is kept on the conversation and extended as the chat grows.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ember import budget, code_index, notes, ollama
from ember.db import connect

LOG = logging.getLogger("ember.context")
KEEP_LAST = 4
MAX_ROWS = 200
SUMMARY_TOKENS = 220
SUMMARY_INPUT_CHARS = 6000
MAX_SUMMARY_CHARS = 900
SUMMARY_PROMPT = (
    "Summarize this earlier part of a chat for the assistant's memory in at most 120 words. Keep decisions, file "
    "names, pins, commands, errors and open questions. Plain sentences, no preamble."
)


@dataclass
class Prepared:
    messages: list[dict[str, Any]]
    usage: dict[str, int]
    chunks: list[dict[str, Any]] = field(default_factory=list)
    summarized: bool = False
    notices: list[str] = field(default_factory=list)


def _rows(conn: sqlite3.Connection, conv_id: int, after: int) -> list[sqlite3.Row]:
    rows = conn.execute(
        "SELECT id, role, content FROM messages WHERE conversation_id = ? AND id > ? ORDER BY id DESC LIMIT ?",
        (conv_id, after, MAX_ROWS),
    ).fetchall()
    return list(reversed(rows))


def _summarize(ollama_url: str, model: str, old_summary: str, rows: list[sqlite3.Row]) -> str:
    transcript = "\n".join(f"{r['role']}: {r['content'][:800]}" for r in rows)[-SUMMARY_INPUT_CHARS:]
    user = (f"Summary so far: {old_summary}\n\n" if old_summary else "") + f"New messages:\n{transcript}"
    try:
        text = ollama.complete(
            ollama_url,
            model,
            [{"role": "system", "content": SUMMARY_PROMPT}, {"role": "user", "content": user}],
            SUMMARY_TOKENS,
        )
    except RuntimeError as exc:
        LOG.warning("summary failed, keeping the old one: %s", exc)
        text = old_summary or "(older messages dropped to save space)"
    return budget.fit(text, MAX_SUMMARY_CHARS)


def history(
    db_path: Path, ollama_url: str, model: str, conv_id: int, max_chars: int
) -> tuple[str, list[dict[str, str]], bool]:
    """(summary, recent turns, summarized_now). Compresses older turns when they don't fit."""
    with connect(db_path) as conn:
        conv = conn.execute("SELECT summary, summary_upto FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        summary, upto = (str(conv["summary"]), int(conv["summary_upto"])) if conv else ("", 0)
        rows = _rows(conn, conv_id, upto)
    size = len(summary) + sum(len(r["content"]) for r in rows)
    did = False
    if size > max_chars and len(rows) > KEEP_LAST:
        old, rows = rows[:-KEEP_LAST], rows[-KEEP_LAST:]
        summary = _summarize(ollama_url, model, summary, old)
        did = True
        with connect(db_path) as conn:
            conn.execute(
                "UPDATE conversations SET summary = ?, summary_upto = ? WHERE id = ?",
                (summary, int(old[-1]["id"]), conv_id),
            )
    room = max(400, max_chars - len(summary))
    picked: list[dict[str, str]] = []
    for r in reversed(rows):  # newest first; the newest (the question) always goes in
        text = r["content"]
        if picked and len(text) > room:
            break
        text = text if len(text) <= room else text[: room // 2] + "\n…\n" + text[-room // 2 :]
        picked.append({"role": r["role"], "content": text})
        room -= len(text)
    picked.reverse()
    return summary, picked, did


def prepare(
    db_path: Path,
    data_dir: Path,
    ollama_url: str,
    model: str,
    conv_id: int,
    project: str,
    question: str,
    system: str,
    kb_context: str | None,
) -> Prepared:
    plan = budget.plan(model)
    system = budget.fit(system, plan.chars("system"))
    note_text = ""
    if project:
        note_text = budget.fit(notes.get(data_dir, project)["text"], plan.chars("notes"))
    refs_room = plan.chars("refs")
    kb_text = budget.fit(kb_context, refs_room // 2 if project else refs_room) if kb_context else ""
    chunks: list[dict[str, Any]] = []
    notices: list[str] = []
    if project:
        started = code_index.refresh_async(data_dir, ollama_url, project)
        if started:
            notices.append(f"Indexing {project}'s code in the background; code search improves when it's done.")
        try:
            chunks = code_index.search(data_dir, ollama_url, project, question, refs_room - len(kb_text))
        except (RuntimeError, OSError, sqlite3.Error) as exc:
            LOG.warning("code search failed: %s", exc)
    code_text = code_index.format_chunks(chunks)
    summary, past, did = history(db_path, ollama_url, model, conv_id, plan.chars("history"))
    parts = [system]
    if note_text:
        parts.append(f"Project notes ({project}):\n{note_text}")
    if code_text:
        parts.append(code_text)
    if kb_text:
        parts.append(kb_text)
    if summary:
        parts.append(f"Earlier in this chat (summary): {summary}")
    messages: list[dict[str, Any]] = [{"role": "system", "content": "\n\n".join(parts)}, *past]
    hist_text = summary + "".join(m["content"] for m in past)
    use = budget.usage(plan, {"system": system, "notes": note_text, "refs": code_text + kb_text, "history": hist_text})
    return Prepared(messages, use, chunks, did, notices)
