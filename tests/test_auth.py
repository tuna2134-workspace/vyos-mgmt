"""Integration tests for authentication, refresh rotation and CSRF."""

from __future__ import annotations

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from tests.helpers import (
    ADMIN_PASSWORD,
    CSRF_HEADERS,
    auth_headers,
    create_user,
    login,
)
from vyos_mgmt.db.models import UserRole

COOKIE_NAME = "vyos_mgmt_refresh"


def _set_cookie(response) -> str:
    return response.headers.get("set-cookie", "")


async def test_login_contract_and_cookie(client, admin_user) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "ADMIN",
            "password": ADMIN_PASSWORD,
            "remember_me": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "user"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert set(body["user"]) == {
        "id",
        "username",
        "email",
        "role",
        "is_active",
        "last_login_at",
        "created_at",
        "updated_at",
    }
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "admin"
    assert body["user"]["last_login_at"] is not None

    header = _set_cookie(response)
    assert COOKIE_NAME in header
    assert "HttpOnly" in header
    assert "Path=/api/v1/auth" in header
    assert "SameSite=lax" in header
    assert "Max-Age=604800" in header
    assert client.cookies.get(COOKIE_NAME)


async def test_remember_me_false_is_a_session_cookie(client, admin_user) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": ADMIN_PASSWORD,
            "remember_me": False,
        },
    )
    assert response.status_code == 200, response.text
    header = _set_cookie(response)
    assert COOKIE_NAME in header
    assert "max-age" not in header.lower()
    assert "expires" not in header.lower()


async def test_login_rejects_invalid_credentials(client, admin_user) -> None:
    unknown = await client.post(
        "/api/v1/auth/login",
        json={"username": "ghost", "password": "whatever-password"},
    )
    assert unknown.status_code == 401
    assert unknown.json()["error"]["code"] == "invalid_credentials"

    wrong = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "not-the-password"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "invalid_credentials"
    assert wrong.json()["error"]["request_id"]


async def test_login_rate_limited_per_ip_and_username(client, admin_user, settings) -> None:
    settings.login_rate_limit_attempts = 2
    for _ in range(2):
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        assert response.status_code == 401

    blocked = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1


async def test_inactive_user_cannot_login(client, app) -> None:
    await create_user("inactive", "Inactive-Password-123!", UserRole.OPERATOR, is_active=False)
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "inactive", "password": "Inactive-Password-123!"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_refresh_requires_csrf(client, admin_user) -> None:
    await login(client, "admin", ADMIN_PASSWORD)
    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


async def test_refresh_rotates_token_and_rejects_replay(client, app, admin_user) -> None:
    await login(client, "admin", ADMIN_PASSWORD)
    old_token = client.cookies.get(COOKIE_NAME)
    assert old_token

    rotated = await client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert rotated.status_code == 200, rotated.text
    new_token = client.cookies.get(COOKIE_NAME)
    assert new_token and new_token != old_token
    assert rotated.json()["token_type"] == "bearer"

    # Replaying the old token from another client is rejected.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as replayer:
        replayer.cookies.set(COOKIE_NAME, old_token, path="/api/v1/auth")
        replay = await replayer.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "invalid_refresh_token"

    # Replay detection revoked the whole token family, including the new token.
    async with AsyncClient(transport=transport, base_url="http://testserver") as victim:
        victim.cookies.set(COOKIE_NAME, new_token, path="/api/v1/auth")
        family = await victim.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert family.status_code == 401


async def test_invalid_refresh_clears_cookie(client, app, admin_user) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as bad:
        bad.cookies.set(COOKIE_NAME, "not-a-valid-jwt", path="/api/v1/auth")
        response = await bad.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"
    header = _set_cookie(response)
    assert COOKIE_NAME in header
    assert "Max-Age=0" in header or "max-age=0" in header


async def test_logout_clears_cookie_and_revokes_token(client, admin_user) -> None:
    await login(client, "admin", ADMIN_PASSWORD)
    token = client.cookies.get(COOKIE_NAME)
    assert token

    response = await client.post("/api/v1/auth/logout", headers=CSRF_HEADERS)
    assert response.status_code == 204
    header = _set_cookie(response)
    assert COOKIE_NAME in header
    assert "Max-Age=0" in header or "max-age=0" in header

    refresh = await client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert refresh.status_code == 401


async def test_logout_requires_csrf(client, admin_user) -> None:
    await login(client, "admin", ADMIN_PASSWORD)
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


async def test_me_requires_bearer(client, admin_token) -> None:
    unauthenticated = await client.get("/api/v1/auth/me")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "not_authenticated"
    assert unauthenticated.headers["WWW-Authenticate"] == "Bearer"

    malformed = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert malformed.status_code == 401

    response = await client.get("/api/v1/auth/me", headers=auth_headers(admin_token))
    assert response.status_code == 200
    assert response.json()["username"] == "admin"


async def test_change_password_revokes_refresh_tokens(client, app, admin_user) -> None:
    payload = await login(client, "admin", ADMIN_PASSWORD)
    access_token = payload["access_token"]
    old_refresh = client.cookies.get(COOKIE_NAME)

    wrong = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(access_token),
        json={"current_password": "wrong", "new_password": "Brand-New-Password-123!"},
    )
    assert wrong.status_code == 400
    assert wrong.json()["error"]["code"] == "invalid_password"

    changed = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(access_token),
        json={
            "current_password": ADMIN_PASSWORD,
            "new_password": "Brand-New-Password-123!",
        },
    )
    assert changed.status_code == 204

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as other:
        other.cookies.set(COOKIE_NAME, old_refresh, path="/api/v1/auth")
        refresh = await other.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert refresh.status_code == 401

    old_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert old_login.status_code == 401
    new_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "Brand-New-Password-123!"},
    )
    assert new_login.status_code == 200


async def test_bootstrap_admin_created_on_startup(settings) -> None:
    from vyos_mgmt.config import SecretStr
    from vyos_mgmt.db.base import Base
    from vyos_mgmt.db.session import build_engine
    from vyos_mgmt.main import create_app

    bootstrap_settings = settings.model_copy(
        update={
            "bootstrap_admin_username": "bootstrap",
            "bootstrap_admin_email": "bootstrap@example.com",
            "bootstrap_admin_password": SecretStr("Bootstrap-Password-123!"),
        }
    )
    engine = build_engine(bootstrap_settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())
    await engine.dispose()

    application = create_app(bootstrap_settings)
    transport = ASGITransport(app=application)
    async with (
        LifespanManager(application),
        AsyncClient(transport=transport, base_url="http://testserver") as http_client,
    ):
        response = await http_client.post(
            "/api/v1/auth/login",
            json={"username": "bootstrap", "password": "Bootstrap-Password-123!"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["user"]["role"] == "admin"
