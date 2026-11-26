"""v0.4.0: roles, radio, printer, parts library, write_file, classifier, migration."""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ember import agent, parts, printer, radio, roles
from ember.classifier import classify
from ember.db import connect, init_db
from ember.radio_kb import chunks, html_sections
from ember.runner import RunResult, check_remote_path
from tests.test_exec import _events, _send, exec_client  # noqa: F401  (fixture)

CHIRP_VENV_PY = Path.home() / ".local/share/ember/chirp-venv/bin/python"


class ToolScript:
    def __init__(self, calls: list[Any]) -> None:
        self.calls = calls

    def __call__(self, base: str, model: str, messages: Any, think: bool, tools: Any = None) -> Iterator[Any]:
        reply = self.calls.pop(0) if self.calls else "Done."
        if isinstance(reply, tuple):
            yield ("tool_calls", [{"function": {"name": reply[0], "arguments": reply[1]}}])
        else:
            yield ("content", reply)


# ---------- roles / targets ----------
def test_roles_parse_and_active_host(settings: Any) -> None:
    assert roles.parse_roles("Radio, build ,radio") == ["radio", "build"]
    assert roles.parse_roles("") == ["general"]
    with pytest.raises(ValueError):
        roles.parse_roles("a;b")
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        for name, r in (("Los Gatos", "radio,build"), ("Zorin", "radio"), ("Mint", "radio,build")):
            conn.execute(
                "INSERT INTO targets(name, kind, host, port, username, os, roles, created_at) "
                "VALUES (?, 'ssh', '192.168.1.5', 22, 'u', 'linux', ?, 0)",
                (name, r),
            )
        ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM targets")}
        assert roles.active_host(conn, "radio", None) == ids["Mint"]  # default candidate order: Mint first
        assert roles.active_host(conn, "build", None) == ids["Los Gatos"]
        roles.set_global_active(conn, "radio", ids["Zorin"])
        assert roles.active_host(conn, "radio", None) == ids["Zorin"]
        assert roles.active_host(conn, "radio", ids["Los Gatos"]) == ids["Los Gatos"]
        with pytest.raises(ValueError):
            roles.set_global_active(conn, "build", ids["Zorin"])


def test_printer_target_validation(exec_client: TestClient) -> None:  # noqa: F811
    c = exec_client
    bad = c.post("/api/admin/targets", json={"name": "CC2", "kind": "printer", "host": "8.8.8.8"})
    assert bad.status_code == 400 and "private" in bad.json()["detail"]
    ok = c.post("/api/admin/targets", json={"name": "CC2", "kind": "printer", "host": "192.168.1.60", "port": 1883})
    assert ok.status_code == 200
    t = [x for x in c.get("/api/targets").json()["targets"] if x["name"] == "CC2"][0]
    assert t["roles"] == "printer"
    presets = c.get("/api/admin/exec").json()["presets"]
    assert {p["name"] for p in presets} >= {"Mint", "Zorin", "Los Gatos"}


