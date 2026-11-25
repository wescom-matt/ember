"""Process-wide settings, loaded once at startup. No secrets live here.

Values come from the environment (systemd loads ~/.config/ember/ember.env).
Every backend URL must be loopback; Ember never calls the internet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_BACKEND_HOSTS = frozenset({"127.0.0.1", "localhost"})
DEFAULT_MODEL = "qwen3.5-9b-4k"
DEFAULT_PORT = 8600

# Hard caps (Power of 10 rule 3: nothing grows without a bound).
MAX_USERNAME = 32
MIN_PASSWORD = 10
MAX_PASSWORD = 256
MAX_TITLE = 120
MAX_MESSAGE_CHARS = 16_000
MAX_REPLY_CHARS = 60_000
MAX_CONVERSATIONS_LIST = 300
MAX_MESSAGES_PER_CONVERSATION = 2_000
MAX_SEARCH_CHARS = 100
MAX_USERS = 50
HISTORY_CHAR_BUDGET = 7_000
HISTORY_MAX_TURNS = 12
SESSION_HOURS = 24 * 7
MAX_SESSIONS_PER_USER = 10
OLLAMA_CONNECT_TIMEOUT_SEC = 30
OLLAMA_STREAM_IDLE_TIMEOUT_SEC = 300
OLLAMA_MAX_STREAM_LINES = 50_000
MAX_HTTP_BYTES = 2_000_000

# Phase 2 command execution limits.
MAX_TOOL_STEPS = 4
COMMAND_TIMEOUT_SEC = 120
SSH_CONNECT_TIMEOUT_SEC = 10
MAX_COMMAND_CHARS = 2_000
MAX_OUTPUT_STORE = 8_000
MAX_OUTPUT_TO_MODEL = 2_500
MAX_TARGETS = 50
MAX_CREDENTIALS = 50
MAX_CONTEXT_CHARS = 24_000


def require_loopback_url(url: str, name: str) -> str:
    """Accept only http://127.0.0.1[:port] origins with no credentials or path."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "http":
        raise ValueError(f"{name} must use http to loopback")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_BACKEND_HOSTS:
        raise ValueError(f"{name} must point at 127.0.0.1")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{name} must not contain credentials")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError(f"{name} must be an origin only")
    if parsed.port is None:
        return "http://127.0.0.1"
    return f"http://127.0.0.1:{parsed.port}"


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _env_int(name: str, default: int, low: int, high: int) -> int:
    raw = _env(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < low or value > high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    ollama_url: str
    qdrant_url: str
    default_model: str
    host: str
    port: int
    secure_cookies: bool
    secret_key_file: Path = Path("~/.config/ember/secret.key")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ember.db"


def load_settings() -> Settings:
    data_dir = Path(_env("EMBER_DATA_DIR", str(Path.home() / ".local/share/ember")))
    return Settings(
        data_dir=data_dir.expanduser().resolve(),
        ollama_url=require_loopback_url(_env("EMBER_OLLAMA_URL", "http://127.0.0.1:11434"), "EMBER_OLLAMA_URL"),
        qdrant_url=require_loopback_url(_env("EMBER_QDRANT_URL", "http://127.0.0.1:6333"), "EMBER_QDRANT_URL"),
        default_model=_env("EMBER_DEFAULT_MODEL", DEFAULT_MODEL),
        host=_env("EMBER_HOST", "127.0.0.1"),
        port=_env_int("EMBER_PORT", DEFAULT_PORT, 1024, 65535),
        secure_cookies=_env("EMBER_SECURE_COOKIES", "1") == "1",
        secret_key_file=Path(_env("EMBER_SECRET_KEY_FILE", str(Path.home() / ".config/ember/secret.key")))
        .expanduser()
        .resolve(),
    )
