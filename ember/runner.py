"""Run one command on a target: locally (the P1) or over SSH (paramiko).

- Local: ["bash", "-lc", command] as an argument list (never shell=True). The
  command string is shell by design; the classifier and Confirm card gate it.
- SSH: keys or passwords from the vault, host key trust-on-first-use with a
  stored SHA-256 fingerprint; a changed key is refused.
- Every run has a timeout and an output cap. Known secrets are redacted.
"""

from __future__ import annotations

import base64
import os
import subprocess  # nosec B404
import tempfile
import time
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import paramiko

from ember import config

READ_CHUNK = 4096
MAX_READ_LOOPS = 100_000


@dataclass(frozen=True)
class TargetSpec:
    id: int
    name: str
    kind: str
    host: str
    port: int
    username: str
    os: str
    fingerprint: str


@dataclass(frozen=True)
class Secret:
    kind: str  # 'key' or 'password'
    value: str


@dataclass
class RunResult:
    exit_code: int | None
    output: str
    error: str = ""
    new_fingerprint: str = ""


class HostKeyChanged(Exception):
    pass


def redact(text: str, secrets: list[str]) -> str:
    out = text
    for s in secrets:
        if s and len(s) >= 4:
            out = out.replace(s, "[redacted]")
    return out


def cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head - 40
    return text[:head] + f"\n…[{len(text) - head - tail} chars cut]…\n" + text[-tail:]


def run_local(command: str, timeout_sec: int) -> RunResult:
    """Run in the home directory with a small environment; output spooled to a temp file."""
    env = {
        "HOME": str(Path.home()),
        "PATH": f"{Path.home()}/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "TERM": "dumb",
    }
    fd, tmp = tempfile.mkstemp(prefix="ember-run-")
    try:
        with os.fdopen(fd, "w+b") as out:
            try:
                proc = subprocess.run(  # noqa: S603 # nosec B603
                    ["/bin/bash", "-lc", command], stdin=subprocess.DEVNULL, stdout=out,
                    stderr=subprocess.STDOUT, cwd=str(Path.home()), env=env, timeout=timeout_sec, check=False,
                )
                code: int | None = proc.returncode
                err = ""
            except subprocess.TimeoutExpired:
                code, err = None, f"timed out after {timeout_sec}s"
            out.seek(0)
            data = out.read(config.MAX_OUTPUT_STORE * 4)
    finally:
        os.unlink(tmp)
    return RunResult(exit_code=code, output=data.decode("utf-8", "replace"), error=err)


def windows_wrap(command: str) -> str:
    """PowerShell via -EncodedCommand so quoting cannot break out."""
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    return f"powershell -NoProfile -NonInteractive -EncodedCommand {encoded}"


def host_fingerprint(key: paramiko.PKey) -> str:
    return str(key.fingerprint)


class _TofuPolicy(paramiko.MissingHostKeyPolicy):
    """Accept an unknown host only if no fingerprint is stored; refuse a changed key."""

    def __init__(self, expected: str) -> None:
        self.expected = expected
        self.seen = ""

    def missing_host_key(self, client: paramiko.SSHClient, hostname: str, key: paramiko.PKey) -> None:
        self.seen = host_fingerprint(key)
        if self.expected and self.seen != self.expected:
            raise HostKeyChanged(f"host key for {hostname} changed (now {self.seen})")


def _load_pkey(secret: Secret) -> paramiko.PKey:
    return paramiko.Ed25519Key.from_private_key(StringIO(secret.value))


def run_ssh(target: TargetSpec, secret: Secret | None, command: str, timeout_sec: int) -> RunResult:
    if secret is None:
        return RunResult(None, "", "no credential set for this target")
    policy = _TofuPolicy(target.fingerprint)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(policy)
    remote = windows_wrap(command) if target.os == "windows" else command
    try:
        client.connect(
            target.host, port=target.port, username=target.username,
            pkey=_load_pkey(secret) if secret.kind == "key" else None,
            password=secret.value if secret.kind == "password" else None,
            timeout=config.SSH_CONNECT_TIMEOUT_SEC, banner_timeout=config.SSH_CONNECT_TIMEOUT_SEC,
            auth_timeout=config.SSH_CONNECT_TIMEOUT_SEC, allow_agent=False, look_for_keys=False,
        )
        result = _exec(client, remote, timeout_sec)
    except HostKeyChanged as exc:
        return RunResult(None, "", f"refused: {exc}. If the host was reinstalled, an admin can reset its fingerprint.")
    except paramiko.AuthenticationException:
        return RunResult(None, "", "SSH login failed (check the user and that the public key is installed)")
    except (TimeoutError, paramiko.SSHException, OSError) as exc:
        return RunResult(None, "", f"SSH error: {type(exc).__name__}: {str(exc)[:200]}")
    finally:
        client.close()
    if not target.fingerprint and policy.seen:
        result.new_fingerprint = policy.seen
    return result


def _exec(client: paramiko.SSHClient, command: str, timeout_sec: int) -> RunResult:
    transport = client.get_transport()
    if transport is None:
        return RunResult(None, "", "SSH transport closed")
    chan = transport.open_session(timeout=config.SSH_CONNECT_TIMEOUT_SEC)
    chan.set_combine_stderr(True)
    chan.settimeout(1.0)
    # Running the user-approved command is the feature; gated by classifier + Confirm.
    chan.exec_command(command)  # nosec B601
    deadline = time.monotonic() + timeout_sec
    buf = bytearray()
    limit = config.MAX_OUTPUT_STORE * 4
    for _ in range(MAX_READ_LOOPS):
        if time.monotonic() > deadline:
            chan.close()
            return RunResult(None, buf.decode("utf-8", "replace"), f"timed out after {timeout_sec}s")
        try:
            chunk = chan.recv(READ_CHUNK)
        except TimeoutError:
            chunk = b""
        if chunk and len(buf) < limit:
            buf.extend(chunk[: limit - len(buf)])
        if not chunk and chan.exit_status_ready():
            break
        if not chunk:
            time.sleep(0.05)
    code = chan.recv_exit_status() if chan.exit_status_ready() else None
    return RunResult(code, buf.decode("utf-8", "replace"))
