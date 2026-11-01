"""Integration tests for the audit trail."""

from __future__ import annotations

from tests.helpers import auth_headers, create_mock_router

AUDIT_FIELDS = {
    "id",
    "actor_username",
    "router_id",
    "router_name",
    "action",
    "resource_type",
    "resource_id",
    "status",
    "details",
    "request_id",
    "created_at",
}


async def _seed_audit_events(client, token: str) -> str:
    router = await create_mock_router(client, token, name="audit-router")
    router_id = router["id"]
    headers = auth_headers(token)
    created = await client.post(
        f"/api/v1/routers/{router_id}/bgp/neighbors",
        headers=headers,
        json={
            "address": "203.0.113.77",
            "remote_as": 65300,
            "description": "Audited peer",
            "password": "audit-secret-password",
        },
    )
    assert created.status_code == 200, created.text
    updated = await client.put(
        f"/api/v1/routers/{router_id}/bgp/global",
        headers=headers,
        json={"system_as": 64601, "router_id": None, "log_neighbor_changes": False},
    )
    assert updated.status_code == 200, updated.text
    return router_id


async def test_audit_records_mutations_with_redaction(client, admin_token) -> None:
    await _seed_audit_events(client, admin_token)
    response = await client.get(
        "/api/v1/audit", headers=auth_headers(admin_token), params={"limit": 50}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    for item in body["items"]:
        assert set(item) == AUDIT_FIELDS
        assert item["actor_username"] == "admin"
        assert item["status"] == "success"
        assert item["request_id"]
        assert item["router_name"] == "audit-router"

    actions = {item["action"] for item in body["items"]}
    assert actions == {
        "router.create",
        "bgp.neighbor.create",
        "bgp.global.update",
    }
    neighbor_event = next(item for item in body["items"] if item["action"] == "bgp.neighbor.create")
    assert neighbor_event["resource_type"] == "bgp_neighbor"
    assert neighbor_event["resource_id"] == "203.0.113.77"
    assert neighbor_event["details"]["password_set"] is True
    assert "audit-secret-password" not in response.text
    assert "password" not in neighbor_event["details"]


async def test_audit_pagination(client, admin_token) -> None:
    await _seed_audit_events(client, admin_token)
    headers = auth_headers(admin_token)

    first_page = await client.get(
        "/api/v1/audit", headers=headers, params={"limit": 2, "offset": 0}
    )
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 3
    assert len(first_page.json()["items"]) == 2

    second_page = await client.get(
        "/api/v1/audit", headers=headers, params={"limit": 2, "offset": 2}
    )
    assert len(second_page.json()["items"]) == 1

    ids = {item["id"] for item in first_page.json()["items"]}
    assert ids.isdisjoint({item["id"] for item in second_page.json()["items"]})


async def test_audit_limit_validation(client, admin_token) -> None:
    headers = auth_headers(admin_token)
    for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        response = await client.get("/api/v1/audit", headers=headers, params=params)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation_error"


async def test_audit_requires_admin(client, operator_token, viewer_token) -> None:
    for token in (operator_token, viewer_token):
        response = await client.get("/api/v1/audit", headers=auth_headers(token))
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"


async def test_audit_keeps_router_name_after_router_delete(client, admin_token) -> None:
    headers = auth_headers(admin_token)
    router = await create_mock_router(client, admin_token, name="deleted-router")
    deleted = await client.delete(f"/api/v1/routers/{router['id']}", headers=headers)
    assert deleted.status_code == 204

    response = await client.get("/api/v1/audit", headers=headers)
    assert response.status_code == 200
    delete_event = next(
        item for item in response.json()["items"] if item["action"] == "router.delete"
    )
    assert delete_event["router_name"] == "deleted-router"
    assert delete_event["router_id"] is None
