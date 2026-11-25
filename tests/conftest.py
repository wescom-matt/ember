from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ember import auth, ollama
from ember.app import create_app
from ember.config import Settings
from ember.db import connect

ADMIN_PW = "admin-pass-1234"
USER_PW = "user-pass-12345"


class FakeKB:
    id = "nomad"
    label = "Nomad"
    description = "fake"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        self.queries.append(query)
        return [
            {
                "rank": 1,
                "score": 0.9,
                "title": "Burns",
                "section": "",
                "source": "medlineplus",
                "path": "a",
                "text": "Cool the burn.",
            }
        ]


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        ollama_url="http://127.0.0.1:11434",
        qdrant_url="http://127.0.0.1:6333",
        default_model="qwen3.5-9b-4k",
        host="127.0.0.1",
        port=8600,
        secure_cookies=False,
    )


@pytest.fixture()
def fake_ollama(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {"messages": None}

    def list_models(base_url: str) -> list[dict[str, Any]]:
        return [{"name": "qwen3.5-9b-4k:latest", "size": 1}, {"name": "llama3.2-4k:latest", "size": 1}]

    def stream_chat(
        base_url: str, model: str, messages: list[dict[str, str]], think: bool
    ) -> Iterator[tuple[str, str]]:
        calls["messages"] = messages
        calls["model"] = model
        yield ("content", "Hello ")
        yield ("content", "there [1].")

    monkeypatch.setattr(ollama, "list_models", list_models)
    monkeypatch.setattr(ollama, "supports_thinking", lambda base_url, model: False)
    monkeypatch.setattr("ember.chat.stream_chat", stream_chat)
    return calls


@pytest.fixture()
def kb() -> FakeKB:
    return FakeKB()


@pytest.fixture()
def client(settings: Settings, fake_ollama: dict[str, Any], kb: FakeKB) -> TestClient:
    auth.THROTTLE.reset()
    app = create_app(settings, kbs={"nomad": kb})
    with connect(settings.db_path) as conn:
        auth.create_user(conn, "matt", ADMIN_PW, is_admin=True)
        auth.create_user(conn, "rain", USER_PW, is_admin=False)
    c = TestClient(app)
    c.headers.update({"X-Ember": "1"})
    return c


def login(c: TestClient, user: str, pw: str) -> None:
    r = c.post("/api/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
