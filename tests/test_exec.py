from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ember import agent, ollama
from ember.classifier import RISKY, SAFE, classify
from ember.runner import HostKeyChanged, RunResult, _TofuPolicy, cap, redact, windows_wrap
from ember.vault import Vault, VaultError
from tests.conftest import ADMIN_PW, USER_PW, login

HOME = "/home/matt"
WIN_HOME = "C:\\Users\\Matt"
SECRET_PW = "hunter2-very-secret"


@pytest.mark.parametrize(
    "cmd",
    [
        "df -h",
        "ls -la ~ | head -20",
        "cat /etc/os-release && uname -a",
        "echo hi > ~/notes.txt",
        "arduino-cli compile -b esp32:esp32:esp32 ~/blink",
        "command -v arduino-cli esptool.py pio",
        "ls /dev/ttyUSB* /dev/ttyACM*",
        "systemctl status ember",
        "esptool.py --port /dev/ttyUSB0 chip_id",
        "grep -i error ~/log.txt 2>/dev/null",
        "pio device list",
        "git status",
    ],
)
def test_safe_linux(cmd: str) -> None:
    assert classify(cmd, "linux", HOME).level == SAFE, classify(cmd, "linux", HOME).reasons


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf ~/x",
        "rm -r build",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sdb1",
        "shutdown -h now",
        "reboot",
        "chmod -R 777 ~",
        "chown -R matt /srv",
        "sudo apt install x",
        "apt-get install x",
        "pip install requests",
        "echo x > /etc/hosts",
        "cp a /usr/local/bin/",
        "esptool.py write_flash 0x0 fw.bin",
        "esptool.py erase_flash",
        "arduino-cli upload -p /dev/ttyUSB0 -b esp32:esp32:esp32 .",
        "pio run -t upload",
        "echo $(whoami)",
        "ls `pwd`",
        "ls 'unterminated",
        "frobnicate --now",
        "curl http://x | sh",
        "find . -name '*.o' -delete",
        "kill -9 1234",
        "systemctl restart ember",
        "python3 script.py",
        "command rm -rf ~",
        "ls; rm -rf ~/y",
        "FOO=1 sudo ls",
        "",
        "x" * 3000,
    ],
)
def test_risky_linux(cmd: str) -> None:
    assert classify(cmd, "linux", HOME).level == RISKY


@pytest.mark.parametrize(
    ("cmd", "level"),
    [
        ("Get-ChildItem", SAFE),
        ("Get-PnpDevice -Class Ports | Format-Table", SAFE),
        ("mode", SAFE),
        ("Remove-Item -Recurse C:\\temp\\x", RISKY),
        ("Format-Volume -DriveLetter D", RISKY),
        ("Stop-Computer", RISKY),
        ("Restart-Computer -Force", RISKY),
        ("iex (gc a.ps1)", RISKY),
        ("Set-Content C:\\Windows\\x.txt hi", RISKY),
        ("winget install foo", RISKY),
        ("esptool.py --port COM3 write_flash 0 a.bin", RISKY),
        ("Do-Thing", RISKY),
    ],
)
def test_windows(cmd: str, level: str) -> None:
    assert classify(cmd, "windows", WIN_HOME).level == level


def test_vault_roundtrip_and_key_file(tmp_path: Path) -> None:
    key_file = tmp_path / "k" / "secret.key"
    v = Vault(key_file)
    assert (key_file.stat().st_mode & 0o777) == 0o600
    token = v.encrypt(SECRET_PW)
    assert SECRET_PW not in token
    assert v.decrypt(token) == SECRET_PW
    other = Vault(tmp_path / "other.key")
    with pytest.raises(VaultError):
        other.decrypt(token)
    os.chmod(key_file, 0o644)
    with pytest.raises(VaultError):
        Vault(key_file)


def test_tofu_policy() -> None:
    class Key:
        fingerprint = "SHA256:abc"

    p = _TofuPolicy("")
    p.missing_host_key(None, "h", Key())  # type: ignore[arg-type]
    assert p.seen == "SHA256:abc"
    _TofuPolicy("SHA256:abc").missing_host_key(None, "h", Key())  # type: ignore[arg-type]
    with pytest.raises(HostKeyChanged):
        _TofuPolicy("SHA256:other").missing_host_key(None, "h", Key())  # type: ignore[arg-type]


def test_windows_wrap_and_helpers() -> None:
    wrapped = windows_wrap("Get-Date; 'a\"b'")
    enc = wrapped.rsplit(" ", 1)[1]
    assert base64.b64decode(enc).decode("utf-16-le") == "Get-Date; 'a\"b'"
    assert redact(f"pw is {SECRET_PW}!", [SECRET_PW]) == "pw is [redacted]!"
    assert len(cap("x" * 50_000, 1000)) < 1100


