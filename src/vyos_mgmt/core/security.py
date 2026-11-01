"""Password hashing and JWT primitives.

Passwords use Argon2id (via argon2-cffi).  Access and refresh tokens are both
JWTs signed with HS256.  Refresh tokens additionally carry a ``jti`` that is
recorded (hashed) in the database so they can be revoked and rotated.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

from vyos_mgmt.config import Settings, get_settings

# Argon2id with RFC 9106 "second recommended" parameters (64 MiB, t=3).
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "vyos-mgmt"

TokenType = Literal["access", "refresh"]


class TokenError(Exception):
    """Raised when a JWT is missing, malformed, expired or revoked."""


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_at: datetime
    jti: str

    @property
    def expires_in(self) -> int:
        return max(0, int((self.expires_at - datetime.now(UTC)).total_seconds()))


@dataclass(frozen=True)
class RefreshClaims:
    user_id: uuid.UUID
    jti: str
    expires_at: datetime
    remember_me: bool


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _encode(payload: dict[str, Any], settings: Settings) -> str:
    return jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def _base_payload(subject: str, token_type: TokenType, ttl: timedelta, settings: Settings) -> dict:
    now = _now()
    return {
        "sub": subject,
        "type": token_type,
        "jti": secrets.token_urlsafe(32),
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }


def create_access_token(user_id: uuid.UUID, settings: Settings | None = None) -> IssuedToken:
    settings = settings or get_settings()
    ttl = timedelta(seconds=settings.access_token_ttl_seconds)
    payload = _base_payload(str(user_id), "access", ttl, settings)
    token = _encode(payload, settings)
    return IssuedToken(
        token=token,
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        jti=payload["jti"],
    )


def create_refresh_token(
    user_id: uuid.UUID,
    *,
    remember_me: bool,
    settings: Settings | None = None,
    ttl_seconds: int | None = None,
) -> IssuedToken:
    settings = settings or get_settings()
    ttl = timedelta(seconds=ttl_seconds or settings.refresh_token_ttl_seconds)
    payload = _base_payload(str(user_id), "refresh", ttl, settings)
    payload["remember"] = remember_me
    token = _encode(payload, settings)
    return IssuedToken(
        token=token,
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        jti=payload["jti"],
    )


def _decode(token: str, expected_type: TokenType, settings: Settings) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={
                "require": ["exp", "iat", "sub", "iss", "aud", "jti", "type"],
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except jwt.PyJWTError as exc:  # includes ExpiredSignatureError
        raise TokenError("Invalid or expired token") from exc

    if payload.get("type") != expected_type:
        raise TokenError("Unexpected token type")
    return payload


def decode_access_token(token: str, settings: Settings | None = None) -> tuple[uuid.UUID, dict]:
    settings = settings or get_settings()
    payload = _decode(token, "access", settings)
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (ValueError, KeyError) as exc:
        raise TokenError("Invalid subject") from exc
    return user_id, payload


def decode_refresh_token(token: str, settings: Settings | None = None) -> RefreshClaims:
    settings = settings or get_settings()
    payload = _decode(token, "refresh", settings)
    try:
        user_id = uuid.UUID(str(payload["sub"]))
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
    except (ValueError, KeyError) as exc:
        raise TokenError("Invalid refresh token claims") from exc
    return RefreshClaims(
        user_id=user_id,
        jti=str(payload["jti"]),
        expires_at=expires_at,
        remember_me=bool(payload.get("remember", False)),
    )
