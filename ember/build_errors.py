"""Trim long build output to the first real error(s) plus nearby source lines.

Handles gcc/clang (PlatformIO, Arduino, cmake builds), CMake, Dart/Flutter,
dotnet/MSBuild and Python tracebacks. Anything else falls back to the first
lines that mention an error. The small model then sees ~1 KB instead of 8 KB.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

MAX_ERRORS = 2
MAX_CHARS = 1600
MIN_OUTPUT_CHARS = 600
SOURCE_RADIUS = 2
MAX_SCAN_LINES = 5000

PATTERNS = (
    (
        "dotnet",
        re.compile(r"^\s*(?P<file>[^\s(][^(\n]*?)\((?P<line>\d+),(?P<col>\d+)\):\s*error\s+(?P<msg>\w+:.*)$"),
    ),
    ("dart", re.compile(r"^(?P<file>[^\s:][^:\n]*\.dart):(?P<line>\d+):(?P<col>\d+):\s*Error:\s*(?P<msg>.*)$")),
    (
        "gcc",
        re.compile(
            r"^(?P<file>(?:[A-Za-z]:)?[^\s:][^:\n]*):(?P<line>\d+):(?:(?P<col>\d+):)?"
            r"\s*(?:fatal )?error:\s*(?P<msg>.*)$"
        ),
    ),
    ("cmake", re.compile(r"^CMake Error at (?P<file>[^:\n]+):(?P<line>\d+)")),
)
GENERIC = re.compile(r"\berror\b|\*\*\* \[.*\] Error|FAILED|undefined reference", re.IGNORECASE)


@dataclass(frozen=True)
class BuildError:
    kind: str
    file: str
    line: int
    msg: str
    after: tuple[str, ...]


def find_errors(output: str) -> list[BuildError]:
    lines = output.splitlines()[:MAX_SCAN_LINES]
    found: list[BuildError] = []
    seen: set[tuple[str, int, str]] = set()
    for i, raw in enumerate(lines):
        for kind, pat in PATTERNS:
            m = pat.match(raw.rstrip())
            if not m:
                continue
            msg = m.groupdict().get("msg") or next((x.strip() for x in lines[i + 1 : i + 4] if x.strip()), "")
            key = (m["file"], int(m["line"]), msg)
            if key not in seen:
                seen.add(key)
                after = tuple(x.rstrip() for x in lines[i + 1 : i + 3] if x.strip() and not _is_error(x))
                found.append(BuildError(kind, m["file"].strip(), int(m["line"]), msg.strip()[:300], after))
            break
        if len(found) >= MAX_ERRORS + 8:
            break
    return found


def _is_error(line: str) -> bool:
    return any(p.match(line.rstrip()) for _k, p in PATTERNS)


def _traceback(output: str) -> str:
    idx = output.rfind("Traceback (most recent call last)")
    if idx < 0:
        return ""
    tail = output[idx:].splitlines()
    return "\n".join(tail[:1] + tail[-6:])


def _source(lookup: Callable[[str], str | None] | None, err: BuildError) -> str:
    if lookup is None:
        return ""
    text = lookup(err.file)
    if not text:
        return ""
    src = text.splitlines()
    lo, hi = max(1, err.line - SOURCE_RADIUS), min(len(src), err.line + SOURCE_RADIUS)
    return "\n".join(f"{'>' if n == err.line else ' '}{n:5}| {src[n - 1][:160]}" for n in range(lo, hi + 1))


def trim(output: str, exit_code: int | None, lookup: Callable[[str], str | None] | None = None) -> str | None:
    """Short error summary for the model, or None when the output should go as-is."""
    if exit_code in (0, None) or len(output) < MIN_OUTPUT_CHARS:
        return None
    errors = find_errors(output)
    parts = [f"Build/command failed (exit {exit_code}). First error(s), trimmed by Ember:"]
    if errors:
        for n, e in enumerate(errors[:MAX_ERRORS], 1):
            parts.append(f"{n}. {e.file}:{e.line}: {e.msg}")
            parts.extend(f"   {a[:200]}" for a in e.after)
            src = _source(lookup, e)
            if src:
                parts.append(src)
        if len(errors) > MAX_ERRORS:
            parts.append(f"({len(errors) - MAX_ERRORS} more errors hidden; fix the first one and rebuild.)")
    else:
        tb = _traceback(output)
        generic = [x.strip()[:200] for x in output.splitlines()[:MAX_SCAN_LINES] if GENERIC.search(x)][:4]
        if not tb and not generic:
            return None
        parts.append(tb or "\n".join(generic))
    parts.append("Last lines:\n" + "\n".join(output.rstrip().splitlines()[-3:]))
    text = "\n".join(parts)
    return text[:MAX_CHARS]
