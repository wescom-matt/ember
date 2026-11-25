"""Tool-calling turn: the model may call run_command on the chat's target.

Bounded: at most MAX_TOOL_STEPS commands per turn, one command per step, a
timeout and output cap per command. A risky command pauses the turn: the
in-flight model context is stored on the pending action, and the turn resumes
when the user clicks Run or Cancel. Credentials never enter the model context.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ember import config, targets, tools
from ember.chat import _event
from ember.classifier import RISKY, classify
from ember.db import connect, now
from ember.ollama import stream_chat
from ember.runner import RunResult, TargetSpec, cap, redact, run_local, run_ssh
from ember.vault import Vault, VaultError

LOG = logging.getLogger("ember.agent")


@dataclass
class AgentCtx:
    db_path: Path
    ollama_url: str
    vault: Vault
    user_id: int
    conversation_id: int
    after_message_id: int
    model: str
    think: bool
    target_id: int
    messages: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    thinking: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    step: int = 0


def tool_prompt(spec: TargetSpec) -> str:
    shell = "PowerShell" if spec.os == "windows" else "bash"
    where = "this computer (the P1)" if spec.kind == "local" else f"{spec.name} ({spec.host}) over SSH"
    return (
        f"\n\nYou can run commands with the run_command tool on target '{spec.name}': {where}, using {shell}.\n"
        "Run one command at a time and read the result before the next. Prefer read-only commands. "
        "Do not install software. For ESP32 work, first check what is installed "
        "(e.g. `command -v arduino-cli esptool.py pio`) and list ports (`ls /dev/ttyUSB* /dev/ttyACM*`). "
        "Flashing, deleting, and system changes will ask the user to confirm. Never ask for passwords. "
        f"Stop after at most {config.MAX_TOOL_STEPS} commands and summarize."
    )


def target_home(spec: TargetSpec) -> str:
    if spec.kind == "local":
        return str(Path.home())
    if spec.os == "windows":
        return f"C:\\Users\\{spec.username}"
    return "/root" if spec.username == "root" else f"/home/{spec.username}"


def to_context(ctx: AgentCtx) -> str:
    data = {"messages": ctx.messages, "text": ctx.text, "thinking": ctx.thinking,
            "sources": ctx.sources, "step": ctx.step, "model": ctx.model, "think": ctx.think}
    raw = json.dumps(data, ensure_ascii=False)
    if len(raw) > config.MAX_CONTEXT_CHARS:
        ctx.messages = ctx.messages[:1] + ctx.messages[-6:]
        data["messages"] = ctx.messages
        raw = json.dumps(data, ensure_ascii=False)
    return raw


def from_context(ctx: AgentCtx, raw: str) -> None:
    data = json.loads(raw or "{}")
    ctx.messages = list(data.get("messages") or [])
    ctx.text = str(data.get("text") or "")
    ctx.thinking = str(data.get("thinking") or "")
    ctx.sources = list(data.get("sources") or [])
    ctx.step = int(data.get("step") or 0)


def _parse_call(call: Any) -> tuple[str, str]:
    fn = call.get("function") if isinstance(call, dict) else None
    if not isinstance(fn, dict) or fn.get("name") != "run_command":
        return "", ""
    args = fn.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return "", ""
    if not isinstance(args, dict):
        return "", ""
    return str(args.get("command") or "").strip(), str(args.get("reason") or "").strip()[:300]


def _record(ctx: AgentCtx, spec: TargetSpec, command: str, reason: str, risk: Any, status: str) -> int:
    with connect(ctx.db_path) as conn:
        cur = conn.execute(
            "INSERT INTO actions(conversation_id, after_message_id, user_id, target_id, target_name, command, reason, "
            "risk, risk_reasons, status, mode, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'none', ?)",
            (ctx.conversation_id, ctx.after_message_id, ctx.user_id, spec.id, spec.name, command, reason,
             risk.level, "; ".join(risk.reasons), status, now()),
        )
        conn.execute("DELETE FROM actions WHERE id <= (SELECT MAX(id) FROM actions) - ?", (20_000,))
        return int(cur.lastrowid or 0)


def _result_text(result: RunResult, secrets: list[str]) -> tuple[str, str]:
    """Return (stored output, text for the model). Both capped and redacted."""
    body = result.output
    if result.error:
        body = (body + "\n" if body else "") + f"[ember] {result.error}"
    clean = redact(body, secrets)
    stored = cap(clean, config.MAX_OUTPUT_STORE)
    code = "none" if result.exit_code is None else str(result.exit_code)
    return stored, f"exit code: {code}\n{cap(clean, config.MAX_OUTPUT_TO_MODEL)}"


def execute_action(ctx: AgentCtx, action_id: int, mode: str) -> tuple[dict[str, Any], str]:
    """Run a recorded action. Permission and target are re-checked here."""
    with connect(ctx.db_path) as conn:
        allowed = tools.exec_allowed(conn, ctx.user_id)
        row = conn.execute("SELECT command, target_id FROM actions WHERE id = ?", (action_id,)).fetchone()
        try:
            spec, secret = targets.resolve(conn, ctx.vault, int(row["target_id"]))
        except (ValueError, VaultError) as exc:
            spec, secret, err = None, None, str(exc)
    if not allowed or spec is None:
        status, text = ("blocked", "Command running is turned off.") if not allowed else ("failed", err)
        _finish(ctx, action_id, status, mode, None, text)
        return {"id": action_id, "status": status, "exit_code": None, "output": text}, f"error: {text}"
    command = str(row["command"])
    if spec.kind == "local":
        result = run_local(command, config.COMMAND_TIMEOUT_SEC)
    else:
        result = run_ssh(spec, secret, command, config.COMMAND_TIMEOUT_SEC)
    secrets = [secret.value] if secret else []
    stored, for_model = _result_text(result, secrets)
    del secret, secrets
    status = "ran" if result.exit_code is not None else "failed"
    with connect(ctx.db_path) as conn:
        if result.new_fingerprint:
            targets.remember_fingerprint(conn, spec.id, result.new_fingerprint)
    _finish(ctx, action_id, status, mode, result.exit_code, stored)
    event = {"id": action_id, "status": status, "exit_code": result.exit_code, "output": stored}
    return event, for_model


def _finish(ctx: AgentCtx, action_id: int, status: str, mode: str, code: int | None, output: str) -> None:
    with connect(ctx.db_path) as conn:
        conn.execute(
            "UPDATE actions SET status = ?, mode = ?, exit_code = ?, output = ?, context = '', finished_at = ? "
            "WHERE id = ?", (status, mode, code, output, now(), action_id),
        )


def _model_step(ctx: AgentCtx, allow_tools: bool, calls: list[Any]) -> Iterator[bytes]:
    """Stream one model call; tool calls are appended to `calls`."""
    step_text: list[str] = []
    if ctx.text and not ctx.text.endswith("\n\n"):
        ctx.text += "\n\n"
    offered = [tools.RUN_COMMAND_TOOL] if allow_tools else None
    for kind, piece in stream_chat(ctx.ollama_url, ctx.model, ctx.messages, ctx.think, offered):
        if kind == "tool_calls":
            calls.extend(piece)
            continue
        if len(ctx.text) + len(ctx.thinking) + len(piece) > config.MAX_REPLY_CHARS:
            yield _event("notice", text="Reply hit the length limit and was cut off.")
            return
        if kind == "content":
            step_text.append(piece)
            ctx.text += piece
            yield _event("token", t=piece)
        else:
            ctx.thinking += piece
            yield _event("think", t=piece)
    if calls:
        ctx.messages.append({"role": "assistant", "content": "".join(step_text), "tool_calls": calls[:1]})


def _handle_call(ctx: AgentCtx, call: Any) -> tuple[list[bytes], bool]:
    """Classify and run (or pause on) one tool call. Returns (events, paused)."""
    command, reason = _parse_call(call)
    ctx.step += 1
    if not command or len(command) > config.MAX_COMMAND_CHARS:
        ctx.messages.append({"role": "tool", "tool_name": "run_command", "content": "error: invalid command"})
        return [], False
    with connect(ctx.db_path) as conn:
        spec, _secret = targets.resolve(conn, ctx.vault, ctx.target_id)
    del _secret
    risk = classify(command, spec.os, target_home(spec))
    action_id = _record(ctx, spec, command, reason, risk, "pending")
    card = {"id": action_id, "target": spec.name, "command": command, "reason": reason,
            "risk": risk.level, "risk_reasons": risk.reasons}
    if risk.level == RISKY:
        with connect(ctx.db_path) as conn:
            conn.execute("UPDATE actions SET context = ? WHERE id = ?", (to_context(ctx), action_id))
        return [_event("confirm", action={**card, "status": "pending"})], True
    result, for_model = execute_action(ctx, action_id, "auto")
    ctx.messages.append({"role": "tool", "tool_name": "run_command", "content": for_model})
    return [_event("action", action={**card, **result, "mode": "auto"})], False


def run_agent(ctx: AgentCtx) -> Iterator[bytes]:
    paused = False
    try:
        for _ in range(config.MAX_TOOL_STEPS + 1):
            calls: list[Any] = []
            yield from _model_step(ctx, ctx.step < config.MAX_TOOL_STEPS, calls)
            if not calls or ctx.step >= config.MAX_TOOL_STEPS:
                break
            events, paused = _handle_call(ctx, calls[0])
            yield from events
            if paused:
                yield _event("paused")
                return
        yield _event("done")
    except (RuntimeError, ValueError, VaultError) as exc:
        LOG.warning("agent turn failed: %s", exc)
        yield _event("error", message=f"Stopped: {str(exc)[:200]}")
    finally:
        if not paused:
            _save_final(ctx)


def _save_final(ctx: AgentCtx) -> None:
    text = ctx.text.strip() or "_(no reply)_"
    with connect(ctx.db_path) as conn:
        t = now()
        conn.execute(
            "INSERT INTO messages(conversation_id, role, content, thinking, sources, model, created_at) "
            "VALUES (?, 'assistant', ?, ?, ?, ?, ?)",
            (ctx.conversation_id, text, ctx.thinking, json.dumps(ctx.sources, ensure_ascii=False), ctx.model, t),
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (t, ctx.conversation_id))


def resume(ctx: AgentCtx, action_id: int, run: bool) -> Iterator[bytes]:
    """Continue a paused turn after the user clicks Run or Cancel."""
    with connect(ctx.db_path) as conn:
        row = conn.execute(
            "SELECT target_name, command, reason, risk, risk_reasons, context FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
    from_context(ctx, row["context"])
    card = {"id": action_id, "target": row["target_name"], "command": row["command"], "reason": row["reason"],
            "risk": row["risk"], "risk_reasons": [r for r in row["risk_reasons"].split("; ") if r]}
    if run:
        result, for_model = execute_action(ctx, action_id, "confirmed")
        yield _event("action", action={**card, **result, "mode": "confirmed"})
    else:
        _finish(ctx, action_id, "cancelled", "none", None, "")
        for_model = "The user cancelled this command. Do not retry it; explain or suggest an alternative."
        yield _event("action", action={**card, "status": "cancelled", "exit_code": None, "output": ""})
    ctx.messages.append({"role": "tool", "tool_name": "run_command", "content": for_model})
    yield from run_agent(ctx)