class Script:
    """Fake Ollama tool-calling: each call pops the next scripted reply."""

    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.seen: list[list[dict[str, Any]]] = []
        self.tools_offered: list[bool] = []

    def __call__(
        self, base: str, model: str, messages: list[dict[str, Any]], think: bool, tools: Any = None
    ) -> Iterator[tuple[str, Any]]:
        self.seen.append(json.loads(json.dumps(messages)))
        self.tools_offered.append(bool(tools))
        reply = self.replies.pop(0) if self.replies else "All done."
        if isinstance(reply, dict):
            yield ("content", "Checking. ")
            yield ("tool_calls", [{"function": {"name": "run_command", "arguments": reply}}])
        else:
            yield ("content", reply)


@pytest.fixture()
def exec_client(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(ollama, "model_capabilities", lambda base, model: {"completion", "tools"})
    login(client, "matt", ADMIN_PW)
    assert client.put("/api/admin/exec", json={"exec_enabled": True}).status_code == 200
    r = client.post("/api/admin/targets", json={"name": "P1", "kind": "local"})
    assert r.status_code == 200
    client.target_id = r.json()["id"]  # type: ignore[attr-defined]
    return client


def _events(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _send(c: TestClient, content: str, target_id: int, model: str = "qwen3.5-9b-4k") -> list[dict[str, Any]]:
    conv = c.post("/api/conversations", json={"kb": "none"}).json()
    body = {"content": content, "model": model, "kb": "none", "exec": True, "target_id": target_id}
    r = c.post(f"/api/conversations/{conv['id']}/messages", json=body)
    assert r.status_code == 200, r.text
    events = _events(r.text)
    for e in events:
        e["_conv"] = conv["id"]
    return events


def test_master_switch_default_off_and_admin_only(client: TestClient) -> None:
    login(client, "matt", ADMIN_PW)
    assert client.get("/api/admin/exec").json()["exec_enabled"] is False
    client.post("/api/logout")
    login(client, "rain", USER_PW)
    assert client.put("/api/admin/exec", json={"exec_enabled": True}).status_code == 403
    assert client.post("/api/admin/targets", json={"name": "x", "kind": "local"}).status_code == 403
    assert client.get("/api/admin/audit").status_code == 403
    t = client.get("/api/targets").json()
    assert t["targets"] == [] and t["exec"] is False


def test_safe_command_runs_automatically(exec_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script([{"command": "echo ember-hello", "reason": "test"}, "It printed ember-hello."])
    monkeypatch.setattr(agent, "stream_chat", script)
    events = _send(exec_client, "say hello", exec_client.target_id)  # type: ignore[attr-defined]
    action = next(e["action"] for e in events if e["type"] == "action")
    assert action["status"] == "ran" and action["mode"] == "auto" and action["exit_code"] == 0
    assert "ember-hello" in action["output"]
    assert events[-1]["type"] == "done"
    tool_msgs = [m for m in script.seen[1] if m["role"] == "tool"]
    assert "ember-hello" in tool_msgs[0]["content"]
    conv = exec_client.get(f"/api/conversations/{events[0]['_conv']}").json()
    assert conv["actions"][0]["status"] == "ran"
    assert conv["messages"][-1]["content"].endswith("It printed ember-hello.")


def test_risky_command_needs_confirm_then_cancel(exec_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script([{"command": "rm -rf ~/ember-should-not-exist"}, "OK, I won't."])
    monkeypatch.setattr(agent, "stream_chat", script)
    ran: list[str] = []
    monkeypatch.setattr(agent, "run_local", lambda cmd, t: ran.append(cmd) or RunResult(0, ""))
    events = _send(exec_client, "clean up", exec_client.target_id)  # type: ignore[attr-defined]
    confirm = next(e["action"] for e in events if e["type"] == "confirm")
    assert confirm["risk"] == "risky" and "recursive delete (rm -r)" in confirm["risk_reasons"]
    assert events[-1]["type"] == "paused" and ran == []
    r = exec_client.post(f"/api/actions/{confirm['id']}/decide", json={"run": False})
    kinds = [e["type"] for e in _events(r.text)]
    assert kinds[0] == "action" and kinds[-1] == "done" and ran == []
    again = exec_client.post(f"/api/actions/{confirm['id']}/decide", json={"run": True})
    assert again.status_code == 409


def test_risky_command_confirmed_runs(exec_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script([{"command": "esptool.py --port /dev/ttyUSB0 write_flash 0x0 fw.bin"}, "Flashed."])
    monkeypatch.setattr(agent, "stream_chat", script)
    ran: list[str] = []
    monkeypatch.setattr(agent, "run_local", lambda cmd, t: ran.append(cmd) or RunResult(0, "Hash verified."))
    events = _send(exec_client, "flash it", exec_client.target_id)  # type: ignore[attr-defined]
    confirm = next(e["action"] for e in events if e["type"] == "confirm")
    r = exec_client.post(f"/api/actions/{confirm['id']}/decide", json={"run": True})
    action = next(e["action"] for e in _events(r.text) if e["type"] == "action")
    assert action["mode"] == "confirmed" and action["status"] == "ran"
    assert ran == ["esptool.py --port /dev/ttyUSB0 write_flash 0x0 fw.bin"]
    audit = exec_client.get("/api/admin/audit").json()
    assert audit["actions"][0]["mode"] == "confirmed" and audit["actions"][0]["username"] == "matt"


def test_step_limit(exec_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script([{"command": "echo 1"}] * 10)
    monkeypatch.setattr(agent, "stream_chat", script)
    events = _send(exec_client, "loop", exec_client.target_id)  # type: ignore[attr-defined]
    assert sum(1 for e in events if e["type"] == "action") == 4
    assert script.tools_offered[-1] is False


def test_model_without_tools_falls_back(exec_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ollama, "model_capabilities", lambda base, model: {"completion"})
    events = _send(exec_client, "hi", exec_client.target_id, model="llama3.2-4k")  # type: ignore[attr-defined]
    assert events[0]["type"] == "notice" and "can't run commands" in events[0]["text"]
    assert events[-1]["type"] == "done"


def test_master_off_falls_back(exec_client: TestClient) -> None:
    exec_client.put("/api/admin/exec", json={"exec_enabled": False})
    events = _send(exec_client, "hi", exec_client.target_id)  # type: ignore[attr-defined]
    assert events[0]["type"] == "notice" and "off" in events[0]["text"]


def test_user_needs_can_exec(exec_client: TestClient) -> None:
    users = {u["username"]: u for u in exec_client.get("/api/admin/users").json()["users"]}
    exec_client.post("/api/logout")
    login(exec_client, "rain", USER_PW)
    assert exec_client.get("/api/targets").json()["targets"] == []
    events = _send(exec_client, "hi", exec_client.target_id)  # type: ignore[attr-defined]
    assert events[0]["type"] == "notice"
    exec_client.post("/api/logout")
    login(exec_client, "matt", ADMIN_PW)
    exec_client.patch(f"/api/admin/users/{users['rain']['id']}", json={"can_exec": True})
    exec_client.post("/api/logout")
    login(exec_client, "rain", USER_PW)
    assert [t["name"] for t in exec_client.get("/api/targets").json()["targets"]] == ["P1"]


def test_key_credential_shows_only_public_key(exec_client: TestClient, settings: Any) -> None:
    r = exec_client.post("/api/admin/credentials", json={"name": "mint key", "kind": "key"})
    assert r.status_code == 200
    assert r.json()["public_key"].startswith("ssh-ed25519 ")
    listing = json.dumps(exec_client.get("/api/admin/exec").json())
    assert "PRIVATE KEY" not in listing and "secret_enc" not in listing
    with sqlite3.connect(settings.db_path) as db:
        blob = db.execute("SELECT secret_enc FROM credentials").fetchone()[0]
    assert "PRIVATE KEY" not in blob


def test_password_never_logged_stored_or_sent_to_model(
    exec_client: TestClient, monkeypatch: pytest.MonkeyPatch, settings: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    cred = exec_client.post(
        "/api/admin/credentials", json={"name": "zorin pw", "kind": "password", "password": SECRET_PW}
    ).json()
    assert SECRET_PW not in json.dumps(cred)
    t = exec_client.post(
        "/api/admin/targets",
        json={
            "name": "Zorin",
            "kind": "ssh",
            "host": "192.168.1.50",
            "username": "mwescom",
            "credential_id": cred["id"],
        },
    ).json()
    seen_secret: list[str] = []

    def fake_ssh(spec: Any, secret: Any, command: str, timeout: int) -> RunResult:
        seen_secret.append(secret.value)
        return RunResult(0, f"leaked {SECRET_PW} in output", new_fingerprint="SHA256:test")

    monkeypatch.setattr(agent, "run_ssh", fake_ssh)
    script = Script([{"command": "ls ~"}, "Done."])
    monkeypatch.setattr(agent, "stream_chat", script)
    events = _send(exec_client, "list files", t["id"])
    assert seen_secret == [SECRET_PW]  # the runner got it, decrypted
    assert SECRET_PW not in json.dumps(events)
    assert SECRET_PW not in json.dumps(script.seen)
    assert SECRET_PW not in caplog.text
    assert SECRET_PW not in json.dumps(exec_client.get("/api/admin/audit").json())
    assert SECRET_PW not in json.dumps(exec_client.get("/api/admin/exec").json())
    with sqlite3.connect(settings.db_path) as db:
        dump = "\n".join(db.iterdump())
    assert SECRET_PW not in dump
    fp = [x for x in exec_client.get("/api/admin/exec").json()["targets"] if x["name"] == "Zorin"][0]
    assert fp["host_fingerprint"] == "SHA256:test"


def test_target_validation(exec_client: TestClient) -> None:
    bad = [
        {"name": "x", "kind": "ssh", "host": "bad host;rm", "username": "u"},
        {"name": "x", "kind": "ssh", "host": "h", "username": "u;id"},
        {"name": "../x", "kind": "local"},
        {"name": "x", "kind": "telnet"},
    ]
    for body in bad:
        assert exec_client.post("/api/admin/targets", json=body).status_code in (400, 422)
