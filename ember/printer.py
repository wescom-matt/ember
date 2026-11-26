"""ELEGOO Centauri Carbon 2 (CC2) over the LAN.

What the CC2 actually speaks (researched, not assumed):
- NOT SDCP (the older Elegoo resin/CC1 WebSocket protocol) and NOT Klipper/Moonraker.
- The printer runs its own MQTT 3.1.1 broker on TCP 1883. Login: user 'elegoo',
  password = the access code set on the printer, or '123456' if none is set.
  The printer must be in LAN-only mode (not cloud mode).
- UDP 52700: send {"id":0,"method":7000} to get the serial number (sn).
- Each connection registers on elegoo/<sn>/api_register, then sends JSON-RPC style
  requests on elegoo/<sn>/<client_id>/api_request and reads
  elegoo/<sn>/<client_id>/api_response. The printer allows only ~4 clients.
- Methods: 1002 status, 1044 file list, 1020 start, 1021 pause, 1023 resume, 1022 stop.
- G-code upload: HTTP PUT http://<ip>/upload with Content-Range, in chunks.
Sources: elegooofficial/elegoo-link (Elegoo's open-source SDK, CC2 adapter) and the
community protocol notes in danielcherubini/elegoo-homeassistant docs/CC2_PROTOCOL.md.
Not yet tested against Matt's printer; firmware updates may change details.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import secrets
import socket
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MQTT_PORT = 1883
DISCOVERY_PORT = 52700
DEFAULT_CODE = "123456"  # the printer's documented default when no access code is set (not a secret)  # nosec B105
TIMEOUT_SEC = 8.0
CHUNK = 1024 * 1024
MAX_GCODE_BYTES = 512 * 1024 * 1024
FILENAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- ")

M_STATUS, M_FILES, M_START, M_PAUSE, M_STOP, M_RESUME = 1002, 1044, 1020, 1021, 1022, 1023
ACTIONS = {
    "status": M_STATUS,
    "files": M_FILES,
    "start": M_START,
    "pause": M_PAUSE,
    "resume": M_RESUME,
    "cancel": M_STOP,
}
# Starting, resuming and cancelling change what the machine does: always confirmed by a person.
CONFIRM_ACTIONS = frozenset({"start", "resume", "cancel", "upload"})
MACHINE_STATES = {
    0: "starting up",
    1: "idle",
    2: "printing",
    3: "filament change",
    4: "filament change",
    5: "bed leveling",
    6: "PID calibration",
    7: "resonance test",
    8: "self check",
    9: "firmware update",
    10: "homing",
    11: "file transfer",
    12: "making timelapse",
    13: "extruder maintenance",
    14: "EMERGENCY STOP",
    15: "power-loss recovery",
}


class PrinterError(Exception):
    """Message is safe to show the user."""


@dataclass(frozen=True)
class PrinterSpec:
    host: str
    access_code: str  # '' -> printer default


def check_host(host: str) -> str:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError as exc:
        raise PrinterError("printer host must be a LAN IP address") from exc
    if addr.version != 4 or not addr.is_private or addr.is_loopback:
        raise PrinterError("printer host must be a private LAN IPv4 address")
    return host


def check_filename(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > 120 or not set(name) <= FILENAME_CHARS or name.startswith("."):
        raise PrinterError("file name: letters, digits, space . _ - only")
    if not name.lower().endswith(".gcode"):
        raise PrinterError("only .gcode files can be sent to the printer")
    return name


def discover(host: str, timeout: float = TIMEOUT_SEC) -> dict[str, Any]:
    """Ask one printer (unicast, not broadcast) for its identity and serial number."""
    check_host(host)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(json.dumps({"id": 0, "method": 7000}).encode(), (host, DISCOVERY_PORT))
        data, _ = sock.recvfrom(8192)
    reply = json.loads(data.decode("utf-8", "replace"))
    result = reply.get("result") if isinstance(reply, dict) else None
    if not isinstance(result, dict) or not result.get("sn"):
        raise PrinterError("printer did not answer discovery (is it on, and on this network?)")
    return result


class Session:
    """One short MQTT session: connect, register, send requests, disconnect."""

    def __init__(self, spec: PrinterSpec, sn: str, mqtt_factory: Any = None) -> None:
        self.spec = spec
        self.sn = sn
        self.client_id = f"1_PC_{1000 + secrets.randbelow(9000)}"
        self._factory = mqtt_factory or _paho_client
        self._replies: dict[str, Any] = {}
        self._cond = threading.Condition()
        self._next = 1
        self._mqtt: Any = None

    def __enter__(self) -> Session:
        self._mqtt = self._factory(self.client_id)
        self._mqtt.username_pw_set("elegoo", self.spec.access_code or DEFAULT_CODE)
        self._mqtt.on_message = self._on_message
        try:
            self._mqtt.connect(self.spec.host, MQTT_PORT, keepalive=60)
        except OSError as exc:
            raise PrinterError(f"cannot reach printer MQTT on {self.spec.host}:1883 ({exc})") from exc
        self._mqtt.loop_start()
        self._register()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._mqtt is not None:
            self._mqtt.loop_stop()
            self._mqtt.disconnect()

    def _on_message(self, _client: Any, _userdata: Any, msg: Any) -> None:
        try:
            body = json.loads(msg.payload.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(body, dict):
            return
        key = "register" if msg.topic.endswith("/register_response") else str(body.get("id", ""))
        with self._cond:
            self._replies[key] = body
            self._cond.notify_all()

    def _wait(self, key: str) -> dict[str, Any]:
        deadline = time.monotonic() + TIMEOUT_SEC
        with self._cond:
            while key not in self._replies:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise PrinterError("printer did not reply in time")
                self._cond.wait(left)
            reply: dict[str, Any] = self._replies.pop(key)
            return reply

    def _register(self) -> None:
        request_id = f"{self.client_id}_req"
        self._mqtt.subscribe(f"elegoo/{self.sn}/{request_id}/register_response")
        self._mqtt.subscribe(f"elegoo/{self.sn}/{self.client_id}/api_response")
        self._mqtt.publish(
            f"elegoo/{self.sn}/api_register", json.dumps({"client_id": self.client_id, "request_id": request_id})
        )
        reply = self._wait("register")
        if reply.get("error") != "ok":
            hint = " (close other apps/slicers connected to it)" if "many" in str(reply.get("error")) else ""
            raise PrinterError(f"printer refused the connection: {reply.get('error')}{hint}")

    def call(self, method: int, params: dict[str, Any] | None = None) -> dict[str, Any]:
        req_id = self._next
        self._next += 1
        self._mqtt.publish(
            f"elegoo/{self.sn}/{self.client_id}/api_request",
            json.dumps({"id": req_id, "method": method, "params": params or {}}),
        )
        reply = self._wait(str(req_id))
        result = reply.get("result")
        if not isinstance(result, dict):
            raise PrinterError("printer sent an unexpected reply")
        code = result.get("error_code", 0)
        if code:
            raise PrinterError(f"printer returned error code {code}")
        return result


def _paho_client(client_id: str) -> Any:
    import paho.mqtt.client as mqtt  # noqa: PLC0415  # only needed when a printer is used

    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True)


def summarize(status: dict[str, Any]) -> dict[str, Any]:
    machine = status.get("machine_status") or {}
    job = status.get("print_status") or {}
    ext = status.get("extruder") or {}
    bed = status.get("heater_bed") or {}
    return {
        "state": MACHINE_STATES.get(int(machine.get("status", -1)), f"code {machine.get('status')}"),
        "progress": job.get("progress", machine.get("progress")),
        "file": job.get("filename", ""),
        "layer": f"{job.get('current_layer', 0)}/{job.get('total_layer', 0)}",
        "remaining_min": int(job.get("remaining_time_sec", 0) or 0) // 60,
        "nozzle": f"{ext.get('temperature', '?')}/{ext.get('target', '?')} C",
        "bed": f"{bed.get('temperature', '?')}/{bed.get('target', '?')} C",
        "errors": machine.get("exception_status") or [],
    }


def run_action(spec: PrinterSpec, action: str, filename: str = "", mqtt_factory: Any = None) -> dict[str, Any]:
    """status | files | start | pause | resume | cancel. Caller enforces confirmation for CONFIRM_ACTIONS."""
    if action not in ACTIONS:
        raise PrinterError("unknown printer action")
    check_host(spec.host)
    sn = str(discover(spec.host).get("sn"))
    params: dict[str, Any] = {}
    if action == "start":
        params = {
            "storage_media": "local",
            "filename": check_filename(filename),
            "config": {"printer_check": True, "bedlevel_force": False, "slot_map": []},
        }
    elif action == "files":
        params = {"storage_media": "local", "offset": 0, "limit": 50}
    with Session(spec, sn, mqtt_factory) as session:
        result = session.call(ACTIONS[action], params)
    return summarize(result) if action == "status" else result


def upload(spec: PrinterSpec, path: Path, name: str, opener: Any = None) -> dict[str, Any]:
    """PUT a .gcode file to the printer's storage in 1 MB ranges."""
    check_host(spec.host)
    name = check_filename(name)
    total = path.stat().st_size
    if total == 0 or total > MAX_GCODE_BYTES:
        raise PrinterError("G-code file is empty or too large")
    md5 = hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
    url = f"http://{spec.host}/upload"  # LAN printer only offers plain HTTP; host is a validated private IP
    send = opener or urllib.request.urlopen
    with path.open("rb") as fh:
        for start in range(0, total, CHUNK):
            chunk = fh.read(CHUNK)
            end = start + len(chunk) - 1
            req = urllib.request.Request(
                url,
                data=chunk,
                method="PUT",
                headers={  # noqa: S310
                    "Content-Type": "application/octet-stream",
                    "Content-Range": f"bytes {start}-{end}/{total}",
                    "X-File-Name": name,
                    "X-File-MD5": md5,
                    "X-Token": spec.access_code or DEFAULT_CODE,
                    "User-Agent": "Ember",
                    "Accept": "application/json",
                },
            )
            with send(req, timeout=60) as resp:  # nosec B310
                body = json.loads(resp.read(4096) or b"{}")
            if body.get("error_code", 1) != 0:
                raise PrinterError(f"upload failed at byte {start}: {body}")
    return {"file": name, "size": total, "md5": md5}


