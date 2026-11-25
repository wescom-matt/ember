"""Stdio MCP server exposing search_knowledge. Speaks only on stdio."""

from __future__ import annotations

import json
import sys
from typing import Any

from nomad_search import __version__, config
from nomad_search.format import format_hits
from nomad_search.search import search_knowledge

PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOL_VERSIONS = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
)
SERVER_NAME = "nomad-search"
# If the client speaks newline-delimited JSON, reply the same way.
# Goose 1.59's rmcp transport expects that; official MCP uses Content-Length.
_use_headers = True
TOOL_NAME = "search_knowledge"
TOOL_DESCRIPTION = (
    "Search the local Nomad knowledge base for medicine, first aid, repair, DIY, "
    "ham radio, outdoors, and other offline references. Use this for factual "
    "questions. Returns cited text passages with source titles. Read-only."
)


def _read_message(stdin: Any) -> dict[str, Any] | None:
    global _use_headers
    headers: dict[str, str] = {}
    while True:
        line = stdin.readline()
        if not line:
            return None
        if line.startswith(b"{") or line.startswith(b"["):
            _use_headers = False
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"bad json: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError("message must be an object")
            return obj
        if line in (b"\r\n", b"\n"):
            break
        try:
            text = line.decode("ascii", "strict").strip()
        except UnicodeDecodeError as exc:
            raise ValueError("bad header") from exc
        if ":" not in text:
            raise ValueError("bad header")
        key, value = text.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    _use_headers = True
    raw_len = headers.get("content-length")
    if raw_len is None:
        raise ValueError("missing Content-Length")
    try:
        length = int(raw_len)
    except ValueError as exc:
        raise ValueError("bad Content-Length") from exc
    if length < 0 or length > config.MAX_MCP_BYTES:
        raise ValueError("Content-Length out of range")
    body = stdin.read(length)
    if len(body) != length:
        raise ValueError("truncated message")
    try:
        obj = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("bad json") from exc
    if not isinstance(obj, dict):
        raise ValueError("message must be an object")
    return obj


def _write_message(stdout: Any, obj: dict[str, Any]) -> None:
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > config.MAX_MCP_BYTES:
        raise ValueError("outgoing message too large")
    if _use_headers:
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        stdout.write(header + body)
    else:
        stdout.write(body + b"\n")
    stdout.flush()


def _result(msg_id: object, result: object) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: object, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message[:300]}}


def _tools() -> list[dict[str, Any]]:
    return [
        {
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The question or search phrase",
                        "maxLength": config.MAX_QUERY_CHARS,
                    },
                    "top_k": {
                        "type": "integer",
                        "description": f"How many passages to return (1-{config.MAX_TOP_K}, default {config.DEFAULT_TOP_K})",
                        "minimum": 1,
                        "maximum": config.MAX_TOP_K,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        }
    ]


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    msg_id = message.get("id")
    if not isinstance(method, str):
        if msg_id is not None:
            return _error(msg_id, -32600, "invalid request")
        return None
    if msg_id is None:
        return None
    if method == "initialize":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        return _result(
            msg_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
            },
        )
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": _tools()})
    if method == "resources/list":
        return _result(msg_id, {"resources": []})
    if method == "prompts/list":
        return _result(msg_id, {"prompts": []})
    if method == "tools/call":
        return _call_tool(msg_id, message.get("params"))
    return _error(msg_id, -32601, f"method not found: {method}")


def _call_tool(msg_id: object, params: object) -> dict[str, Any]:
    if not isinstance(params, dict):
        return _error(msg_id, -32602, "invalid params")
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name != TOOL_NAME:
        return _error(msg_id, -32602, f"unknown tool: {name}")
    if not isinstance(arguments, dict):
        return _error(msg_id, -32602, "arguments must be an object")
    query = arguments.get("query")
    top_k = arguments.get("top_k")
    try:
        hits = search_knowledge(query, top_k)
        clean = config.sanitize_query(query)
        text = format_hits(clean, hits)
    except ValueError as exc:
        return _error(msg_id, -32602, str(exc))
    except (RuntimeError, OSError) as exc:
        return _result(
            msg_id,
            {"content": [{"type": "text", "text": f"Search failed: {exc}"}], "isError": True},
        )
    return _result(msg_id, {"content": [{"type": "text", "text": text}], "isError": False})


def main() -> int:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        try:
            message = _read_message(stdin)
        except ValueError as exc:
            _write_message(stdout, _error(None, -32700, str(exc)))
            continue
        if message is None:
            return 0
        reply = _handle(message)
        if reply is not None:
            _write_message(stdout, reply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
