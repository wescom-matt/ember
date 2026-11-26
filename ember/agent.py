"""Tool-calling turn: run_command / write_file on the chat's target, the radio
host or the build host, and printer controls when a printer is set up.

Bounded: at most MAX_TOOL_STEPS commands per turn, one command per step, a
timeout and output cap per command. A risky command pauses the turn: the
in-flight model context is stored on the pending action, and the turn resumes
when the user clicks Run or Cancel. Credentials never enter the model context.
"""

from __future__ import annotations

import difflib
import json
import logging
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ember import config, printer, targets, tools
from ember.chat import _event
from ember.classifier import RISKY, SAFE, Risk, classify
from ember.db import connect, now
from ember.ollama import stream_chat
from ember.runner import (
    RunResult,
    TargetSpec,
    cap,
    check_remote_path,
    fetch_file,
    push_file,
    redact,
    run_local,
    run_ssh,
)
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
    hosts: dict[str, int] = field(default_factory=dict)  # role -> target id (radio, build, printer)


MAX_FILE_CHARS = 64_000
MAX_DIFF_CHARS = 12_000


def tool_prompt(spec: TargetSpec | None, names: dict[str, str]) -> str:
    """Short tool guide. `names` maps role -> target name for the radio/build/printer hosts."""
    where = "none"
    if spec is not None:
        shell = "PowerShell" if spec.os == "windows" else "bash"
        where = f"{spec.name} ({'this P1' if spec.kind == 'local' else spec.host}, {shell})"
    hosts = ", ".join(f"{role}={names[role]}" for role in ("radio", "build", "printer") if names.get(role))
    return (
        f"\n\nTools: run_command and write_file, with on=chat ({where}), on=radio or on=build. "
        f"Hosts: {hosts or 'no radio/build host set'}.\n"
        "One command at a time; read the result first. Check before changing: `command -v pio arduino-cli "
        "esptool.py chirpc`, ports `ls /dev/ttyUSB* /dev/ttyACM*`. Build: `pio run`, `arduino-cli compile`. "
        "Fixing: `journalctl -u NAME -n 100 --no-pager`, `systemctl status NAME`; to restart or install use "
        "`sudo -n ...` (fails if a password is needed: then write a script for the user to run). "
        "Change files with write_file (the user sees a diff). Radio uploads are done on the Radio screen. "
        "Flashing, installs, restarts and printer start/cancel ask the user. Never ask for passwords. "
        f"At most {config.MAX_TOOL_STEPS} steps, then summarize."
    )


def target_home(spec: TargetSpec) -> str:
    if spec.kind == "local":
        return str(Path.home())
    if spec.os == "windows":
        return f"C:\\Users\\{spec.username}"
    return "/root" if spec.username == "root" else f"/home/{spec.username}"


def to_context(ctx: AgentCtx) -> str:
    data = {"messages": ctx.messages, "text": ctx.text, "thinking": ctx.thinking,
            "sources": ctx.sources, "step": ctx.step, "model": ctx.model, "think": ctx.think, "hosts": ctx.hosts}
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
    ctx.hosts = {str(k): int(v) for k, v in dict(data.get("hosts") or {}).items()}


def _parse_call(call: Any) -> tuple[str, dict[str, Any]]:
    fn = call.get("function") if isinstance(call, dict) else None
    if not isinstance(fn, dict) or fn.get("name") not in ("run_command", "write_file", "printer"):
        return "", {}
    args = fn.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return "", {}
    return (str(fn["name"]), args) if isinstance(args, dict) else ("", {})


