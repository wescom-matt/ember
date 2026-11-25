"""Encrypted credential storage and SSH key generation.

Secrets are encrypted with Fernet (AES-128-CBC + HMAC-SHA256, from the
`cryptography` library). The encryption key lives in a 0600 file outside the
database (~/.config/ember/secret.key), so a copied database alone reveals nothing.
Secrets are never returned by the API, logged, or sent to the model.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

MAX_SECRET_CHARS = 16_000


class VaultError(Exception):
    """Credential could not be stored or read. Message is safe to show."""


def _load_or_create_key(path: Path) -> bytes:
    if path.exists():
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            raise VaultError(f"{path} must be mode 600 (it is {oct(mode)})")
        data = path.read_bytes().strip()
        if len(data) != 44:
            raise VaultError("secret key file is damaged")
        return data
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = Fernet.generate_key()
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(key + b"\n")
    return key


class Vault:
    def __init__(self, key_file: Path) -> None:
        self._fernet = Fernet(_load_or_create_key(key_file))

    def encrypt(self, secret: str) -> str:
        if not secret or len(secret) > MAX_SECRET_CHARS:
            raise VaultError("secret is empty or too long")
        return self._fernet.encrypt(secret.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as exc:
            raise VaultError("stored credential cannot be decrypted (wrong or replaced key file?)") from exc


def generate_ssh_key(comment: str) -> tuple[str, str]:
    """Return (private key in OpenSSH format, public key line). Caller encrypts the private key."""
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()
    ).decode("ascii")
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    safe_comment = "".join(ch for ch in comment if ch.isalnum() or ch in "-_.@")[:60]
    return private, f"{public.decode('ascii')} {safe_comment}".strip()
