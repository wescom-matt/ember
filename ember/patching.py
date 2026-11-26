"""Edit-by-diff: apply a small unified diff or SEARCH/REPLACE blocks to a file.

Small models are much better at "change these 3 lines" than at rewriting a whole
file. Every edit is validated (each search block found once, hunks match, braces
stay balanced, Python still compiles) before Ember shows the diff and asks.
"""

from __future__ import annotations

import ast
import difflib
import re

MAX_PATCH_CHARS = 12_000
MAX_BLOCKS = 20
SR_BLOCK = re.compile(r"<{5,9} ?SEARCH\n(.*?)\n?={5,9}\n(.*?)\n?>{5,9} ?REPLACE", re.DOTALL)
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")
BRACE_EXT = (".c", ".h", ".cpp", ".hpp", ".cc", ".ino", ".cs", ".js", ".ts", ".dart", ".java")


class PatchError(ValueError):
    pass


def _find_lines(hay: list[str], needle: list[str], hint: int) -> int:
    """Index where needle starts in hay (exact, then ignoring trailing spaces); closest to hint wins."""
    if not needle:
        return min(max(hint, 0), len(hay))
    for norm in (lambda s: s, lambda s: s.rstrip()):
        n = [norm(x) for x in needle]
        hits = [i for i in range(len(hay) - len(n) + 1) if [norm(x) for x in hay[i : i + len(n)]] == n]
        if hits:
            return min(hits, key=lambda i: abs(i - hint))
    return -1


def apply_unified(text: str, patch: str) -> str:
    lines = text.splitlines()
    hunks: list[tuple[int, list[str], list[str]]] = []
    cur: tuple[int, list[str], list[str]] | None = None
    for raw in patch.splitlines():
        m = HUNK.match(raw)
        if m:
            cur = (int(m.group(1)) - 1, [], [])
            hunks.append(cur)
        elif cur is None or raw.startswith(("---", "+++")):
            continue
        elif raw.startswith("-"):
            cur[1].append(raw[1:])
        elif raw.startswith("+"):
            cur[2].append(raw[1:])
        elif raw.startswith(" ") or raw == "":
            cur[1].append(raw[1:])
            cur[2].append(raw[1:])
    if not hunks or len(hunks) > MAX_BLOCKS:
        raise PatchError("no usable @@ hunks in the diff")
    offset = 0
    for start, old, new in hunks:
        at = _find_lines(lines, old, start + offset)
        if at < 0:
            raise PatchError(f"hunk at line {start + 1} doesn't match the file; read the file again")
        lines[at : at + len(old)] = new
        offset += len(new) - len(old)
    return "\n".join(lines) + ("\n" if text.endswith("\n") or not text else "")


def apply_search_replace(text: str, patch: str) -> str:
    blocks = SR_BLOCK.findall(patch)
    if not blocks or len(blocks) > MAX_BLOCKS:
        raise PatchError("no SEARCH/REPLACE blocks found")
    for search, replace in blocks:
        count = text.count(search) if search else 0
        if count == 1:
            text = text.replace(search, replace, 1)
            continue
        if count > 1:
            raise PatchError("a SEARCH block matches more than once; include more lines")
        lines = text.splitlines()
        at = _find_lines(lines, search.splitlines(), 0) if search else -1
        if at < 0:
            raise PatchError("a SEARCH block was not found; copy the lines exactly")
        lines[at : at + len(search.splitlines())] = replace.splitlines()
        text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    return text


def _braces(text: str) -> int:
    clean = re.sub(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|//[^\n]*|/\*.*?\*/', "", text, flags=re.DOTALL)
    return clean.count("{") - clean.count("}")


def validate(path: str, old: str, new: str) -> None:
    if new == old:
        raise PatchError("the edit changes nothing")
    if path.lower().endswith(BRACE_EXT) and _braces(new) != _braces(old):
        raise PatchError("the edit leaves unbalanced { } braces")
    if path.lower().endswith(".py"):
        try:
            ast.parse(new)
        except SyntaxError as exc:
            raise PatchError(f"Python syntax error after edit, line {exc.lineno}") from exc


def apply(path: str, old: str, patch: str) -> str:
    """Return the new file text, or raise PatchError with a message for the model."""
    if not patch.strip() or len(patch) > MAX_PATCH_CHARS:
        raise PatchError("patch is empty or too large; send a smaller edit")
    new = apply_search_replace(old, patch) if "SEARCH" in patch and "REPLACE" in patch else apply_unified(old, patch)
    validate(path, old, new)
    return new


def diff(path: str, old: str, new: str) -> str:
    lines = difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"{path} (now)", f"{path} (new)")
    return "".join(lines) or "(no change)"