def _record(ctx: AgentCtx, spec: TargetSpec, act: dict[str, Any], risk: Risk, status: str) -> int:
    with connect(ctx.db_path) as conn:
        cur = conn.execute(
            "INSERT INTO actions(conversation_id, after_message_id, user_id, target_id, target_name, command, reason, "
            "risk, risk_reasons, status, mode, kind, payload, diff, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'none', ?, ?, ?, ?)",
            (ctx.conversation_id, ctx.after_message_id, ctx.user_id, spec.id, spec.name, act["command"],
             act["reason"], risk.level, "; ".join(risk.reasons), status, act["kind"],
             json.dumps(act.get("payload") or {}), act.get("diff", ""), now()),
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
        row = conn.execute(
            "SELECT kind, command, payload, target_id FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
        kind = str(row["kind"] or "command")
        try:
            spec, secret = targets.resolve(conn, ctx.vault, int(row["target_id"]), for_commands=kind != "printer")
        except (ValueError, VaultError) as exc:
            spec, secret, err = None, None, str(exc)
    if not allowed or spec is None:
        status, text = ("blocked", "Command running is turned off.") if not allowed else ("failed", err)
        _finish(ctx, action_id, status, mode, None, text)
        return {"id": action_id, "status": status, "exit_code": None, "output": text}, f"error: {text}"
    payload = json.loads(row["payload"] or "{}")
    if kind == "printer":
        result = _run_printer(spec, secret.value if secret else "", payload)
    elif kind == "write_file":
        result = _write_file(spec, secret, str(payload.get("path")), str(payload.get("content")))
    elif spec.kind == "local":
        result = run_local(str(row["command"]), config.COMMAND_TIMEOUT_SEC)
    else:
        result = run_ssh(spec, secret, str(row["command"]), config.COMMAND_TIMEOUT_SEC)
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


def _run_printer(spec: TargetSpec, code: str, payload: dict[str, Any]) -> RunResult:
    try:
        out = printer.run_action(printer.PrinterSpec(spec.host, code), str(payload.get("action")),
                                 str(payload.get("file") or ""))
    except (printer.PrinterError, OSError, ValueError) as exc:
        return RunResult(None, "", str(exc)[:300])
    return RunResult(0, json.dumps(out, ensure_ascii=False)[:4000], "")


def _write_file(spec: TargetSpec, secret: Any, path: str, content: str) -> RunResult:
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "new"
        local.write_text(content, encoding="utf-8")
        prev = Path(tmp) / "prev"
        try:
            if fetch_file(spec, secret, path, prev, MAX_FILE_CHARS * 4).ok:
                push_file(spec, secret, prev, path + ".bak-ember")  # keep the old version
            done = push_file(spec, secret, local, path)
        except (OSError, ValueError) as exc:
            return RunResult(None, "", f"write failed: {str(exc)[:200]}")
    if not done.ok:
        return RunResult(None, "", f"write failed: {done.error}", new_fingerprint=done.new_fingerprint)
    return RunResult(0, f"wrote {done.size} bytes to {path}", "", new_fingerprint=done.new_fingerprint)


def file_diff(spec: TargetSpec, secret: Any, path: str, content: str) -> str:
    """Unified diff of the current file on the target vs the proposed content."""
    old = ""
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "old"
        try:
            got = fetch_file(spec, secret, path, local, MAX_FILE_CHARS * 4)
            if got.ok:
                old = local.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            old = ""
    lines = difflib.unified_diff(old.splitlines(True), content.splitlines(True), f"{path} (now)", f"{path} (new)")
    text = "".join(lines) or "(no change)"
    return cap(text, MAX_DIFF_CHARS)


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
    offered = tools.offered_tools(bool(ctx.hosts.get("printer"))) if allow_tools else None
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


def _plan(ctx: AgentCtx, name: str, args: dict[str, Any]) -> tuple[TargetSpec, dict[str, Any], Risk]:
    """Turn a tool call into (target, action, risk). Raises ValueError with a message for the model."""
    if name == "printer":
        action = str(args.get("action") or "")
        if action not in printer.ACTIONS or not ctx.hosts.get("printer"):
            raise ValueError("no printer is set up" if action in printer.ACTIONS else "unknown printer action")
        file_name = printer.check_filename(str(args["file"])) if action == "start" else ""
        with connect(ctx.db_path) as conn:
            spec, _s = targets.resolve(conn, ctx.vault, ctx.hosts["printer"], for_commands=False)
        risky = action in printer.CONFIRM_ACTIONS
        risk = Risk(RISKY if risky else SAFE, ["changes what the printer is doing"] if risky else [])
        act = {"kind": "printer", "command": f"printer {action} {file_name}".strip(), "payload":
               {"action": action, "file": file_name}}
        return spec, act, risk
    on = str(args.get("on") or "chat")
    target_id = ctx.target_id if on == "chat" else ctx.hosts.get(on, 0)
    if not target_id:
        raise ValueError(f"no {on} host is set; ask the user to pick one")
    with connect(ctx.db_path) as conn:
        spec, secret = targets.resolve(conn, ctx.vault, target_id)
    if name == "write_file":
        path = check_remote_path(str(args.get("path") or ""))
        content = str(args.get("content") or "")
        if len(content) > MAX_FILE_CHARS:
            raise ValueError("file is too large to write this way")
        act = {"kind": "write_file", "command": f"write {path}", "payload": {"path": path, "content": content},
               "diff": file_diff(spec, secret, path, content)}
        return spec, act, Risk(RISKY, ["changes a file (see the diff)"])
    command = str(args.get("command") or "").strip()
    if not command or len(command) > config.MAX_COMMAND_CHARS:
        raise ValueError("invalid command")
    return spec, {"kind": "command", "command": command}, classify(command, spec.os, target_home(spec))


def _handle_call(ctx: AgentCtx, call: Any) -> tuple[list[bytes], bool]:
    """Classify and run (or pause on) one tool call. Returns (events, paused)."""
    name, args = _parse_call(call)
    ctx.step += 1
    try:
        if not name:
            raise ValueError("unknown tool")
        spec, act, risk = _plan(ctx, name, args)
    except (ValueError, VaultError, printer.PrinterError) as exc:
        ctx.messages.append({"role": "tool", "tool_name": name or "tool", "content": f"error: {str(exc)[:200]}"})
        return [], False
    act["reason"] = str(args.get("reason") or "").strip()[:300]
    action_id = _record(ctx, spec, act, risk, "pending")
    card = {"id": action_id, "target": spec.name, "command": act["command"], "reason": act["reason"],
            "risk": risk.level, "risk_reasons": risk.reasons, "kind": act["kind"], "diff": act.get("diff", "")}
    if risk.level == RISKY:
        with connect(ctx.db_path) as conn:
            conn.execute("UPDATE actions SET context = ? WHERE id = ?", (to_context(ctx), action_id))
        return [_event("confirm", action={**card, "status": "pending"})], True
    result, for_model = execute_action(ctx, action_id, "auto")
    ctx.messages.append({"role": "tool", "tool_name": name, "content": for_model})
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
            "SELECT target_name, command, reason, risk, risk_reasons, context, kind, diff FROM actions WHERE id = ?",
            (action_id,),
        ).fetchone()
    from_context(ctx, row["context"])
    card = {"id": action_id, "target": row["target_name"], "command": row["command"], "reason": row["reason"],
            "risk": row["risk"], "risk_reasons": [r for r in row["risk_reasons"].split("; ") if r],
            "kind": row["kind"], "diff": row["diff"]}
    tool_name = {"write_file": "write_file", "printer": "printer"}.get(str(row["kind"]), "run_command")
    if run:
        result, for_model = execute_action(ctx, action_id, "confirmed")
        yield _event("action", action={**card, **result, "mode": "confirmed"})
    else:
        _finish(ctx, action_id, "cancelled", "none", None, "")
        for_model = "The user cancelled this. Do not retry it; explain or suggest an alternative."
        yield _event("action", action={**card, "status": "cancelled", "exit_code": None, "output": ""})
    ctx.messages.append({"role": "tool", "tool_name": tool_name, "content": for_model})
    yield from run_agent(ctx)
