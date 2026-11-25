from __future__ import annotations

import pytest

from ember import auth, config, kb, ollama
from ember.chat import build_messages


def test_loopback_only() -> None:
    assert config.require_loopback_url("http://localhost:11434", "x") == "http://127.0.0.1:11434"
    for bad in ("https://127.0.0.1", "http://10.0.0.1:1", "http://u:p@127.0.0.1", "http://127.0.0.1/x", "file:///etc"):
        with pytest.raises(ValueError):
            config.require_loopback_url(bad, "x")


def test_password_hash_roundtrip() -> None:
    h = auth.hash_password("correct-horse-1")
    assert h.startswith("$argon2id$")
    assert auth.verify_password(h, "correct-horse-1")
    assert not auth.verify_password(h, "wrong")
    assert not auth.verify_password("not-a-hash", "x")
    with pytest.raises(ValueError):
        auth.hash_password("short")


def test_username_rules() -> None:
    assert auth.clean_username(" Matt ") == "matt"
    for bad in ("a", "has space", "../x", "x" * 40, "-lead"):
        with pytest.raises(ValueError):
            auth.clean_username(bad)


def test_normalize_model() -> None:
    names = {"qwen3.5-9b-4k:latest", "llama3.1:8b"}
    assert ollama.normalize_model("qwen3.5-9b-4k", names) == "qwen3.5-9b-4k:latest"
    assert ollama.normalize_model("llama3.1:8b", names) == "llama3.1:8b"
    assert ollama.normalize_model("nope", names) is None


def test_snippet_and_dedupe() -> None:
    hit = {"score": 0.5, "payload": {"full_title": "T", "archive_title": "A", "article_path": "p", "text": "x" * 2000}}
    s = kb._snippet(hit)
    assert s["title"] == "T" and s["source"] == "A" and len(s["text"]) <= kb.MAX_SNIPPET_CHARS + 3
    out = kb._dedupe([kb._snippet(hit), kb._snippet(hit)], 4)
    assert len(out) == 1 and out[0]["rank"] == 1


def test_build_messages_context() -> None:
    msgs = build_messages([{"role": "user", "content": "hi"}], "CTX")
    assert msgs[0]["role"] == "system" and msgs[0]["content"].endswith("CTX")
    assert msgs[1] == {"role": "user", "content": "hi"}


def test_throttle_bounded() -> None:
    t = auth.LoginThrottle()
    for i in range(auth.MAX_TRACKED + 50):
        t.fail(f"u{i}")
    assert len(t._fails) <= auth.MAX_TRACKED
