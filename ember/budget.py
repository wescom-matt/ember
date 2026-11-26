"""Context budget: split the model's context window across system prompt, project
notes, reference passages (code + knowledge base), chat history and the reply.

Token counts are estimates (about 3.5 characters per token for code and English),
good enough to stay inside a 4k or 8k window.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CHARS_PER_TOKEN = 3.5
DEFAULT_CTX = 4096
MIN_CTX = 2048
MAX_CTX = 32768
# Shares of the window per part. The rest of system's share covers tool schemas.
SHARES = {
    4096: {"system": 0.25, "notes": 0.08, "refs": 0.20, "history": 0.22, "reply": 0.25},
    8192: {"system": 0.14, "notes": 0.07, "refs": 0.31, "history": 0.26, "reply": 0.22},
}
PARTS = ("system", "notes", "refs", "history", "reply")


@dataclass(frozen=True)
class Budget:
    ctx: int
    tokens: dict[str, int]

    def chars(self, part: str) -> int:
        return int(self.tokens[part] * CHARS_PER_TOKEN)


def context_size(model: str) -> int:
    """Window size from the model name ('qwen3.5-9b-8k' -> 8192); 4096 if the name doesn't say."""
    m = re.search(r"-(\d{1,2})k(?::|$)", model.lower())
    if not m:
        return DEFAULT_CTX
    return max(MIN_CTX, min(MAX_CTX, int(m.group(1)) * 1024))


def plan(model: str) -> Budget:
    ctx = context_size(model)
    shares = SHARES[8192] if ctx >= 8192 else SHARES[4096]
    return Budget(ctx, {p: int(ctx * shares[p]) for p in PARTS})


def estimate(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN + 0.999)


def fit(text: str, max_chars: int) -> str:
    """Trim to max_chars, cutting at a line break when one is near the end."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    nl = cut.rfind("\n")
    return (cut[:nl] if nl > max_chars * 0.7 else cut).rstrip() + "\n…"


def usage(budget: Budget, used: dict[str, str]) -> dict[str, int]:
    """Token use per part for the UI indicator; 'reply' is the reserved space."""
    out = {p: estimate(used.get(p, "")) for p in PARTS if p != "reply"}
    out["reply"] = budget.tokens["reply"]
    out["ctx"] = budget.ctx
    out["total"] = sum(out[p] for p in PARTS)
    return out
