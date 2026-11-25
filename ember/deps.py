"""Shared request dependencies: auth, ownership, and input checks."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

from ember import auth, ollama
from ember.db import connect
from ember.kb import KnowledgeBase

LOG = logging.getLogger("ember")
COOKIE = "ember_session"


def _db(request: Request) -> Path:
    path: Path = request.app.state.settings.db_path
    return path


def current_user(request: Request) -> dict[str, Any]:
    with connect(_db(request)) as conn:
        row = auth.session_user(conn, request.cookies.get(COOKIE))
    if row is None:
        raise HTTPException(status_code=401, detail="sign in required")
    return {"id": int(row["id"]), "username": row["username"], "is_admin": bool(row["is_admin"])}


def admin_user(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="admin only")
    return user


User = Annotated[dict[str, Any], Depends(current_user)]
Admin = Annotated[dict[str, Any], Depends(admin_user)]


def _own_conversation(conn: sqlite3.Connection, conv_id: int, user_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, title, model, kb, exec_on, target_id, created_at, updated_at FROM conversations "
        "WHERE id = ? AND user_id = ?",
        (conv_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="chat not found")
    conv: sqlite3.Row = row
    return conv


def _check_kb(request: Request, kb_id: str) -> KnowledgeBase | None:
    if kb_id == "none":
        return None
    registry: dict[str, KnowledgeBase] = request.app.state.kbs
    kb = registry.get(kb_id)
    if kb is None:
        raise HTTPException(status_code=400, detail="unknown knowledge base")
    return kb


def _check_model(request: Request, name: str) -> str:
    try:
        installed = ollama.model_names(request.app.state.settings.ollama_url)
    except RuntimeError as exc:
        LOG.warning("ollama model list failed: %s", exc)
        raise HTTPException(status_code=503, detail="Ollama is not responding") from exc
    model = ollama.normalize_model(name, installed)
    if model is None:
        raise HTTPException(status_code=400, detail="model is not installed")
    return model