def test_migration_v2_to_v3_keeps_targets(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE targets (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, "
        "kind TEXT NOT NULL CHECK (kind IN ('local','ssh')), host TEXT NOT NULL DEFAULT '', port INTEGER NOT NULL "
        "DEFAULT 22, username TEXT NOT NULL DEFAULT '', os TEXT NOT NULL DEFAULT 'linux', credential_id INTEGER, "
        "host_fingerprint TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL);"
        "INSERT INTO targets(name, kind, created_at) VALUES ('P1', 'local', 1);"
    )
    conn.commit()
    conn.close()
    init_db(db)
    init_db(db)  # idempotent
    with connect(db) as c:
        row = c.execute("SELECT name, roles FROM targets").fetchone()
        assert row["name"] == "P1" and row["roles"] == "general"
        c.execute("INSERT INTO targets(name, kind, host, created_at) VALUES ('CC2', 'printer', '192.168.1.9', 1)")


# ---------- classifier ----------
@pytest.mark.parametrize(
    ("cmd", "level"),
    [
        (
            "CHIRP_TESTENV=1 chirpc -r Baofeng_UV-5R --serial=/dev/ttyUSB0 --mmap=ember-radio/a.img --download-mmap",
            "safe",
        ),
        ("chirpc -r Baofeng_UV-5R --serial=/dev/ttyUSB0 --mmap=a.img --upload-mmap", "risky"),
        ("chirpc -r Baofeng_UV-5R --mmap=a.img --set-mem-name=TEST 5", "safe"),
        ("chirpc -r Icom_IC-7300 -s /dev/ttyUSB0 --set-mem-freq=146.52 5", "risky"),
        ("chirpc -r X --mmap=/etc/x.img --download-mmap", "risky"),
        ('orca-slicer --slice 0 --outputdir "ember-prints" "$HOME/m.stl"', "safe"),
        ("orca-slicer --slice 0 --outputdir /opt/x m.stl", "risky"),
    ],
)
def test_classifier_radio_and_slicer(cmd: str, level: str) -> None:
    assert classify(cmd, "linux", "/home/matt").level == level


# ---------- radio ----------
def test_radio_models_and_commands() -> None:
    assert radio.MODELS["bf-f8plus"].chirp_id == "Baofeng_UV-5R"
    assert radio.MODELS["anytone-d868uv"].mode == "none"
    assert radio.MODELS["ic-7300"].mode == "live"
    cmd = radio.download_command(radio.MODELS["uv-5r"], "/dev/ttyUSB0", "ember-radio/r1.img", "linux")
    assert cmd.endswith("--download-mmap") and "--serial=/dev/ttyUSB0" in cmd
    up = radio.upload_command(radio.MODELS["uv-5r"], "/dev/ttyUSB0", "pre.img", "new.img", "linux")
    assert up.index("--download-mmap") < up.index("--upload-mmap") and "&&" in up
    for bad in ("/dev/ttyUSB0; rm -rf ~", "/etc/passwd", "COM3 & calc"):
        with pytest.raises(radio.RadioError):
            radio.check_port(bad)
    with pytest.raises(radio.RadioError):
        radio.download_command(radio.MODELS["anytone-d868uv"], "COM3", "x.img", "windows")
    out = "lrwxrwxrwx 1 root root 13 usb-Prolific_PL2303-if00-port0 -> ../../ttyUSB0\n/dev/ttyUSB0\n"
    assert radio.parse_ports(out, "linux") == ["/dev/serial/by-id/usb-Prolific_PL2303-if00-port0", "/dev/ttyUSB0"]


def test_radio_channel_diff() -> None:
    old = [{"number": 1, "name": "A", "freq": 146.52}, {"number": 2, "name": "B", "freq": 147.0}]
    new = [{"number": 1, "name": "A", "freq": 146.55}, {"number": 3, "name": "C", "freq": 446.0}]
    diff = radio.diff_channels(old, new)
    assert [d["change"] for d in diff] == ["changed", "removed", "added"]
    assert diff[0]["fields"] == {"freq": [146.52, 146.55]}


@pytest.mark.skipif(not CHIRP_VENV_PY.is_file(), reason="CHIRP venv not installed")
def test_radio_helper_with_real_chirp(tmp_path: Path, settings: Any) -> None:
    images = list(Path("/workspace/chirp-work").glob("chirp-*/tests/images/Baofeng_UV-5R.img"))
    if not images:
        pytest.skip("no sample image")
    model = radio.MODELS["uv-5r"]
    chans = radio.channels(model, images[0])
    assert chans and "freq" in chans[0]
    out = tmp_path / "e.img"
    new = radio.apply_edits(model, images[0], out, [{"number": 0, "name": "TEST", "freq": "146.520"}])
    assert out.is_file() and new[0]["name"] == "TEST"
    with pytest.raises(radio.RadioError):
        radio.apply_edits(model, images[0], tmp_path / "bad.img", [{"number": 0, "freq": "999.1"}])
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        rid = radio.add_radio(conn, "UV-5R one", "uv-5r", "/dev/ttyUSB0", "")
        item = radio.store_image(conn, settings.data_dir, rid, images[0], "backup", None, "test", None)
        path, row = radio.image_path(conn, settings.data_dir, item["id"])
        assert path.read_bytes() == images[0].read_bytes() and row["model_key"] == "uv-5r"


def test_radio_upload_requires_confirm(exec_client: TestClient) -> None:  # noqa: F811
    r = exec_client.post("/api/radio/images/1/upload", json={"confirm": False})
    assert r.status_code == 400 and "confirmation" in r.json()["detail"]


# ---------- printer ----------
class FakeMsg:
    def __init__(self, topic: str, payload: dict[str, Any]) -> None:
        self.topic = topic
        self.payload = json.dumps(payload).encode()


class FakeMqtt:
    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self.on_message: Any = None
        self.published: list[tuple[str, dict[str, Any]]] = []
        self.auth: tuple[str, str] = ("", "")

    def username_pw_set(self, user: str, pw: str) -> None:
        self.auth = (user, pw)

    def connect(self, host: str, port: int, keepalive: int) -> None:
        assert port == 1883

    def loop_start(self) -> None: ...
    def loop_stop(self) -> None: ...
    def disconnect(self) -> None: ...
    def subscribe(self, topic: str) -> None: ...

    def publish(self, topic: str, body: str) -> None:
        data = json.loads(body)
        self.published.append((topic, data))
        if topic.endswith("api_register"):
            self.on_message(
                None,
                None,
                FakeMsg(
                    f"elegoo/SN1/{data['request_id']}/register_response", {"client_id": self.client_id, "error": "ok"}
                ),
            )
        else:
            result = {
                "error_code": 0,
                "machine_status": {"status": 2, "progress": 45},
                "print_status": {
                    "filename": "a.gcode",
                    "current_layer": 3,
                    "total_layer": 10,
                    "remaining_time_sec": 600,
                },
                "extruder": {"temperature": 215, "target": 220},
                "heater_bed": {"temperature": 60, "target": 60},
            }
            self.on_message(
                None,
                None,
                FakeMsg(
                    topic.replace("api_request", "api_response"),
                    {"id": data["id"], "method": data["method"], "result": result},
                ),
            )


def test_printer_status_and_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(printer, "discover", lambda host, timeout=8.0: {"sn": "SN1"})
    made: list[FakeMqtt] = []

    def factory(cid: str) -> FakeMqtt:
        made.append(FakeMqtt(cid))
        return made[-1]

    spec = printer.PrinterSpec("192.168.1.60", "")
    s = printer.run_action(spec, "status", mqtt_factory=factory)
    assert s["state"] == "printing" and s["progress"] == 45 and s["remaining_min"] == 10
    assert made[0].auth == ("elegoo", "123456")
    printer.run_action(printer.PrinterSpec("192.168.1.60", "9999"), "start", "part.gcode", mqtt_factory=factory)
    topic, body = made[1].published[-1]
    assert topic.endswith("/api_request") and body["method"] == 1020 and body["params"]["filename"] == "part.gcode"
    assert made[1].auth == ("elegoo", "9999")
    with pytest.raises(printer.PrinterError):
        printer.run_action(spec, "start", "../x.gcode", mqtt_factory=factory)
    with pytest.raises(printer.PrinterError):
        printer.check_host("8.8.8.8")


def test_printer_upload_chunks(tmp_path: Path) -> None:
    f = tmp_path / "a.gcode"
    f.write_bytes(b"G1 X1\n" * 400_000)  # ~2.4 MB -> 3 chunks
    seen: list[str] = []

    class Resp:
        def __enter__(self) -> Resp:
            return self

        def __exit__(self, *a: object) -> None: ...

        def read(self, n: int) -> bytes:
            return b'{"error_code": 0, "offset": 1}'

    def opener(req: Any, timeout: int) -> Resp:
        assert req.full_url == "http://192.168.1.60/upload" and req.get_method() == "PUT"
        seen.append(req.headers["Content-range"])
        return Resp()

    out = printer.upload(printer.PrinterSpec("192.168.1.60", ""), f, "a.gcode", opener=opener)
    assert len(seen) == 3 and seen[0].startswith("bytes 0-1048575/") and out["size"] == f.stat().st_size


def test_printer_routes_need_confirm(exec_client: TestClient) -> None:  # noqa: F811
    assert exec_client.post("/api/printer/start", json={"file": "a.gcode"}).status_code == 400
    assert exec_client.post("/api/printer-upload", json={"path": "x.gcode"}).status_code == 400


def test_slice_command_quotes_paths() -> None:
    cmd = printer.slice_command("linux", "~/models/cube.stl", "0.4", "", "", "ember-prints")
    assert '"$HOME/models/cube.stl"' in cmd and "Elegoo Centauri Carbon 2 0.4 nozzle.json" in cmd
    with pytest.raises(printer.PrinterError):
        printer.slice_command("linux", "~/m.stl", "0.5", "", "", "out")
    with pytest.raises(ValueError):
        check_remote_path("~/a$(reboot).stl")


# ---------- write_file through the agent ----------
def test_write_file_shows_diff_and_needs_confirm(
    exec_client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = Path.home() / "ember-test-write.txt"
    target.write_text("port=1\n")
    try:
        rel = "~/ember-test-write.txt"
        monkeypatch.setattr(agent, "stream_chat", ToolScript([("write_file", {"path": rel, "content": "port=2\n"})]))
        events = _send(exec_client, "change port", exec_client.target_id)  # type: ignore[attr-defined]
        card = next(e["action"] for e in events if e["type"] == "confirm")
        assert card["kind"] == "write_file" and "-port=1" in card["diff"] and "+port=2" in card["diff"]
        assert target.read_text() == "port=1\n"
        r = exec_client.post(f"/api/actions/{card['id']}/decide", json={"run": True})
        assert any(e["type"] == "action" and e["action"]["status"] == "ran" for e in _events(r.text))
        assert target.read_text() == "port=2\n"
        assert (Path.home() / "ember-test-write.txt.bak-ember").read_text() == "port=1\n"
    finally:
        target.unlink(missing_ok=True)
        (Path.home() / "ember-test-write.txt.bak-ember").unlink(missing_ok=True)


def test_run_command_on_unset_radio_host(exec_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(agent, "stream_chat", ToolScript([("run_command", {"command": "ls", "on": "radio"}), "ok"]))
    ran: list[str] = []
    monkeypatch.setattr(agent, "run_local", lambda c, t: ran.append(c) or RunResult(0, ""))
    events = _send(exec_client, "list", exec_client.target_id)  # type: ignore[attr-defined]
    assert ran == [] and events[-1]["type"] == "done"


# ---------- parts library + radio KB ----------
def test_parts_library(tmp_path: Path) -> None:
    stl = tmp_path / "knob.stl"
    stl.write_text("solid x\nendsolid x\n")
    conn = parts.open_db(tmp_path)
    with pytest.raises(parts.PartsError):
        parts.add_part(conn, tmp_path, {"name": "x", "category": "household", "license": ""}, [stl])
    with pytest.raises(parts.PartsError):
        parts.add_part(conn, tmp_path, {"name": "x", "category": "household", "license": "All rights reserved"}, [stl])
    pid = parts.add_part(
        conn,
        tmp_path,
        {
            "name": "Radio knob",
            "category": "household",
            "license": "CC-BY-4.0",
            "tags": "knob potentiometer",
            "source_url": "https://example.org/k",
        },
        [stl],
    )
    parts.add_guide(
        conn,
        {
            "title": "Replace a faucet cartridge",
            "license": "CC-BY-NC-SA-3.0",
            "source_url": "https://www.ifixit.com/Guide/_/1",
        },
        "Step 1: shut off water",
    )
    hits = parts.search(conn, "knob", 5)
    assert hits[0]["id"] == pid and hits[0]["files"][0]["name"] == "knob.stl"
    assert parts.search(conn, "faucet", 5)[0]["kind"] == "guide"
    with pytest.raises(parts.PartsError):
        parts.part_file(tmp_path, conn, pid, "../library.db")
    kb = parts.PartsKB(tmp_path).search("knob", 3)
    assert kb[0]["source"].endswith("CC-BY-4.0")


def test_radio_kb_parsing() -> None:
    html = (
        "<html><nav>menu</nav><h2>GMRS channels</h2><table><tr><td>1</td><td>462.5625</td></tr></table>"
        "<script>x()</script><p>Main channels.</p></html>"
    )
    secs = html_sections(html)
    assert secs[0][0] == "GMRS channels" and "1 | 462.5625" in secs[0][1] and "menu" not in str(secs)
    assert chunks([("h", "line\n" * 2000)])




def test_buildhost_script_dry_run(tmp_path: Path) -> None:
    import subprocess  # noqa: PLC0415

    script = Path(__file__).resolve().parent.parent / "coldboot/buildhost/install-buildhost.sh"
    if not shutil.which("bash"):
        pytest.skip("no bash")
    out = subprocess.run(["bash", str(script), "--help"], capture_output=True, text=True, check=True)  # noqa: S603,S607
    assert "--chirp-only" in out.stdout


# ---------- parts seed: licenses, de-dup, cap ----------
def _importer() -> Any:
    import importlib.util  # noqa: PLC0415

    path = Path(__file__).resolve().parent.parent / "scripts/parts_import.py"
    spec = importlib.util.spec_from_file_location("parts_import", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tarball(files: dict[str, bytes]) -> bytes:
    import io  # noqa: PLC0415
    import tarfile  # noqa: PLC0415

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo("repo-main/" + name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


MIT_TEXT = b"MIT License\nPermission is hereby granted, free of charge"


def test_seed_license_rules_dedup_and_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pi = _importer()
    assert pi.license_text_matches("MIT", MIT_TEXT.decode())
    assert not pi.license_text_matches("GPL-3.0", MIT_TEXT.decode())
    assert pi.license_text_matches("CC-BY-NC-4.0", "Creative Commons Attribution-NonCommercial")
    repos = {
        "a/clean": {"LICENSE": MIT_TEXT, "knob.stl": b"solid a", "dup.stl": b"solid same"},
        "a/mixed": {"LICENSE": MIT_TEXT, "LICENSE-CASE.md": b"CC BY-NC", "case.stl": b"solid b"},
        "a/sub": {"LICENSE": MIT_TEXT, "own.stl": b"solid c", "vendor/LICENSE.txt": b"other", "vendor/v.stl": b"x"},
        "a/copy": {"LICENSE": MIT_TEXT, "again.stl": b"solid same"},
    }
    monkeypatch.setattr(pi, "get", lambda url, limit=0: _tarball(repos["/".join(url.split("/")[3:5])]))
    conn = parts.open_db(tmp_path)
    seen = parts.known_hashes(conn)
    budget = pi.Budget(10_000)
    src = {"ref": "main", "license": "MIT", "category": "household"}
    assert pi.seed_github(conn, tmp_path, {**src, "repo": "a/clean"}, budget, seen) == 1
    assert pi.seed_github(conn, tmp_path, {**src, "repo": "a/mixed"}, budget, seen) == 0  # two root licenses
    assert pi.seed_github(conn, tmp_path, {**src, "repo": "a/sub"}, budget, seen) == 1
    sub = parts.search(conn, "sub", 5)[0]
    assert [f["name"] for f in sub["files"]] == ["own.stl"]  # vendor/ has its own license -> left out
    assert pi.seed_github(conn, tmp_path, {**src, "repo": "a/copy"}, budget, seen) == 0  # identical file
    assert pi.seed_github(conn, tmp_path, {**src, "repo": "a/clean"}, budget, seen) == 0  # already there
    assert (
        pi.seed_github(
            conn,
            tmp_path,
            {**src, "repo": "a/mixed", "license": "CC-BY-NC-4.0", "license_file": "LICENSE-CASE.md"},
            budget,
            seen,
        )
        == 0
    )  # vague text
    tiny = pi.Budget(1)
    repos["a/big"] = {"LICENSE": MIT_TEXT, "big.stl": b"solid big part"}
    assert pi.seed_github(conn, tmp_path, {**src, "repo": "a/big"}, tiny, seen) == 0 and tiny.full
    pid = sub["id"]
    assert parts.remove_part(conn, tmp_path, pid) and not parts.remove_part(conn, tmp_path, pid)
