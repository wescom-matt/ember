"""Timed, size-capped JSON HTTP to loopback services only (adapted from nomad-search)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

from ember.config import MAX_HTTP_BYTES, require_loopback_url

MAX_LINE_BYTES = 1_000_000


def _check_origin(url: str) -> None:
    parts = url.split("/", 3)
    if len(parts) < 3:
        raise ValueError("bad url")
    require_loopback_url(f"{parts[0]}//{parts[2]}", "request url")


def _request(url: str, payload: dict[str, Any] | None) -> urllib.request.Request:
    _check_origin(url)
    headers = {"Accept": "application/json", "User-Agent": "ember/1"}
    data = None
    method = "GET"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    return urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310 - loopback http checked above


def _http_error(exc: urllib.error.HTTPError) -> RuntimeError:
    try:
        body = exc.read(300)
    except OSError:
        body = b""
    detail = body.decode("utf-8", "replace").strip().replace("\n", " ")[:200]
    return RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}")


def call_json(url: str, payload: dict[str, Any] | None, timeout_sec: int) -> dict[str, Any]:
    request = _request(url, payload)
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:  # noqa: S310 # nosec B310
            raw = response.read(MAX_HTTP_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("request timed out") from exc
    if len(raw) > MAX_HTTP_BYTES:
        raise RuntimeError("response too large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("response was not JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("response JSON must be an object")
    return data


def stream_ndjson(url: str, payload: dict[str, Any], timeout_sec: int, max_lines: int) -> Iterator[dict[str, Any]]:
    """Yield JSON objects from a newline-delimited stream, with a line cap."""
    request = _request(url, payload)
    try:
        response = urllib.request.urlopen(request, timeout=timeout_sec)  # noqa: S310 # nosec B310
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("request timed out") from exc
    with response:
        for _ in range(max_lines):
            line = response.readline(MAX_LINE_BYTES)
            if not line:
                return
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError("stream sent bad JSON") from exc
            if isinstance(item, dict):
                yield item
        raise RuntimeError("stream exceeded line limit")
