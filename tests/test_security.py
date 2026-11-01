"""Unit tests for password hashing and JWT handling."""

from __future__ import annotations

import uuid

import pytest

from vyos_mgmt.config import Settings
from vyos_mgmt.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)

SECRET = "unit-test-secret-key-0123456789abcdef"


def make_settings(secret: str = SECRET) -> Settings:
    return Settings(environment="test", secret_key=secret)


def test_argon2id_hash_and_verify() -> None:
    password_hash = hash_password("correct horse battery staple")
    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, "correct horse battery staple")
    assert not verify_password(password_hash, "wrong password")
    assert not verify_password("not-a-valid-hash", "anything")
    assert not password_needs_rehash(password_hash)


def test_hash_is_salted() -> None:
    first = hash_password("same-password")
    second = hash_password("same-password")
    assert first != second


def test_access_token_round_trip() -> None:
    settings = make_settings()
    user_id = uuid.uuid4()
    issued = create_access_token(user_id, settings)
    decoded_id, payload = decode_access_token(issued.token, settings)
    assert decoded_id == user_id
    assert payload["type"] == "access"
    assert payload["iss"] == settings.jwt_issuer
    assert payload["aud"] == settings.jwt_audience
    assert issued.expires_in > 0


def test_refresh_token_round_trip() -> None:
    settings = make_settings()
    user_id = uuid.uuid4()
    issued = create_refresh_token(user_id, remember_me=True, settings=settings)
    claims = decode_refresh_token(issued.token, settings)
    assert claims.user_id == user_id
    assert claims.jti == issued.jti
    assert claims.remember_me is True
    assert hash_token(issued.token) != issued.token


def test_token_types_are_not_interchangeable() -> None:
    settings = make_settings()
    user_id = uuid.uuid4()
    access = create_access_token(user_id, settings)
    refresh = create_refresh_token(user_id, remember_me=False, settings=settings)

    with pytest.raises(TokenError):
        decode_refresh_token(access.token, settings)
    with pytest.raises(TokenError):
        decode_access_token(refresh.token, settings)


def test_expired_refresh_token_rejected() -> None:
    settings = make_settings()
    expired = create_refresh_token(
        uuid.uuid4(), remember_me=False, settings=settings, ttl_seconds=-1
    )
    with pytest.raises(TokenError):
        decode_refresh_token(expired.token, settings)


def test_token_signed_with_other_secret_rejected() -> None:
    issuer_settings = make_settings()
    verifier_settings = make_settings("another-secret-key-0123456789abcdef")
    issued = create_access_token(uuid.uuid4(), issuer_settings)
    with pytest.raises(TokenError):
        decode_access_token(issued.token, verifier_settings)


def test_garbage_token_rejected() -> None:
    with pytest.raises(TokenError):
        decode_access_token("not-a-jwt", make_settings())
