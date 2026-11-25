from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from ember import __version__
from tests.conftest import ADMIN_PW, USER_PW, FakeKB, login


def _events(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_version_and_security_headers(client: TestClient) -> None:
    r = client.get("/api/version")
    assert r.json() == {"version": __version__}
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_index_and_vendored_assets(client: TestClient) -> None:
    html = client.get("/").text
    assert "http://" not in html and "https://" not in html  # no CDN
    assert client.get("/static/vendor/highlight.min.js").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_requires_login(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/conversations").status_code == 401


def test_bad_login_is_generic_and_locks(client: TestClient) -> None:
    for _ in range(5):
        r = client.post("/api/login", json={"username": "matt", "password": "nope-nope-nope"})
        assert r.status_code == 401
        assert r.json()["detail"] == "wrong username or password"
    r = client.post("/api/login", json={"username": "matt", "password": ADMIN_PW})
    assert r.status_code == 401
    assert "too many" in r.json()["detail"]


def test_login_cookie_flags(client: TestClient) -> None:
    r = client.post("/api/login", json={"username": "matt", "password": ADMIN_PW})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert ADMIN_PW not in r.text


def test_csrf_header_required(client: TestClient) -> None:
    r = client.post("/api/login", json={"username": "matt", "password": ADMIN_PW}, headers={"X-Ember": ""})
    assert r.status_code == 403


def test_chat_flow_with_sources(client: TestClient, fake_ollama: dict[str, Any], kb: FakeKB) -> None:
    login(client, "matt", ADMIN_PW)
    models = client.get("/api/models").json()
    assert models["default"] == "qwen3.5-9b-4k:latest"
    conv = client.post("/api/conversations", json={"model": "", "kb": "nomad"}).json()
    r = client.post(
        f"/api/conversations/{conv['id']}/messages",
        json={"content": "How to treat a burn?", "model": "qwen3.5-9b-4k", "kb": "nomad"},
    )
    assert r.status_code == 200
    events = _events(r.text)
    kinds = [e["type"] for e in events]
    assert "sources" in kinds and kinds[-1] == "done"
    assert kb.queries == ["How to treat a burn?"]
    system = fake_ollama["messages"][0]["content"]
    assert "Cool the burn." in system and "ESP32" in system
    detail = client.get(f"/api/conversations/{conv['id']}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["content"] == "Hello there [1]."
    assert detail["messages"][1]["sources"][0]["source"] == "medlineplus"
    assert detail["conversation"]["title"].startswith("How to treat")


def test_rejects_unknown_model_and_kb(client: TestClient) -> None:
    login(client, "matt", ADMIN_PW)
    conv = client.post("/api/conversations", json={"kb": "none"}).json()
    r = client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "hi", "model": "evil", "kb": "none"})
    assert r.status_code == 400
    r = client.post(
        f"/api/conversations/{conv['id']}/messages", json={"content": "hi", "model": "llama3.2-4k", "kb": "../etc"}
    )
    assert r.status_code == 400


def test_history_is_private_per_user(client: TestClient) -> None:
    login(client, "matt", ADMIN_PW)
    conv = client.post("/api/conversations", json={"kb": "none"}).json()
    client.post("/api/logout")
    login(client, "rain", USER_PW)
    assert client.get(f"/api/conversations/{conv['id']}").status_code == 404
    assert client.delete(f"/api/conversations/{conv['id']}").status_code == 404
    assert client.get("/api/conversations").json()["conversations"] == []


def test_rename_search_delete(client: TestClient) -> None:
    login(client, "matt", ADMIN_PW)
    conv = client.post("/api/conversations", json={"kb": "none"}).json()
    client.post(
        f"/api/conversations/{conv['id']}/messages", json={"content": "LoRa range test", "model": "llama3.2-4k"}
    )
    assert client.patch(f"/api/conversations/{conv['id']}", json={"title": "Radio"}).status_code == 200
    found = client.get("/api/conversations", params={"q": "lora"}).json()["conversations"]
    assert [c["title"] for c in found] == ["Radio"]
    assert client.get("/api/conversations", params={"q": "100%_"}).json()["conversations"] == []
    assert client.delete(f"/api/conversations/{conv['id']}").status_code == 200
    assert client.get("/api/conversations").json()["conversations"] == []


def test_admin_only_routes(client: TestClient) -> None:
    login(client, "rain", USER_PW)
    assert client.get("/api/admin/users").status_code == 403
    assert client.post("/api/admin/users", json={"username": "x1", "password": "p" * 12}).status_code == 403


def test_admin_manages_users(client: TestClient) -> None:
    login(client, "matt", ADMIN_PW)
    r = client.post("/api/admin/users", json={"username": "guest", "password": "guest-pass-123", "is_admin": False})
    assert r.status_code == 200
    users = {u["username"]: u for u in client.get("/api/admin/users").json()["users"]}
    assert "pw_hash" not in users["guest"]
    rain = users["rain"]["id"]
    assert client.patch(f"/api/admin/users/{rain}", json={"is_admin": True}).status_code == 200
    assert client.patch(f"/api/admin/users/{rain}", json={"is_admin": False}).status_code == 200
    me = users["matt"]["id"]
    r = client.patch(f"/api/admin/users/{me}", json={"is_admin": False})
    assert r.status_code == 400  # last admin is protected
    assert client.post("/api/admin/users", json={"username": "Bad Name!", "password": "x" * 12}).status_code == 400


def test_disabled_user_cannot_log_in(client: TestClient) -> None:
    login(client, "matt", ADMIN_PW)
    users = {u["username"]: u for u in client.get("/api/admin/users").json()["users"]}
    client.patch(f"/api/admin/users/{users['rain']['id']}", json={"is_active": False})
    client.post("/api/logout")
    r = client.post("/api/login", json={"username": "rain", "password": USER_PW})
    assert r.status_code == 401


def test_change_password(client: TestClient) -> None:
    login(client, "rain", USER_PW)
    r = client.post("/api/me/password", json={"current": "wrong-wrong", "new": "brand-new-pass-1"})
    assert r.status_code == 400
    r = client.post("/api/me/password", json={"current": USER_PW, "new": "brand-new-pass-1"})
    assert r.status_code == 200
    assert client.get("/api/me").status_code == 401  # sessions ended
    login(client, "rain", "brand-new-pass-1")


def test_kb_failure_degrades(client: TestClient, kb: FakeKB, monkeypatch: Any) -> None:
    def boom(query: str, top_k: int) -> list[dict[str, Any]]:
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(kb, "search", boom)
    login(client, "matt", ADMIN_PW)
    conv = client.post("/api/conversations", json={"kb": "nomad"}).json()
    r = client.post(
        f"/api/conversations/{conv['id']}/messages", json={"content": "q", "model": "llama3.2-4k", "kb": "nomad"}
    )
    kinds = [e["type"] for e in _events(r.text)]
    assert "notice" in kinds and kinds[-1] == "done"
