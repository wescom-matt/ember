"""Format search hits for people and for the agent tool."""

from __future__ import annotations

from typing import Any

from nomad_search import config


def format_hits(query: str, hits: list[dict[str, Any]]) -> str:
    if not hits:
        return (
            f'No matching passages in the Nomad knowledge base for: "{query}"\n'
            "Try different wording. Answers should not be invented."
        )
    lines = [
        f'Nomad knowledge base results for: "{query}"',
        "Cite these sources. Do not invent others.",
        "",
    ]
    for hit in hits:
        header = f"[{hit['rank']}] {hit['source']} — {hit['title']}  (score {hit['score']:.4f})"
        lines.append(header)
        section = hit.get("section") or ""
        path = hit.get("path") or ""
        if section and section not in header:
            lines.append(f"Section: {section}")
        if path:
            lines.append(f"Path: {path}")
        lines.append(hit.get("text") or "")
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    if len(text) > config.MAX_RESPONSE_CHARS:
        text = text[: config.MAX_RESPONSE_CHARS].rstrip() + "\n[truncated]\n"
    return text
