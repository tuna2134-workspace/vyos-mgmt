"""Integration tests for router inventory and connection probing."""

from __future__ import annotations

from sqlalchemy import select

from tests.helpers import auth_headers, create_mock_router
from vyos_mgmt.core.crypto import decrypt_secret
from vyos_mgmt.db.models import Router
from vyos_mgmt.db.session import get_session_factory

ROUTER_FIELDS = {
    "id",
    "name",
    "host",
    "port",
    "protocol",
    "verify_tls",
    "driver",
    "description",
    "api_key_configured",
    "created_by_id",
    "created_at",
    "updated_at",
}


async def test_router_crud_with_mock_driver(client, admin_token) -> None:
    headers = auth_headers(admin_token)

    listed = await client.get("/api/v1/routers", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == {"items": [], "total": 0}

    device = await create_mock_router(client, admin_token, name="edge-tokyo")
    assert set(device) == ROUTER_FIELDS
    assert device["driver"] == "mock"
    assert device["api_key_configured"] is False
    assert device["created_by_id"] is not None

    fetched = await client.get(f"/api/v1/routers/{device['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "edge-tokyo"

    patched = await client.patch(
        f"/api/v1/routers/{device['id']}",
        headers=headers,
        json={"description": "Updated", "port": 8443, "name": "edge-osaka"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["description"] == "Updated"
    assert patched.json()["port"] == 8443
    assert patched.json()["name"] == "edge-osaka"

    deleted = await client.delete(f"/api/v1/routers/{device['id']}", headers=headers)
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/routers/{device['id']}", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "router_not_found"


async def test_pyvyos_requires_api_key(client, admin_token) -> None:
    response = await client.post(
        "/api/v1/routers",
        headers=auth_headers(admin_token),
        json={"name": "real", "host": "192.0.2.1", "driver": "pyvyos"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "api_key_required"


async def test_api_key_is_encrypted_and_never_returned(client, admin_token, settings) -> None:
    headers = auth_headers(admin_token)
    plaintext = "super-secret-api-key"
    response = await client.post(
        "/api/v1/routers",
        headers=headers,
        json={
            "name": "secure-router",
            "host": "192.0.2.30",
            "driver": "pyvyos",
            "api_key": plaintext,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["api_key_configured"] is True
    assert plaintext not in response.text
    assert "api_key" not in body
    assert "api_key_encrypted" not in body

    factory = get_session_factory()
    async with factory() as session:
        stored = await session.scalar(select(Router).where(Router.id == body["id"]))
        assert stored is not None
        assert stored.api_key_encrypted
        assert stored.api_key_encrypted != plaintext
        assert (
            decrypt_secret(
                stored.api_key_encrypted,
                secret=settings.secret_key.get_secret_value(),
            )
            == plaintext
        )

    # ``api_key: ""`` clears the stored credential, as per the contract.
    cleared = await client.patch(
        f"/api/v1/routers/{body['id']}", headers=headers, json={"api_key": ""}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["api_key_configured"] is False

    # A keyless router may not be switched to the pyvyos driver.
    switched = await client.patch(
        f"/api/v1/routers/{body['id']}", headers=headers, json={"driver": "pyvyos"}
    )
    assert switched.status_code == 400
    assert switched.json()["error"]["code"] == "api_key_required"


async def test_duplicate_router_name_is_case_insensitive(client, admin_token) -> None:
    headers = auth_headers(admin_token)
    await create_mock_router(client, admin_token, name="Edge-A")
    duplicate = await client.post(
        "/api/v1/routers",
        headers=headers,
        json={"name": "edge-a", "host": "192.0.2.40", "driver": "mock"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "router_exists"


async def test_router_validation_errors(client, admin_token) -> None:
    headers = auth_headers(admin_token)
    for payload in [
        {"name": "bad", "host": "https://192.0.2.1", "driver": "mock"},
        {"name": "bad", "host": "192.0.2.1", "port": 0, "driver": "mock"},
        {"name": "", "host": "192.0.2.1", "driver": "mock"},
        {"name": "bad", "host": "192.0.2.1", "driver": "unknown"},
    ]:
        response = await client.post("/api/v1/routers", headers=headers, json=payload)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation_error"


async def test_test_endpoint_reports_unreachable_but_returns_200(client, admin_token) -> None:
    headers = auth_headers(admin_token)
    created = await client.post(
        "/api/v1/routers",
        headers=headers,
        json={
            "name": "unreachable",
            "host": "127.0.0.1",
            "port": 1,
            "protocol": "http",
            "verify_tls": False,
            "driver": "pyvyos",
            "api_key": "key",
        },
    )
    assert created.status_code == 201, created.text
    router_id = created.json()["id"]

    probe = await client.post(f"/api/v1/routers/{router_id}/test", headers=headers)
    assert probe.status_code == 200
    body = probe.json()
    assert body["reachable"] is False
    assert body["error"]
    assert body["driver"] == "pyvyos"

    system = await client.get(f"/api/v1/routers/{router_id}/system", headers=headers)
    assert system.status_code == 502
    assert system.json()["error"]["code"] in {
        "router_unreachable",
        "router_command_failed",
    }


async def test_system_endpoint_for_mock_router(client, admin_token) -> None:
    device = await create_mock_router(client, admin_token)
    response = await client.get(
        f"/api/v1/routers/{device['id']}/system",
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is True
    assert body["driver"] == "mock"
    assert body["hostname"] == "edge-mock"
    assert body["version"]
