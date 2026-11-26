"""Radio programming with CHIRP.

How it works
- The radio host (a target with the 'radio' role) has the programming cable and
  CHIRP's command-line tool `chirpc`. Ember runs chirpc there over SSH.
- Every image downloaded from a radio is copied back to the P1 and stored per
  radio under data_dir/radios/<radio_id>/ with its SHA-256.
- Channel lists and edits are done on the P1 by a small helper running in a
  separate CHIRP virtualenv (radio_helper.py), so CHIRP's drivers never run
  inside the web process.
- Uploading to a radio always needs the user's confirmation, and Ember takes a
  fresh backup from the radio immediately before the upload.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess  # nosec B404
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ember.db import now

MAX_RADIOS = 30
MAX_IMAGES_PER_RADIO = 200
MAX_IMAGE_BYTES = 2 * 1024 * 1024
HELPER_TIMEOUT_SEC = 60
REMOTE_DIR = "ember-radio"
PORT_RE = re.compile(r"^(/dev/(tty(USB|ACM)\d{1,3}|serial/by-id/[A-Za-z0-9._:+-]{1,200})|COM\d{1,3})$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}$")


@dataclass(frozen=True)
class RadioModel:
    key: str
    label: str
    chirp_id: str  # value for chirpc -r ; '' if CHIRP has no driver
    mode: str  # 'clone' (download/upload whole image), 'live' (per-channel over CAT), 'none'
    note: str


# Matt's radios. chirp_id values were checked against `chirpc --list-radios` (CHIRP-next, kk7ds/chirp a477ca9).
MODELS: dict[str, RadioModel] = {
    m.key: m
    for m in (
        RadioModel(
            "bf-f8plus",
            "Baofeng BF-F8 Plus",
            "Baofeng_UV-5R",
            "clone",
            "The BF-F8+ uses CHIRP's UV-5R driver. (Baofeng_BF-F8HP is a different, 8 W radio.)",
        ),
        RadioModel("uv-5r", "Baofeng UV-5R", "Baofeng_UV-5R", "clone", "Fully supported by CHIRP."),
        RadioModel(
            "uv-9r-plus",
            "Baofeng UV-9R Plus",
            "Baofeng_UV-9R",
            "clone",
            "CHIRP has a UV-9R driver (and a UV-9R Pro alias). It checks the radio's ID on download, "
            "so a wrong match fails safely before anything is written.",
        ),
        RadioModel(
            "kenwood-t271",
            "Kenwood T271",
            "",
            "none",
            "CHIRP has no driver named TK-271/TH-271. Its Kenwood TK-260/270/272/278 family is the "
            "nearest; if yours is one of those, set the model to that. Otherwise use Kenwood's KPG "
            "programming software on Windows.",
        ),
        RadioModel(
            "kenwood-tk270",
            "Kenwood TK-270 (if your T271 is this family)",
            "Kenwood_TK-270",
            "clone",
            "Commercial VHF radio, CHIRP clone mode.",
        ),
        RadioModel(
            "anytone-d868uv",
            "AnyTone AT-D868UV",
            "",
            "none",
            "CHIRP does NOT support the AT-D868UV (a DMR radio). Its codeplug needs AnyTone's CPS on "
            "Windows (Los Gatos). Ember cannot read, edit or store its .rdt codeplug.",
        ),
        RadioModel(
            "ic-7300",
            "ICOM IC-7300",
            "Icom_IC-7300",
            "live",
            "CHIRP talks to the IC-7300 live over its USB CI-V port (115200 baud): channels are read "
            "and written one at a time; there is no whole-image download/upload. Ember's 'backup' is "
            "a channel listing snapshot. For a full settings backup use Icom's CS-7300 or the SD card.",
        ),
    )
}


class RadioError(Exception):
    """Message is safe to show the user."""


def check_port(port: str) -> str:
    port = (port or "").strip()
    if not PORT_RE.fullmatch(port):
        raise RadioError("serial port must look like /dev/ttyUSB0, /dev/serial/by-id/..., or COM3")
    return port


def get_model(key: str) -> RadioModel:
    model = MODELS.get(key)
    if model is None:
        raise RadioError("unknown radio model")
    return model


# ---------- commands run on the radio host ----------
def ports_command(os_type: str) -> str:
    if os_type == "windows":
        return "Get-CimInstance Win32_SerialPort | Select-Object DeviceID,Description"
    return "ls -l /dev/serial/by-id/ ; ls /dev/ttyUSB* /dev/ttyACM*"


def parse_ports(output: str, os_type: str) -> list[str]:
    found: list[str] = []
    for line in output.splitlines()[:200]:
        for word in line.replace("->", " ").split():
            cand = word.strip()
            if os_type != "windows" and cand.startswith("usb-"):
                cand = "/dev/serial/by-id/" + cand
            if PORT_RE.fullmatch(cand) and cand not in found:
                found.append(cand)
    return found[:20]


def remote_file(radio_id: int, tag: str, os_type: str) -> str:
    sep = "\\" if os_type == "windows" else "/"
    return f"{REMOTE_DIR}{sep}radio{int(radio_id)}-{tag}.img"


def download_command(model: RadioModel, port: str, remote: str, os_type: str) -> str:
    if model.mode != "clone":
        raise RadioError(f"{model.label}: whole-image download is not possible ({model.note})")
    mkdir = (
        f"New-Item -ItemType Directory -Force {REMOTE_DIR} | Out-Null; "
        if os_type == "windows"
        else (f"mkdir -p {REMOTE_DIR} && ")
    )
    return f"{mkdir}chirpc -r {model.chirp_id} --serial={check_port(port)} --mmap={remote} --download-mmap"


def upload_command(model: RadioModel, port: str, pre_backup: str, new_image: str, os_type: str) -> str:
    """Fresh backup from the radio first; only if that worked, upload the new image."""
    port = check_port(port)
    get = f"chirpc -r {model.chirp_id} --serial={port} --mmap={pre_backup} --download-mmap"
    put = f"chirpc -r {model.chirp_id} --serial={port} --mmap={new_image} --upload-mmap"
    if os_type == "windows":
        return f"{get}; if ($LASTEXITCODE -eq 0) {{ {put} }} else {{ exit 1 }}"
    return f"{get} && {put}"


def live_list_command(model: RadioModel, port: str) -> str:
    if model.mode != "live":
        raise RadioError("not a live-mode radio")
    return f"chirpc -r {model.chirp_id} --serial={check_port(port)} --list-mem"


# ---------- storage on the P1 ----------
def radio_dir(data_dir: Path, radio_id: int) -> Path:
    path = data_dir / "radios" / str(int(radio_id))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def store_image(
    conn: sqlite3.Connection,
    data_dir: Path,
    radio_id: int,
    src: Path,
    kind: str,
    parent_id: int | None,
    note: str,
    user_id: int | None,
) -> dict[str, Any]:
    data = src.read_bytes()
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise RadioError("image is empty or too large")
    digest = hashlib.sha256(data).hexdigest()
    name = f"{now()}-{kind}-{digest[:12]}.img"
    dest = radio_dir(data_dir, radio_id) / name
    dest.write_bytes(data)
    dest.chmod(0o600)
    cur = conn.execute(
        "INSERT INTO radio_images(radio_id, kind, file_name, sha256, size, parent_id, note, user_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (radio_id, kind, name, digest, len(data), parent_id, note[:200], user_id, now()),
    )
    return {"id": int(cur.lastrowid or 0), "kind": kind, "sha256": digest, "size": len(data)}


def image_path(conn: sqlite3.Connection, data_dir: Path, image_id: int) -> tuple[Path, sqlite3.Row]:
    row = conn.execute(
        "SELECT i.*, r.model_key FROM radio_images i JOIN radios r ON r.id = i.radio_id WHERE i.id = ?", (image_id,)
    ).fetchone()
    if row is None:
        raise RadioError("no such image")
    path = radio_dir(data_dir, int(row["radio_id"])) / str(row["file_name"])
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
        raise RadioError("stored image is missing or its checksum does not match")
    return path, row


def list_radios(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM radios ORDER BY name LIMIT ?", (MAX_RADIOS,)).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        model = MODELS.get(str(r["model_key"]))
        item["model"] = model.label if model else r["model_key"]
        item["mode"] = model.mode if model else "none"
        item["images"] = [
            dict(i)
            for i in conn.execute(
                "SELECT id, kind, sha256, size, parent_id, note, created_at FROM radio_images "
                "WHERE radio_id = ? ORDER BY id DESC LIMIT ?",
                (r["id"], MAX_IMAGES_PER_RADIO),
            ).fetchall()
        ]
        out.append(item)
    return out


def add_radio(conn: sqlite3.Connection, name: str, model_key: str, port: str, notes: str) -> int:
    name = (name or "").strip()
    if not NAME_RE.fullmatch(name):
        raise RadioError("radio name: 1-40 letters, digits, space . _ -")
    get_model(model_key)
    if port:
        check_port(port)
    if conn.execute("SELECT COUNT(*) FROM radios").fetchone()[0] >= MAX_RADIOS:
        raise RadioError("radio limit reached")
    if conn.execute("SELECT 1 FROM radios WHERE name = ?", (name,)).fetchone():
        raise RadioError("a radio with that name exists")
    cur = conn.execute(
        "INSERT INTO radios(name, model_key, port, notes, created_at) VALUES (?, ?, ?, ?, ?)",
        (name, model_key, port, (notes or "")[:300], now()),
    )
    return int(cur.lastrowid or 0)


def last_backup(conn: sqlite3.Connection, radio_id: int) -> int:
    row = conn.execute(
        "SELECT id FROM radio_images WHERE radio_id = ? AND kind = 'backup' ORDER BY id DESC LIMIT 1", (radio_id,)
    ).fetchone()
    return int(row["id"]) if row else 0


# ---------- CHIRP helper (separate venv, subprocess) ----------
def helper_python() -> Path:
    return Path.home() / ".local/share/ember/chirp-venv/bin/python"


def helper_available() -> bool:
    return helper_python().is_file()


def run_helper(args: list[str], stdin: str = "") -> Any:
    """Run radio_helper.py in the CHIRP venv. Arguments are a list (no shell); output is JSON."""
    if not helper_available():
        raise RadioError("CHIRP is not installed on the P1 (run ./coldboot.sh install, or install.sh)")
    script = Path(__file__).with_name("radio_helper.py")
    try:
        proc = subprocess.run(  # noqa: S603 # nosec B603
            [str(helper_python()), "-W", "ignore", str(script), *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=HELPER_TIMEOUT_SEC,
            check=False,
            env={"CHIRP_TESTENV": "1", "HOME": str(Path.home())},
        )
    except subprocess.TimeoutExpired as exc:
        raise RadioError("CHIRP helper timed out") from exc
    try:
        result = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RadioError(f"CHIRP helper failed: {proc.stderr[-300:]}") from exc
    if not isinstance(result, dict) or result.get("error"):
        raise RadioError(str(result.get("error") if isinstance(result, dict) else "bad helper reply")[:300])
    return result


def channels(model: RadioModel, image: Path) -> list[dict[str, Any]]:
    result = run_helper(["list", model.chirp_id, str(image)])
    return list(result.get("channels") or [])


def apply_edits(model: RadioModel, image: Path, out: Path, edits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = run_helper(["edit", model.chirp_id, str(image), str(out)], json.dumps({"edits": edits[:200]}))
    return list(result.get("channels") or [])


DIFF_FIELDS = ("name", "freq", "duplex", "offset", "tmode", "rtone", "ctone", "dtcs", "mode", "power", "skip")


def diff_channels(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-channel differences: added, removed, or changed fields."""
    before = {str(c["number"]): c for c in old}
    after = {str(c["number"]): c for c in new}
    out: list[dict[str, Any]] = []
    for num in sorted(set(before) | set(after), key=lambda n: (len(n), n))[:2000]:
        a, b = before.get(num), after.get(num)
        if a is None and b is not None:
            out.append({"number": num, "change": "added", "after": b})
        elif b is None and a is not None:
            out.append({"number": num, "change": "removed", "before": a})
        elif a is not None and b is not None:
            fields = {f: [a.get(f), b.get(f)] for f in DIFF_FIELDS if a.get(f) != b.get(f)}
            if fields:
                out.append({"number": num, "change": "changed", "fields": fields})
    return out
