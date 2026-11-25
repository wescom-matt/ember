"""Timed, size-capped JSON HTTP to loopback only."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from nomad_search.config import MAX_HTTP_BYTES, require_local_http_url


def post_json(url: str, payload: dict[str, Any], timeout_sec: int) -> dict[str, Any]:
    origin = url.split("/", 3)
    if len(origin) < 3:
        raise ValueError("bad url")
    # Re-check the origin of the full URL (scheme://host[:port]/...).
    parts = url.split("/", 3)
    origin_only = f"{parts[0]}//{parts[2]}"
    require_local_http_url(origin_only, "request url")
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "nomad-search/1.0",
        },
        method="POST",
    )
    return _read_json(request, timeout_sec)


def _read_json(request: urllib.request.Request, timeout_sec: int) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            status = int(getattr(response, "status", 0) or 0)
            if status < 200 or status >= 300:
                raise RuntimeError(f"HTTP {status}")
            raw = response.read(MAX_HTTP_BYTES + 1)
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read(512)
        except OSError:
            err_body = b""
        detail = err_body.decode("utf-8", "replace").strip().replace("\n", " ")
        if len(detail) > 200:
            detail = detail[:200]
        raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
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
