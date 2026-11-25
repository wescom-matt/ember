"""Phase 2 HTTP routes: targets, credentials, master switch, confirm/cancel, audit."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ember import config, ollama, targets, tools
from ember.agent import AgentCtx, resume, run_agent, tool_prompt
from ember.chat import Turn, _event, _retrieve, build_messages, history, run_turn
from ember.db import audit, connect
from ember.deps import Admin, User, _db, _own_conversation
from ember.kb import KnowledgeBase
from ember.runner import cap, redact, run_local, run_ssh
from ember.vault import Vault, VaultError

LOG = logging.getLogger("ember.exec")
ACTION_COLS = (
    "id, after_message_id, target_name, command, reason, risk, risk_reasons, status, mode, exit_code, output, "
    "created_at"
)


class MasterIn(BaseModel):
    exec_enabled: bool


class CredentialIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    kind: str = Field(pattern="^(key|password)$")
    password: str | None = Field(default=None, max_length=config.MAX_PASSWORD)


class TargetIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    kind: str = Field(pattern="^(local|ssh)$")
    host: str = Field(default="", max_length=253)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(default="", max_length=64)
    os: str = Field(default="linux", pattern="^(linux|windows)$")
    credential_id: int | None = None


class TargetPatch(BaseModel):
    enabled: bool | None = None
    reset_fingerprint: bool = False


class DecideIn(BaseModel):
    run: bool


def list_actions(conn: sqlite3.Connection, conv_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {ACTION_COLS} FROM actions WHERE conversation_id = ? ORDER BY id LIMIT ?",  # noqa: S608 # nosec B608
        (conv_id, config.MAX_MESSAGES_PER_CONVERSATION),
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["target"] = item.pop("target_name")
        item["risk_reasons"] = [x for x in str(item["risk_reasons"]).split("; ") if x]
        out.append(item)
    return out


def _vault(request: Request) -> Vault:
    vault: Vault = request.app.state.vault
    return vault


def _fallback(turn: Turn, kb: KnowledgeBase | None, request: Request, why: str) -> Iterator[bytes]:
    settings = request.app.state.settings
    yield _event("notice", text=why)
    yield from run_turn(settings.db_path, settings.ollama_url, kb, turn)


def start_exec_turn(
    request: Request, user_id: int, turn: Turn, kb: KnowledgeBase | None, target_id: int | None, after_id: int
) -> Iterator[bytes]:
    settings = request.app.state.settings
    with connect(_db(request)) as conn:
        allowed = tools.exec_allowed(conn, user_id)
        try:
            spec, _secret = targets.resolve(conn, _vault(request), int(target_id or 0))
            del _secret
        except (ValueError, VaultError):
            spec = None
    if not allowed:
        return _fallback(turn, kb, request, "Command running is off (admin switch or your account). Answering only.")
    if spec is None:
        return _fallback(turn, kb, request, "Pick a target to run commands on. Answering only.")
    try:
        caps = ollama.model_capabilities(settings.ollama_url, turn.model)
    except RuntimeError:
        caps = set()
    if "tools" not in caps:
        why = f"{turn.model} can't run commands (no tool support); try qwen3.5-9b-4k. Answering only."
        return _fallback(turn, kb, request, why)
    ctx = AgentCtx(settings.db_path, settings.ollama_url, _vault(request), user_id, turn.conversation_id,
                   after_id, turn.model, turn.think, spec.id)
    return _exec_stream(ctx, kb, turn.question, tool_prompt(spec))


def _exec_stream(ctx: AgentCtx, kb: KnowledgeBase | None, question: str, prompt: str) -> Iterator[bytes]:
    if kb is not None:
        yield _event("status", text=f"Searching {kb.label}…")
    hits, context, kb_error = _retrieve(kb, question)
    if kb_error:
        yield _event("notice", text=kb_error)
    if kb is not None:
        yield _event("sources", sources=hits)
    with connect(ctx.db_path) as conn:
        past = history(conn, ctx.conversation_id)
    messages: list[dict[str, Any]] = list(build_messages(past, context))
    messages[0]["content"] += prompt
    ctx.messages = messages
    ctx.sources = hits
    yield _event("status", text="Working…")
    yield from run_agent(ctx)


def _claim_action(conn: sqlite3.Connection, action_id: int, user_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT a.id, a.conversation_id, a.target_id, a.context, a.status FROM actions a "
        "JOIN conversations c ON c.id = a.conversation_id WHERE a.id = ? AND a.user_id = ? AND c.user_id = ?",
        (action_id, user_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="action not found")
    cur = conn.execute(
        "UPDATE actions SET mode = 'confirmed' WHERE id = ? AND status = 'pending' AND mode = 'none' AND context != ''",
        (action_id,),
    )
    if cur.rowcount != 1:
        raise HTTPException(status_code=409, detail="this command was already handled or has expired")
    claimed: sqlite3.Row = row
    return claimed


def register_user_exec_routes(app: FastAPI) -> None:
    @app.get("/api/targets")
    def user_targets(user: User, request: Request) -> dict[str, Any]:
        with connect(_db(request)) as conn:
            caps = tools.capabilities(conn, user["id"])
            items = targets.list_targets(conn, enabled_only=True) if caps["can_exec"] else []
        public = [{k: t[k] for k in ("id", "name", "kind", "os", "host")} for t in items]
        return {"targets": public, **caps}

    @app.post("/api/actions/{action_id}/decide")
    def decide(action_id: int, body: DecideIn, user: User, request: Request) -> StreamingResponse:
        settings = request.app.state.settings
        with connect(_db(request)) as conn:
            if body.run and not tools.exec_allowed(conn, user["id"]):
                raise HTTPException(status_code=403, detail="command running is turned off")
            row = _claim_action(conn, action_id, user["id"])
            _own_conversation(conn, int(row["conversation_id"]), user["id"])
            model = str(json.loads(row["context"]).get("model") or settings.default_model)
            think = bool(json.loads(row["context"]).get("think"))
            audit(conn, user["id"], "command_confirmed" if body.run else "command_cancelled", f"action={action_id}")
        ctx = AgentCtx(settings.db_path, settings.ollama_url, _vault(request), user["id"],
                       int(row["conversation_id"]), 0, model, think, int(row["target_id"] or 0))
        with connect(_db(request)) as conn:
            after = conn.execute("SELECT after_message_id FROM actions WHERE id = ?", (action_id,)).fetchone()
        ctx.after_message_id = int(after["after_message_id"])
        stream = resume(ctx, action_id, body.run)
        return StreamingResponse(stream, media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})


def register_admin_exec_routes(app: FastAPI) -> None:
    @app.get("/api/admin/exec")
    def admin_exec(admin: Admin, request: Request) -> dict[str, Any]:
        with connect(_db(request)) as conn:
            return {
                "exec_enabled": tools.master_on(conn),
                "targets": targets.list_targets(conn, enabled_only=False),
                "credentials": targets.list_credentials(conn),
            }

    @app.put("/api/admin/exec")
    def set_master(body: MasterIn, admin: Admin, request: Request) -> dict[str, bool]:
        with connect(_db(request)) as conn:
            tools.set_master(conn, body.exec_enabled)
            audit(conn, admin["id"], "exec_master", "on" if body.exec_enabled else "off")
        return {"exec_enabled": body.exec_enabled}

    @app.post("/api/admin/credentials")
    def add_credential(body: CredentialIn, admin: Admin, request: Request) -> dict[str, Any]:
        with connect(_db(request)) as conn:
            try:
                if body.kind == "key":
                    item = targets.add_key_credential(conn, _vault(request), body.name)
                else:
                    item = targets.add_password_credential(conn, _vault(request), body.name, body.password or "")
            except (ValueError, VaultError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            audit(conn, admin["id"], "credential_added", f"id={item['id']} kind={body.kind}")
        return item

    @app.delete("/api/admin/credentials/{cred_id}")
    def delete_credential(cred_id: int, admin: Admin, request: Request) -> dict[str, bool]:
        with connect(_db(request)) as conn:
            cur = conn.execute("DELETE FROM credentials WHERE id = ?", (cred_id,))
            if cur.rowcount != 1:
                raise HTTPException(status_code=404, detail="no such credential")
            audit(conn, admin["id"], "credential_deleted", f"id={cred_id}")
        return {"ok": True}

    register_target_routes(app)


def register_target_routes(app: FastAPI) -> None:
    @app.post("/api/admin/targets")
    def add_target(body: TargetIn, admin: Admin, request: Request) -> dict[str, Any]:
        with connect(_db(request)) as conn:
            try:
                target_id = targets.save_target(conn, targets.validate_target(body.model_dump()), None)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            audit(conn, admin["id"], "target_added", f"id={target_id}")
        return {"id": target_id}

    @app.put("/api/admin/targets/{target_id}")
    def edit_target(target_id: int, body: TargetIn, admin: Admin, request: Request) -> dict[str, bool]:
        with connect(_db(request)) as conn:
            try:
                targets.save_target(conn, targets.validate_target(body.model_dump()), target_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            audit(conn, admin["id"], "target_changed", f"id={target_id}")
        return {"ok": True}

    @app.patch("/api/admin/targets/{target_id}")
    def patch_target(target_id: int, body: TargetPatch, admin: Admin, request: Request) -> dict[str, bool]:
        with connect(_db(request)) as conn:
            if not conn.execute("SELECT 1 FROM targets WHERE id = ?", (target_id,)).fetchone():
                raise HTTPException(status_code=404, detail="no such target")
            if body.enabled is not None:
                conn.execute("UPDATE targets SET enabled = ? WHERE id = ?", (int(body.enabled), target_id))
            if body.reset_fingerprint:
                conn.execute("UPDATE targets SET host_fingerprint = '' WHERE id = ?", (target_id,))
            audit(conn, admin["id"], "target_changed", f"id={target_id}")
        return {"ok": True}

    @app.delete("/api/admin/targets/{target_id}")
    def delete_target(target_id: int, admin: Admin, request: Request) -> dict[str, bool]:
        with connect(_db(request)) as conn:
            if conn.execute("DELETE FROM targets WHERE id = ?", (target_id,)).rowcount != 1:
                raise HTTPException(status_code=404, detail="no such target")
            audit(conn, admin["id"], "target_deleted", f"id={target_id}")
        return {"ok": True}

    @app.post("/api/admin/targets/{target_id}/test")
    def test_target(target_id: int, admin: Admin, request: Request) -> dict[str, Any]:
        with connect(_db(request)) as conn:
            try:
                spec, secret = targets.resolve(conn, _vault(request), target_id)
            except (ValueError, VaultError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        probe = "Write-Output ember-ok" if spec.os == "windows" else "echo ember-ok"
        if spec.kind == "local":
            result = run_local(probe, config.SSH_CONNECT_TIMEOUT_SEC)
        else:
            result = run_ssh(spec, secret, probe, config.SSH_CONNECT_TIMEOUT_SEC * 2)
        text = redact(cap(result.output + (f"\n{result.error}" if result.error else ""), 500),
                      [secret.value] if secret else [])
        del secret
        with connect(_db(request)) as conn:
            if result.new_fingerprint:
                targets.remember_fingerprint(conn, spec.id, result.new_fingerprint)
            audit(conn, admin["id"], "target_tested", f"id={target_id} exit={result.exit_code}")
            fp = conn.execute("SELECT host_fingerprint FROM targets WHERE id = ?", (target_id,)).fetchone()
        ok = result.exit_code == 0 and "ember-ok" in result.output
        return {"ok": ok, "output": text.strip(), "fingerprint": fp["host_fingerprint"] if fp else ""}

    @app.get("/api/admin/audit")
    def audit_log(admin: Admin, request: Request, limit: int = 200) -> dict[str, Any]:
        n = max(1, min(limit, 1000))
        with connect(_db(request)) as conn:
            actions = conn.execute(
                "SELECT a.id, a.created_at, a.finished_at, u.username, a.target_name, a.command, a.risk, "
                "a.risk_reasons, a.status, a.mode, a.exit_code FROM actions a LEFT JOIN users u ON u.id = a.user_id "
                "ORDER BY a.id DESC LIMIT ?", (n,),
            ).fetchall()
            events = conn.execute(
                "SELECT e.at, u.username, e.event, e.detail FROM audit e LEFT JOIN users u ON u.id = e.user_id "
                "ORDER BY e.id DESC LIMIT ?", (n,),
            ).fetchall()
        return {"actions": [dict(r) for r in actions], "events": [dict(r) for r in events]}


def register_exec_routes(app: FastAPI) -> None:
    register_user_exec_routes(app)
    register_admin_exec_routes(app)
