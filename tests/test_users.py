"""Integration tests for user administration and last-admin protection."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from tests.helpers import CSRF_HEADERS, auth_headers, login

NEW_USER = {
    "username": "NOC.User",
    "email": "noc@example.com",
    "password": "Noc-Password-123!",
    "role": "operator",
}
SECOND_ADMIN = {
    "username": "second-admin",
    "email": None,
    "password": "Second-Admin-Password-123!",
    "role": "admin",
}


async def test_user_crud_and_username_normalisation(client, admin_token) -> None:
    headers = auth_headers(admin_token)

    created = await client.post("/api/v1/users", headers=headers, json=NEW_USER)
    assert created.status_code == 201, created.text
    user = created.json()
    assert user["username"] == "noc.user"
    assert user["email"] == "noc@example.com"
    assert user["role"] == "operator"
    assert user["is_active"] is True

    listed = await client.get("/api/v1/users", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 2

    duplicate = await client.post(
        "/api/v1/users",
        headers=headers,
        json={**NEW_USER, "username": "NOC.USER"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "user_exists"

    updated = await client.patch(
        f"/api/v1/users/{user['id']}",
        headers=headers,
        json={"email": "changed@example.com", "role": "viewer", "is_active": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["email"] == "changed@example.com"
    assert updated.json()["role"] == "viewer"
    assert updated.json()["is_active"] is False

    deleted = await client.delete(f"/api/v1/users/{user['id']}", headers=headers)
    assert deleted.status_code == 204
    remaining = await client.get("/api/v1/users", headers=headers)
    assert remaining.json()["total"] == 1


async def test_username_validation(client, admin_token) -> None:
    headers = auth_headers(admin_token)
    for username in ("a", "has space", "-leading", "UPPER!"):
        response = await client.post(
            "/api/v1/users",
            headers=headers,
            json={**NEW_USER, "username": username},
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation_error"


async def test_last_admin_is_protected(client, admin_token, admin_user) -> None:
    headers = auth_headers(admin_token)

    demote = await client.patch(
        f"/api/v1/users/{admin_user.id}", headers=headers, json={"role": "viewer"}
    )
    assert demote.status_code == 409
    assert demote.json()["error"]["code"] == "last_admin"

    deactivate = await client.patch(
        f"/api/v1/users/{admin_user.id}", headers=headers, json={"is_active": False}
    )
    assert deactivate.status_code == 409
    assert deactivate.json()["error"]["code"] == "last_admin"

    self_delete = await client.delete(f"/api/v1/users/{admin_user.id}", headers=headers)
    assert self_delete.status_code == 409
    assert self_delete.json()["error"]["code"] == "cannot_delete_self"

    second = await client.post("/api/v1/users", headers=headers, json=SECOND_ADMIN)
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]

    demoted = await client.patch(
        f"/api/v1/users/{second_id}", headers=headers, json={"role": "operator"}
    )
    assert demoted.status_code == 200

    still_last = await client.patch(
        f"/api/v1/users/{admin_user.id}", headers=headers, json={"role": "viewer"}
    )
    assert still_last.status_code == 409
    assert still_last.json()["error"]["code"] == "last_admin"


async def test_validation_errors_do_not_echo_passwords(client, admin_token) -> None:
    response = await client.post(
        "/api/v1/users",
        headers=auth_headers(admin_token),
        json={**NEW_USER, "password": "LEAKME" + "x" * 200},
    )
    assert response.status_code == 422
    assert "LEAKME" not in response.text
    details = response.json()["error"]["details"]
    password_error = next(item for item in details if item["loc"][-1] == "password")
    assert password_error["input"] == "[redacted]"
    assert "ctx" not in password_error


async def test_operator_cannot_manage_users(client, operator_token) -> None:
    headers = auth_headers(operator_token)
    assert (await client.get("/api/v1/users", headers=headers)).status_code == 403
    assert (await client.post("/api/v1/users", headers=headers, json=NEW_USER)).status_code == 403


async def test_password_reset_revokes_sessions(client, app, admin_token) -> None:
    headers = auth_headers(admin_token)
    created = await client.post("/api/v1/users", headers=headers, json=NEW_USER)
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as user_client:
        await login(user_client, "noc.user", NEW_USER["password"])

        reset = await client.patch(
            f"/api/v1/users/{user_id}",
            headers=headers,
            json={"password": "Reset-Password-456!"},
        )
        assert reset.status_code == 200, reset.text

        refresh = await user_client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
        assert refresh.status_code == 401

        old_login = await user_client.post(
            "/api/v1/auth/login",
            json={"username": "noc.user", "password": NEW_USER["password"]},
        )
        assert old_login.status_code == 401
        new_login = await user_client.post(
            "/api/v1/auth/login",
            json={"username": "noc.user", "password": "Reset-Password-456!"},
        )
        assert new_login.status_code == 200