# ---------- offline slicing on the build host (OrcaSlicer CLI + CC2 profiles) ----------
MODEL_EXT = (".stl", ".3mf", ".obj", ".step", ".stp")
NOZZLES = ("0.2", "0.4", "0.6", "0.8")
PROFILE_DIR = ".local/share/ember/slicer-profiles/cc2"  # under the build host's home (Linux)
WIN_TOOLS = "ember-tools"  # %USERPROFILE%\ember-tools on Windows
PROFILE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .@+-_")
DEFAULT_PROCESS = "0.20mm Standard @Elegoo CC2 0.4 nozzle"
DEFAULT_FILAMENT = "Elegoo PLA @ECC2"


def _profile(name: str, fallback: str) -> str:
    name = (name or fallback).strip()
    if not name or len(name) > 80 or not set(name) <= PROFILE_CHARS:
        raise PrinterError("profile names: letters, digits, space . @ + - _")
    return name


def slice_command(os_type: str, model: str, nozzle: str, process: str, filament: str, outdir: str) -> str:
    """OrcaSlicer CLI line for the CC2 (tested with OrcaSlicer 2.5.2 and the merged ECC2 profiles).

    Paths were checked by runner.check_remote_path (no $, quotes or backticks), so double quotes are safe.
    """
    if not model.lower().endswith(MODEL_EXT):
        raise PrinterError(f"model must be one of {', '.join(MODEL_EXT)}")
    if nozzle not in NOZZLES:
        raise PrinterError("nozzle must be 0.2, 0.4, 0.6 or 0.8")
    proc = _profile(process, DEFAULT_PROCESS)
    fil = _profile(filament, DEFAULT_FILAMENT)
    machine = f"Elegoo Centauri Carbon 2 {nozzle} nozzle"
    if os_type == "windows":
        base = f"$HOME\\{WIN_TOOLS}\\slicer-profiles\\cc2"
        settings = f"{base}\\machine\\{machine}.json;{base}\\process\\{proc}.json"
        return (
            f'& "$HOME\\{WIN_TOOLS}\\OrcaSlicer\\orca-slicer.exe" --slice 0 --arrange 1 --orient 1 '
            f'--load-settings "{settings}" --load-filaments "{base}\\filament\\{fil}.json" '
            f'--outputdir "{outdir}" "{model}"'
        )
    base = f"$HOME/{PROFILE_DIR}"
    settings = f"{base}/machine/{machine}.json;{base}/process/{proc}.json"
    out_q, model_q = _dq(outdir), _dq(model)
    return (
        f"mkdir -p {out_q} && orca-slicer --slice 0 --arrange 1 --orient 1 "
        f'--load-settings "{settings}" --load-filaments "{base}/filament/{fil}.json" '
        f"--outputdir {out_q} {model_q}"
    )


def _dq(path: str) -> str:
    """Double-quote a checked path for bash; '~/x' becomes "$HOME/x"."""
    if any(c in path for c in '$"`'):
        raise PrinterError("path has unsupported characters")
    return f'"$HOME/{path[2:]}"' if path.startswith("~/") else f'"{path}"'
