"""Shared helpers for the integration tests."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from vyos_mgmt.core.security import hash_password
from vyos_mgmt.db.models import User, UserRole
from vyos_mgmt.db.session import get_session_factory

ADMIN_PASSWORD = "Admin-Password-123!"
OPERATOR_PASSWORD = "Operator-Password-123!"
VIEWER_PASSWORD = "Viewer-Password-123!"
CSRF_HEADERS = {"X-Requested-With": "vyos-mgmt"}


async def create_user(
    username: str,
    password: str,
    role: UserRole = UserRole.ADMIN,
    *,
    email: str | None = None,
    is_active: bool = True,
) -> User:
    factory = get_session_factory()
    async with factory() as session:
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def login(
    client: AsyncClient,
    username: str,
    password: str,
    *,
    remember_me: bool = True,
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password, "remember_me": remember_me},
    )
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_mock_router(
    client: AsyncClient, token: str, name: str = "edge-mock", **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "host": "192.0.2.10",
        "driver": "mock",
        "description": "Test router",
    }
    payload.update(overrides)
    response = await client.post("/api/v1/routers", json=payload, headers=auth_headers(token))
    assert response.status_code == 201, response.text
    return response.json()
