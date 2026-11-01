"""Symmetric encryption for device credentials stored at rest."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from vyos_mgmt.config import get_settings


class SecretDecryptionError(RuntimeError):
    """The stored ciphertext cannot be decrypted with the configured key."""


def _fernet(secret: str | None = None) -> Fernet:
    secret = secret or get_settings().secret_key.get_secret_value()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str, *, secret: str | None = None) -> str:
    return _fernet(secret).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str, *, secret: str | None = None) -> str:
    try:
        return _fernet(secret).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise SecretDecryptionError(
            "Stored credential could not be decrypted; was SECRET_KEY rotated?"
        ) from exc
