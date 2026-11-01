"""Authentication endpoints: login, refresh-token rotation, logout."""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vyos_mgmt.api.deps import (
    ClientIP,
    CsrfProtected,
    CurrentUser,
    SessionDep,
    SettingsDep,
)
from vyos_mgmt.config import Settings
from vyos_mgmt.core.errors import AppError, error_response
from vyos_mgmt.core.rate_limit import rate_limiter
from vyos_mgmt.core.security import (
    IssuedToken,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from vyos_mgmt.db.models import RefreshToken, User
from vyos_mgmt.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    TokenResponse,
    UserRead,
)
from vyos_mgmt.services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])

# Verified against when the username does not exist so that response timing does
# not reveal whether an account is valid.
_DUMMY_PASSWORD_HASH = hash_password("vyos-mgmt-timing-equalisation-dummy")


def _invalid_credentials() -> AppError:
    return AppError(401, "invalid_credentials", "Invalid username or password")


_REFRESH_ERROR_MESSAGE = "Refresh token is invalid or expired"


def _invalid_refresh_response(request: Request, settings: Settings) -> Response:
    """Build a 401 that also clears the now-useless refresh cookie.

    Returning a response (rather than raising) is required because exception
    handlers build a fresh response and would drop the ``Set-Cookie`` header.
    """

    response = error_response(
        request,
        status_code=401,
        code="invalid_refresh_token",
        message=_REFRESH_ERROR_MESSAGE,
    )
    _clear_refresh_cookie(response, settings)
    return response


def _set_refresh_cookie(
    response: Response, token: str, *, remember_me: bool, settings: Settings
) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=settings.refresh_token_ttl_seconds if remember_me else None,
        path=settings.refresh_cookie_path,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
    )


def _issue_tokens(
    session: AsyncSession,
    user: User,
    *,
    remember_me: bool,
    settings: Settings,
    request: Request,
    client_ip: str,
) -> tuple[TokenResponse, IssuedToken]:
    access = create_access_token(user.id, settings)
    refresh = create_refresh_token(user.id, remember_me=remember_me, settings=settings)
    session.add(
        RefreshToken(
            user_id=user.id,
            jti=refresh.jti,
            token_hash=hash_token(refresh.token),
            expires_at=refresh.expires_at,
            user_agent=(request.headers.get("user-agent") or "")[:255] or None,
            ip_address=client_ip[:64] if client_ip else None,
        )
    )
    payload = TokenResponse(
        access_token=access.token,
        token_type="bearer",
        expires_in=settings.access_token_ttl_seconds,
        user=UserRead.model_validate(user),
    )
    return payload, refresh


async def _revoke_all_refresh_tokens(
    session: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None
) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now or datetime.now(UTC))
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    client_ip: ClientIP,
) -> TokenResponse:
    rate_key = f"login:{client_ip}:{payload.username}"
    allowed, retry_after = await rate_limiter.hit(
        rate_key,
        limit=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
    )
    if not allowed:
        raise AppError(
            429,
            "rate_limited",
            "Too many login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    user = await session.scalar(select(User).where(User.username == payload.username))
    if user is None:
        # Equalise timing with the valid-user path; result is discarded.
        verify_password(_DUMMY_PASSWORD_HASH, payload.password)
        raise _invalid_credentials()

    if not verify_password(user.password_hash, payload.password):
        raise _invalid_credentials()
    if not user.is_active:
        raise _invalid_credentials()

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    user.last_login_at = datetime.now(UTC)
    await rate_limiter.reset(rate_key)

    token_response, refresh = _issue_tokens(
        session,
        user,
        remember_me=payload.remember_me,
        settings=settings,
        request=request,
        client_ip=client_ip,
    )
    _set_refresh_cookie(response, refresh.token, remember_me=payload.remember_me, settings=settings)
    return token_response


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    _csrf: CsrfProtected,
    session: SessionDep,
    settings: SettingsDep,
    client_ip: ClientIP,
) -> TokenResponse | Response:
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if not raw_token:
        return _invalid_refresh_response(request, settings)

    try:
        claims = decode_refresh_token(raw_token, settings)
    except TokenError:
        return _invalid_refresh_response(request, settings)

    record = await session.scalar(select(RefreshToken).where(RefreshToken.jti == claims.jti))
    now = datetime.now(UTC)
    if (
        record is None
        or record.user_id != claims.user_id
        or not hmac.compare_digest(record.token_hash, hash_token(raw_token))
        or record.expires_at <= now
    ):
        return _invalid_refresh_response(request, settings)

    if record.revoked_at is not None:
        # A rotated token was replayed: assume theft and revoke the family.
        # Commit explicitly so the revocation survives the 401 response.
        await _revoke_all_refresh_tokens(session, record.user_id, now=now)
        await session.commit()
        return _invalid_refresh_response(request, settings)

    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        return _invalid_refresh_response(request, settings)

    record.revoked_at = now
    token_response, new_refresh = _issue_tokens(
        session,
        user,
        remember_me=claims.remember_me,
        settings=settings,
        request=request,
        client_ip=client_ip,
    )
    _set_refresh_cookie(
        response, new_refresh.token, remember_me=claims.remember_me, settings=settings
    )
    return token_response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    _csrf: CsrfProtected,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if raw_token:
        try:
            claims = decode_refresh_token(raw_token, settings)
        except TokenError:
            claims = None
        if claims is not None:
            record = await session.scalar(
                select(RefreshToken).where(RefreshToken.jti == claims.jti)
            )
            if record is not None and record.revoked_at is None:
                record.revoked_at = datetime.now(UTC)

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response, settings)
    return response


@router.get("/me", response_model=UserRead)
async def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    current_user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    if not verify_password(current_user.password_hash, payload.current_password):
        raise AppError(400, "invalid_password", "The current password is incorrect")
    if payload.current_password == payload.new_password:
        raise AppError(
            400, "password_unchanged", "The new password must differ from the current one"
        )

    current_user.password_hash = hash_password(payload.new_password)
    await _revoke_all_refresh_tokens(session, current_user.id)
    await record_audit(
        session,
        action="user.change_password",
        resource_type="user",
        actor=current_user,
        request=request,
        resource_id=str(current_user.id),
    )

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response, settings)
    return response


__all__ = ["router"]
