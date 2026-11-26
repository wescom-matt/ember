"""v0.5.0: projects view, dev docs KB, project cache helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ember import projects
from ember.dev_kb import DEV_SOURCES, DevKB
from ember.kb import build_registry
from tests.conftest import ADMIN_PW, USER_PW, login

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "coldboot"))
import projects_cache  # noqa: E402


def test_seed_loads_and_has_outpost(settings: Any) -> None:
    items = projects.load(settings.data_dir)
    names = {p["name"] for p in items}
    assert {"Outpost", "Outpost 2.0 (Heltec V4)", "ember"} <= names
    outpost = next(p for p in items if p["name"] == "Outpost")
    assert outpost["host"] == "Los Gatos" and outpost["backup_host"] == "Mint"
    assert outpost["env"] == "heltec_v3_arduino3"


def test_validate_rejects_bad_input() -> None:
    with pytest.raises(projects.ProjectsError):
        projects.validate([{"name": "a"}, {"name": "A"}])
    with pytest.raises(projects.ProjectsError):
        projects.validate([{"name": "x", "commands": [{"name": "b", "cmd": "y" * 600}]}])
    with pytest.raises(projects.ProjectsError):
        projects.validate("nope")
    ok = projects.validate({"projects": [{"name": " x ", "offline": "bad"}]})
    assert ok[0]["name"] == "x" and ok[0]["offline"] == {}


def test_save_and_prompt_text(settings: Any) -> None:
    projects.save(
        settings.data_dir,
        [{"name": "P", "host": "Mint", "folder": "~/p", "commands": [{"name": "build", "cmd": "make"}]}],
    )
    assert [p["name"] for p in projects.load(settings.data_dir)] == ["P"]
    text = projects.prompt_text(settings.data_dir)
    assert "Mint:~/p" in text and "make" in text
    assert len(projects.prompt_text(settings.data_dir)) <= projects.MAX_PROMPT_CHARS


def test_projects_routes(client: TestClient) -> None:
    login(client, "rain", USER_PW)
    r = client.get("/api/projects")
    assert r.status_code == 200 and any(p["name"] == "Outpost" for p in r.json()["projects"])
    assert client.put("/api/admin/projects", json={"projects": []}).status_code == 403
    client.post("/api/logout")
    login(client, "matt", ADMIN_PW)
    assert client.put("/api/admin/projects", json={"projects": [{"name": "a"}, {"name": "a"}]}).status_code == 400
    r = client.put("/api/admin/projects", json={"projects": [{"name": "Only"}]})
    assert r.status_code == 200
    assert [p["name"] for p in client.get("/api/projects").json()["projects"]] == ["Only"]


def test_dev_kb_registered(tmp_path: Path) -> None:
    reg = build_registry("http://127.0.0.1:1", "http://127.0.0.1:1", tmp_path)
    assert isinstance(reg.get("dev"), DevKB)
    ids = {s["id"] for s in DEV_SOURCES}
    assert {"sx1262-datasheet", "ax25-2.2", "kiss", "heltec-v4r8", "heltec-v4r8-schematic"} <= ids


def test_core_name_and_lib_version(tmp_path: Path) -> None:
    url = "https://github.com/pioarduino/platform-espressif32/releases/download/55.03.312/platform.zip"
    a = projects_cache.Cache.core_name(url, ["x"])
    assert a.startswith("pioarduino-55.03.312-") and a != projects_cache.Cache.core_name(url, ["y"])
    assert projects_cache.Cache.core_name("espressif32@7.1.3", []) == "espressif32@7.1.3"
    (tmp_path / "library.json").write_text(json.dumps({"version": "7.8.1"}))
    assert projects_cache.lib_version(tmp_path) == "7.8.1"
    other = tmp_path / "o"
    other.mkdir()
    (other / "library.properties").write_text("name=X\nversion=2.5.17\n")
    assert projects_cache.lib_version(other) == "2.5.17"
