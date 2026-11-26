"""ColdBoot script tests: dry-run safety, backup/restore integrity, model helper."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "coldboot.sh"
CBMODELS = REPO / "coldboot" / "cbmodels.py"
SECRET = "SECRET-KEY-MUST-NOT-PRINT"
BASH = shutil.which("bash") or "/bin/bash"


def run(args: list[str], home: Path, check: bool = True, **env: str) -> subprocess.CompletedProcess[str]:
    full_env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "USER": "tester",
        "COLDBOOT_KIT": str(home / "no-kit"),
        "COLDBOOT_OLLAMA_URL": "http://127.0.0.1:9",
        "COLDBOOT_QDRANT_URL": "http://127.0.0.1:9",
        **env,
    }
    result = subprocess.run(  # noqa: S603
        [BASH, str(SCRIPT), *args], env=full_env, capture_output=True, text=True, timeout=120, input=""
    )
    if check and result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return result


def tree(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir"
    return out


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    (h / ".config/ember/tls").mkdir(parents=True)
    (h / ".local/share/ember").mkdir(parents=True)
    (h / ".config/goose").mkdir(parents=True)
    key = h / ".config/ember/secret.key"
    key.write_text(SECRET)
    key.chmod(0o600)
    (h / ".config/ember/ember.env").write_text("EMBER_PORT=8600\n")
    (h / ".config/ember/tls/ember.key").write_text("tls-key")
    (h / ".config/ember/tls/ember.crt").write_text("tls-crt")
    (h / ".config/goose/config.yaml").write_text("GOOSE_MODE: approve\n")
    conn = sqlite3.connect(h / ".local/share/ember/ember.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE targets (name TEXT)")
    conn.execute("INSERT INTO targets VALUES ('zorin')")
    conn.commit()
    conn.close()
    return h


def make_backup(home: Path, out: Path) -> tuple[Path, str]:
    result = run(["backup", "--out", str(out)], home)
    archives = list(out.glob("*.tar.gz"))
    assert len(archives) == 1
    return archives[0], result.stdout + result.stderr


def test_shellcheck_clean() -> None:
    exe = shutil.which("shellcheck") or str(Path(sys.executable).parent / "shellcheck")
    if not Path(exe).exists():
        pytest.skip("shellcheck not installed")
    scripts = [SCRIPT, REPO / "install.sh", REPO / "bin" / "ember"]
    subprocess.run([exe, "-x", *map(str, scripts)], check=True, timeout=120)  # noqa: S603


def test_dry_run_install_changes_nothing(tmp_path: Path) -> None:
    h = tmp_path / "empty-home"
    h.mkdir()
    (h / ".bashrc").write_text("# mine\n")
    before = tree(h)
    result = run(["install", "--dry-run"], h)
    assert "DRY RUN" in result.stdout
    assert "[dry-run] would: install" in result.stdout
    assert tree(h) == before


def test_backup_restore_roundtrip(home: Path, tmp_path: Path) -> None:
    archive, output = make_backup(home, tmp_path / "bk")
    assert SECRET not in output
    assert "CONTAINS EMBER'S SECRET KEY" in output
    assert oct(archive.stat().st_mode & 0o777) == "0o600"
    target = tmp_path / "restored"
    result = run(["restore", str(archive), "--to", str(target)], home)
    assert SECRET not in result.stdout + result.stderr
    assert "checksums OK" in result.stdout
    assert (target / ".config/ember/secret.key").read_text() == SECRET
    assert oct((target / ".config/ember/secret.key").stat().st_mode & 0o777) == "0o600"
    rows = sqlite3.connect(target / ".local/share/ember/ember.db").execute("SELECT name FROM targets").fetchall()
    assert rows == [("zorin",)]


def test_restore_dry_run_writes_nothing(home: Path, tmp_path: Path) -> None:
    archive, _ = make_backup(home, tmp_path / "bk")
    target = tmp_path / "restored"
    run(["restore", str(archive), "--to", str(target), "--dry-run"], home)
    assert not target.exists()


def test_restore_keeps_old_copy(home: Path, tmp_path: Path) -> None:
    archive, _ = make_backup(home, tmp_path / "bk")
    target = tmp_path / "restored"
    (target / ".config/goose").mkdir(parents=True)
    (target / ".config/goose/config.yaml").write_text("old\n")
    run(["restore", str(archive), "--to", str(target)], home)
    olds = list((target / ".config/goose").glob("config.yaml.pre-restore-*"))
    assert len(olds) == 1 and olds[0].read_text() == "old\n"


def test_restore_rejects_bad_archive_checksum(home: Path, tmp_path: Path) -> None:
    archive, _ = make_backup(home, tmp_path / "bk")
    sums = Path(str(archive) + ".sha256")
    sums.write_text("0" * 64 + "  " + archive.name + "\n")
    result = run(["restore", str(archive), "--to", str(tmp_path / "r")], home, check=False)
    assert result.returncode != 0
    assert "does NOT match" in result.stderr
    assert not (tmp_path / "r").exists()


def rewrite_archive(archive: Path, change: dict[str, bytes], extra: list[tarfile.TarInfo] | None = None) -> None:
    members: list[tuple[tarfile.TarInfo, bytes | None]] = []
    with tarfile.open(archive) as tar:
        for m in tar.getmembers():
            data = tar.extractfile(m).read() if m.isfile() else None  # type: ignore[union-attr]
            if m.name in change:
                data = change[m.name]
                m.size = len(data)
            members.append((m, data))
    with tarfile.open(archive, "w:gz") as tar:
        for m, data in members:
            tar.addfile(m, io.BytesIO(data) if data is not None else None)
        for info in extra or []:
            tar.addfile(info, io.BytesIO(b"x" * info.size) if info.isfile() else None)
    Path(str(archive) + ".sha256").unlink()


def test_restore_detects_tampered_file(home: Path, tmp_path: Path) -> None:
    archive, _ = make_backup(home, tmp_path / "bk")
    rewrite_archive(archive, {"home/.config/goose/config.yaml": b"GOOSE_MODE: auto\n"})
    result = run(["restore", str(archive), "--to", str(tmp_path / "r")], home, check=False)
    assert result.returncode != 0
    assert "do NOT match" in result.stderr
    assert not (tmp_path / "r").exists()


def test_restore_rejects_path_traversal(home: Path, tmp_path: Path) -> None:
    archive, _ = make_backup(home, tmp_path / "bk")
    evil = tarfile.TarInfo("home/../../evil.txt")
    evil.size = 1
    rewrite_archive(archive, {}, [evil])
    result = run(["restore", str(archive), "--to", str(tmp_path / "r")], home, check=False)
    assert result.returncode != 0
    assert "unsafe path" in result.stderr
    assert not list(tmp_path.rglob("evil.txt"))


def test_restore_rejects_symlink(home: Path, tmp_path: Path) -> None:
    archive, _ = make_backup(home, tmp_path / "bk")
    link = tarfile.TarInfo("home/.ssh/authorized_keys")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    rewrite_archive(archive, {}, [link])
    result = run(["restore", str(archive), "--to", str(tmp_path / "r")], home, check=False)
    assert result.returncode != 0
    assert "links or special files" in result.stderr


def test_restore_rejects_unlisted_file(home: Path, tmp_path: Path) -> None:
    archive, _ = make_backup(home, tmp_path / "bk")
    extra = tarfile.TarInfo("home/.bashrc")
    extra.size = 4
    rewrite_archive(archive, {}, [extra])
    result = run(["restore", str(archive), "--to", str(tmp_path / "r")], home, check=False)
    assert result.returncode != 0
    assert "not covered by SHA256SUMS" in result.stderr


# ---------- cbmodels ----------


def fake_store(root: Path, name: str, tag: str, blobs: dict[str, bytes]) -> None:
    (root / "blobs").mkdir(parents=True, exist_ok=True)
    layers = []
    for data in blobs.values():
        digest = hashlib.sha256(data).hexdigest()
        (root / "blobs" / f"sha256-{digest}").write_bytes(data)
        layers.append({"digest": f"sha256:{digest}", "size": len(data)})
    mf = root / "manifests/registry.ollama.ai/library" / name / tag
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text(json.dumps({"config": layers[0], "layers": layers[1:]}))


def cbmodels(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(CBMODELS), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {})},
    )


def test_cbmodels_export_import_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "store"
    fake_store(src, "llama3.2", "1b", {"cfg": b"config", "w": b"weights" * 100})
    fake_store(src, "nomic-embed-text", "v1.5", {"cfg": b"config2", "w": b"embed"})
    cache = tmp_path / "cache"
    r = cbmodels("export", "--store", str(src), "--dest", str(cache), "llama3.2:1b", "nomic-embed-text:v1.5")
    assert r.returncode == 0, r.stderr
    new_store = tmp_path / "new"
    r = cbmodels("import", "--src", str(cache), "--store", str(new_store))
    assert r.returncode == 0, r.stderr
    assert tree(new_store) == tree(src)
    r = cbmodels("import", "--src", str(cache), "--store", str(new_store))
    assert "kept" in r.stdout


def test_cbmodels_detects_corrupt_blob(tmp_path: Path) -> None:
    src = tmp_path / "store"
    fake_store(src, "llama3.2", "1b", {"cfg": b"config", "w": b"weights"})
    blob = next(p for p in (src / "blobs").iterdir() if p.stat().st_size == 7)
    blob.write_bytes(b"WEIGHTS")
    r = cbmodels("export", "--store", str(src), "--dest", str(tmp_path / "c"), "llama3.2:1b")
    assert r.returncode == 2
    assert "CHECKSUM MISMATCH" in r.stderr
    assert not list((tmp_path / "c").rglob("*.part"))


def test_cbmodels_rejects_bad_name_and_remote_url(tmp_path: Path) -> None:
    r = cbmodels("export", "--store", str(tmp_path), "--dest", str(tmp_path / "c"), "../x:y")
    assert r.returncode == 2
    r = cbmodels(
        "check", "--spec", str(REPO / "coldboot/models.json"), env={"COLDBOOT_OLLAMA_URL": "http://10.0.0.1:1"}
    )
    assert r.returncode == 2 and "loopback" in r.stderr


class FakeOllama(BaseHTTPRequestHandler):
    models = ["qwen3.5:9b", "llama3.2:latest", "llama3.2:1b", "nomic-embed-text:v1.5", "qwen3.5-9b-4k:latest"]
    created: list[dict[str, Any]] = []

    def reply(self, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        self.reply({"models": [{"name": m} for m in self.models]})

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/create":
            FakeOllama.created.append(body)
            self.reply({"status": "success"})
        else:
            self.reply({"parameters": "num_ctx                        4096\ntop_k 20"})

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture()
def ollama() -> Any:
    server = HTTPServer(("127.0.0.1", 0), FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield {"COLDBOOT_OLLAMA_URL": f"http://127.0.0.1:{server.server_port}"}
    server.shutdown()


def test_cbmodels_missing_check_create(ollama: dict[str, str]) -> None:
    spec = str(REPO / "coldboot/models.json")
    r = cbmodels("missing", "--spec", spec, env=ollama)
    assert r.stdout.split("\n")[:3] == ["custom qwen3.5-9b-8k", "custom llama3.2-4k", "custom llama3.2-1b-4k"]
    r = cbmodels("check", "--spec", spec, env=ollama)
    assert r.returncode == 1
    assert "PASS model qwen3.5-9b-4k (num_ctx 4096, want 4096)" in r.stdout
    assert "FAIL model llama3.2-4k (missing)" in r.stdout
    r = cbmodels("create", "--spec", spec, "llama3.2-4k", env=ollama)
    assert r.returncode == 0, r.stderr
    body = FakeOllama.created[-1]
    assert body["from"] == "llama3.2:latest" and body["parameters"]["num_ctx"] == 4096


def test_spec_and_pins_are_consistent() -> None:
    spec = json.loads((REPO / "coldboot/models.json").read_text())
    for item in spec["custom"]:
        assert item["from"] in spec["base"]
        want = 8192 if item["name"].endswith("-8k") else 4096
        assert item["parameters"]["num_ctx"] == want
    for line in (REPO / "coldboot/pins.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            name, sha, rel, url = line.split()
            assert len(sha) == 64 and not rel.startswith("/") and (url == "-" or url.startswith("https://"))
    config = (REPO / "coldboot/stack/configs/goose/config.yaml").read_text()
    assert "GOOSE_MODE: approve" in config and "__HOME__/.local/bin/nomad-search-mcp" in config
