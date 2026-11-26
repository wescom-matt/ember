"""Ember web app (FastAPI)."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ember import __version__, auth, config, ollama, projects, tools
from ember.chat import Turn, run_turn
from ember.config import Settings
from ember.db import audit, connect, init_db, now
from ember.deps import COOKIE, Admin, User, _check_kb, _check_model, _db, _own_conversation
from ember.kb import KnowledgeBase, build_registry, describe
from ember.routes_devices import register_device_routes
from ember.routes_exec import list_actions, register_exec_routes, start_exec_turn
from ember.vault import Vault

LOG = logging.getLogger("ember")
STATIC_DIR = Path(__file__).resolve().parent / "static"
CSRF_HEADER = "x-ember"
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=config.MAX_USERNAME)
    password: str = Field(min_length=1, max_length=config.MAX_PASSWORD)


class PasswordIn(BaseModel):
    current: str = Field(min_length=1, max_length=config.MAX_PASSWORD)
    new: str = Field(min_length=config.MIN_PASSWORD, max_length=config.MAX_PASSWORD)


class ConversationIn(BaseModel):
    model: str = Field(default="", max_length=100)
    kb: str = Field(default="none", max_length=32)


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=config.MAX_TITLE)
    model: str | None = Field(default=None, max_length=100)
    kb: str | None = Field(default=None, max_length=32)
    exec_on: bool | None = None
    target_id: int | None = None


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=config.MAX_MESSAGE_CHARS)
    model: str = Field(min_length=1, max_length=100)
    kb: str = Field(default="none", max_length=32)
    think: bool = False
    exec: bool = False
    target_id: int | None = None
    project: str = Field(default="", max_length=80)
    small_steps: bool = False


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=config.MAX_USERNAME)
    password: str = Field(min_length=config.MIN_PASSWORD, max_length=config.MAX_PASSWORD)
    is_admin: bool = False


class UserPatch(BaseModel):
    is_admin: bool | None = None
    is_active: bool | None = None
    can_exec: bool | None = None
    password: str | None = Field(default=None, min_length=config.MIN_PASSWORD, max_length=config.MAX_PASSWORD)


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def register_auth_routes(app: FastAPI) -> None:
    @app.post("/api/login")
    def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
        settings: Settings = request.app.state.settings
        with connect(_db(request)) as conn:
            try:
                row = auth.authenticate(conn, body.username, body.password)
            except auth.AuthError as exc:
                raise HTTPException(status_code=401, detail=str(exc)) from exc
            token = auth.new_session(conn, int(row["id"]))
            audit(conn, int(row["id"]), "login_ok")
        response.set_cookie(
            COOKIE, token, max_age=config.SESSION_HOURS * 3600, httponly=True,
            samesite="strict", secure=settings.secure_cookies, path="/",
        )
        return {"username": row["username"], "is_admin": bool(row["is_admin"])}

    @app.post("/api/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        with connect(_db(request)) as conn:
            auth.end_session(conn, request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/me")
    def me(user: User) -> dict[str, Any]:
        return user

    @app.post("/api/me/password")
    def change_password(body: PasswordIn, user: User, request: Request) -> dict[str, bool]:
        with connect(_db(request)) as conn:
            row = conn.execute("SELECT pw_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
            if row is None or not auth.verify_password(row["pw_hash"], body.current):
                raise HTTPException(status_code=400, detail="current password is wrong")
            try:
                auth.set_password(conn, user["id"], body.new)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            audit(conn, user["id"], "password_changed")
        return {"ok": True}


def register_chat_routes(app: FastAPI) -> None:
    @app.get("/api/models")
    def models(user: User, request: Request) -> dict[str, Any]:
        settings: Settings = request.app.state.settings
        try:
            items = ollama.list_models(settings.ollama_url)
        except RuntimeError as exc:
            LOG.warning("ollama model list failed: %s", exc)
            raise HTTPException(status_code=503, detail="Ollama is not responding") from exc
        names = {m["name"] for m in items}
        default = ollama.normalize_model(settings.default_model, names) or (items[0]["name"] if items else "")
        return {"models": items, "default": default}

    @app.get("/api/kbs")
    def kbs(user: User, request: Request) -> dict[str, Any]:
        return {"kbs": describe(request.app.state.kbs), "default": "nomad"}

    @app.get("/api/conversations")
    def list_conversations(user: User, request: Request, q: str = "") -> dict[str, Any]:
        term = " ".join(q.split())[: config.MAX_SEARCH_CHARS]
        sql = "SELECT id, title, model, kb, updated_at FROM conversations c WHERE user_id = ?"
        args: list[Any] = [user["id"]]
        if term:
            sql += (
                " AND (title LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM messages m"
                " WHERE m.conversation_id = c.id AND m.content LIKE ? ESCAPE '\\'))"
            )
            args += [_like(term), _like(term)]
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(config.MAX_CONVERSATIONS_LIST)
        with connect(_db(request)) as conn:
            rows = conn.execute(sql, args).fetchall()
        return {"conversations": [dict(r) for r in rows]}

    @app.post("/api/conversations")
    def new_conversation(body: ConversationIn, user: User, request: Request) -> dict[str, Any]:
        _check_kb(request, body.kb)
        model = body.model or request.app.state.settings.default_model
        t = now()
        with connect(_db(request)) as conn:
            cur = conn.execute(
                "INSERT INTO conversations(user_id, title, model, kb, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user["id"], "New chat", model, body.kb, t, t),
            )
            conv_id = int(cur.lastrowid or 0)
        return {"id": conv_id, "title": "New chat", "model": model, "kb": body.kb, "updated_at": t}

    @app.get("/api/conversations/{conv_id}")
    def get_conversation(conv_id: int, user: User, request: Request) -> dict[str, Any]:
        with connect(_db(request)) as conn:
            conv = _own_conversation(conn, conv_id, user["id"])
            rows = conn.execute(
                "SELECT id, role, content, thinking, sources, model, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY id LIMIT ?",
                (conv_id, config.MAX_MESSAGES_PER_CONVERSATION),
            ).fetchall()
            actions = list_actions(conn, conv_id)
        messages = []
        for r in rows:
            item = dict(r)
            item["sources"] = json.loads(r["sources"] or "[]")
            messages.append(item)
        return {"conversation": dict(conv), "messages": messages, "actions": actions}

    @app.patch("/api/conversations/{conv_id}")
    def patch_conversation(conv_id: int, body: ConversationPatch, user: User, request: Request) -> dict[str, Any]:
        if body.kb is not None:
            _check_kb(request, body.kb)
        with connect(_db(request)) as conn:
            conv = _own_conversation(conn, conv_id, user["id"])
            title = body.title.strip() if body.title else conv["title"]
            exec_on = conv["exec_on"] if body.exec_on is None else int(body.exec_on)
            target_id = conv["target_id"] if body.target_id is None else body.target_id
            conn.execute(
                "UPDATE conversations SET title = ?, model = ?, kb = ?, exec_on = ?, target_id = ? WHERE id = ?",
                (title or conv["title"], body.model or conv["model"], body.kb or conv["kb"],
                 exec_on, target_id, conv_id),
            )
        return {"ok": True}

    @app.delete("/api/conversations/{conv_id}")
    def delete_conversation(conv_id: int, user: User, request: Request) -> dict[str, bool]:
        with connect(_db(request)) as conn:
            _own_conversation(conn, conv_id, user["id"])
            conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        return {"ok": True}

    @app.post("/api/conversations/{conv_id}/messages")
    def send_message(conv_id: int, body: MessageIn, user: User, request: Request) -> StreamingResponse:
        settings: Settings = request.app.state.settings
        kb = _check_kb(request, body.kb)
        model = _check_model(request, body.model)
        think = body.think and _thinks(settings.ollama_url, model)
        if body.project and not any(p["name"] == body.project for p in projects.load(settings.data_dir)):
            raise HTTPException(status_code=400, detail="unknown project")
        with connect(_db(request)) as conn:
            conv = _own_conversation(conn, conv_id, user["id"])
            count = conn.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conv_id,)).fetchone()[0]
            if count >= config.MAX_MESSAGES_PER_CONVERSATION - 1:
                raise HTTPException(status_code=400, detail="this chat is full; start a new one")
            t = now()
            cur = conn.execute(
                "INSERT INTO messages(conversation_id, role, content, model, created_at) VALUES (?, 'user', ?, ?, ?)",
                (conv_id, body.content, model, t),
            )
            user_msg_id = int(cur.lastrowid or 0)
            conn.execute(
                "UPDATE actions SET status = 'expired', context = '' WHERE conversation_id = ? AND status = 'pending'",
                (conv_id,),
            )
            title = conv["title"]
            if title == "New chat":
                title = " ".join(body.content.split())[:60] or "New chat"
            conn.execute(
                "UPDATE conversations SET title = ?, model = ?, kb = ?, exec_on = ?, target_id = ?, updated_at = ?, "
                "project = ?, small_steps = ? WHERE id = ?",
                (title, model, body.kb, int(body.exec), body.target_id, t, body.project, int(body.small_steps),
                 conv_id),
            )
        turn = Turn(conversation_id=conv_id, model=model, kb_id=body.kb, think=think, question=body.content,
                    project=body.project, small_steps=body.small_steps, data_dir=settings.data_dir)
        if body.exec:
            stream = start_exec_turn(request, user["id"], turn, kb, body.target_id, user_msg_id)
        else:
            stream = run_turn(settings.db_path, settings.ollama_url, kb, turn)
        return StreamingResponse(stream, media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})


def _thinks(ollama_url: str, model: str) -> bool:
    try:
        return ollama.supports_thinking(ollama_url, model)
    except RuntimeError as exc:
        LOG.warning("model capability check failed: %s", exc)
        return False


def register_admin_routes(app: FastAPI) -> None:
    @app.get("/api/admin/users")
    def list_users(admin: Admin, request: Request) -> dict[str, Any]:
        with connect(_db(request)) as conn:
            rows = conn.execute(
                "SELECT id, username, is_admin, is_active, can_exec, created_at FROM users ORDER BY username LIMIT ?",
                (config.MAX_USERS,),
            ).fetchall()
        return {"users": [dict(r) for r in rows]}

    @app.post("/api/admin/users")
    def add_user(body: UserIn, admin: Admin, request: Request) -> dict[str, Any]:
        with connect(_db(request)) as conn:
            try:
                user_id = auth.create_user(conn, body.username, body.password, body.is_admin)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            audit(conn, admin["id"], "user_created", f"id={user_id} admin={int(body.is_admin)}")
        return {"id": user_id}

    @app.patch("/api/admin/users/{user_id}")
    def edit_user(user_id: int, body: UserPatch, admin: Admin, request: Request) -> dict[str, bool]:
        with connect(_db(request)) as conn:
            row = conn.execute("SELECT id, is_admin, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="no such user")
            _guard_last_admin(conn, row, body)
            _apply_user_patch(conn, user_id, body)
            audit(conn, admin["id"], "user_changed", f"id={user_id} fields={_patch_fields(body)}")
        return {"ok": True}


def _patch_fields(body: UserPatch) -> str:
    return ",".join(k for k, v in body.model_dump().items() if v is not None)


def _guard_last_admin(conn: sqlite3.Connection, row: sqlite3.Row, body: UserPatch) -> None:
    losing = (body.is_admin is False) or (body.is_active is False)
    if row["is_admin"] and row["is_active"] and losing and auth.active_admin_count(conn) <= 1:
        raise HTTPException(status_code=400, detail="keep at least one active admin")


def _apply_user_patch(conn: sqlite3.Connection, user_id: int, body: UserPatch) -> None:
    if body.is_admin is not None:
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(body.is_admin), user_id))
    if body.is_active is not None:
        conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(body.is_active), user_id))
        if not body.is_active:
            auth.end_all_sessions(conn, user_id)
    if body.can_exec is not None:
        conn.execute("UPDATE users SET can_exec = ? WHERE id = ?", (int(body.can_exec), user_id))
    if body.password is not None:
        try:
            auth.set_password(conn, user_id, body.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def create_app(settings: Settings, kbs: dict[str, KnowledgeBase] | None = None) -> FastAPI:
    init_db(settings.db_path)
    app = FastAPI(title="Ember", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    if kbs is None:
        kbs = build_registry(settings.ollama_url, settings.qdrant_url, settings.data_dir)
    app.state.kbs = kbs
    app.state.vault = Vault(settings.secret_key_file)

    @app.middleware("http")
    async def guard(request: Request, call_next: Any) -> Response:
        is_write = request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD")
        if is_write and request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse({"detail": "missing request header"}, status_code=403)
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get("/api/version")
    def version() -> dict[str, str]:
        return {"version": __version__}

    @app.get("/api/capabilities")
    def capabilities(user: User, request: Request) -> dict[str, bool]:
        with connect(_db(request)) as conn:
            return tools.capabilities(conn, user["id"])

    register_auth_routes(app)
    register_chat_routes(app)
    register_admin_routes(app)
    register_exec_routes(app)
    register_device_routes(app)
    app.mount("/static", StaticFiles(directory=STATIC_DIR, html=False), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app
