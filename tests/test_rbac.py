"""Role-based access control matrix tests."""

from __future__ import annotations

from tests.helpers import auth_headers, create_mock_router

NEW_NEIGHBOR = {"address": "203.0.113.50", "remote_as": 65050}
NEW_ROUTER = {"name": "rbac-router", "host": "192.0.2.20", "driver": "mock"}
NEW_RULE = {"number": 10, "action": "permit"}
ROUTE_MAP_BASE = "/api/v1/routers/{router_id}/route-maps"


async def test_unauthenticated_requests_are_rejected(client) -> None:
    response = await client.get("/api/v1/routers")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


async def test_viewer_is_read_only(client, admin_token, viewer_token) -> None:
    device = await create_mock_router(client, admin_token)
    router_id = device["id"]
    headers = auth_headers(viewer_token)

    assert (await client.get("/api/v1/routers", headers=headers)).status_code == 200
    assert (
        await client.get(f"/api/v1/routers/{router_id}/bgp", headers=headers)
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/routers/{router_id}/bgp/status", headers=headers)
    ).status_code == 200
    assert (
        await client.get(ROUTE_MAP_BASE.format(router_id=router_id), headers=headers)
    ).status_code == 200
    assert (
        await client.get(f"{ROUTE_MAP_BASE.format(router_id=router_id)}/BGP-IN", headers=headers)
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/routers/{router_id}/test", headers=headers)
    ).status_code == 200

    forbidden_requests = [
        await client.post(
            f"/api/v1/routers/{router_id}/bgp/neighbors",
            json=NEW_NEIGHBOR,
            headers=headers,
        ),
        await client.put(
            f"/api/v1/routers/{router_id}/bgp/global",
            json={"system_as": 64512, "router_id": None, "log_neighbor_changes": False},
            headers=headers,
        ),
        await client.post(
            ROUTE_MAP_BASE.format(router_id=router_id),
            json={"name": "VIEWER-MAP"},
            headers=headers,
        ),
        await client.put(
            f"{ROUTE_MAP_BASE.format(router_id=router_id)}/BGP-IN",
            json={"description": "x"},
            headers=headers,
        ),
        await client.delete(
            f"{ROUTE_MAP_BASE.format(router_id=router_id)}/LOCAL-PREF",
            headers=headers,
        ),
        await client.post(
            f"{ROUTE_MAP_BASE.format(router_id=router_id)}/LOCAL-PREF/rules",
            json=NEW_RULE,
            headers=headers,
        ),
        await client.put(
            f"{ROUTE_MAP_BASE.format(router_id=router_id)}/LOCAL-PREF/rules/10",
            json=NEW_RULE,
            headers=headers,
        ),
        await client.delete(
            f"{ROUTE_MAP_BASE.format(router_id=router_id)}/LOCAL-PREF/rules/10",
            headers=headers,
        ),
        await client.post("/api/v1/routers", json=NEW_ROUTER, headers=headers),
        await client.get("/api/v1/users", headers=headers),
        await client.get("/api/v1/audit", headers=headers),
        await client.delete(f"/api/v1/routers/{router_id}/bgp", headers=headers),
    ]
    for response in forbidden_requests:
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "forbidden"


async def test_operator_can_manage_bgp_but_not_admin_resources(
    client, admin_token, operator_token
) -> None:
    device = await create_mock_router(client, admin_token)
    router_id = device["id"]
    headers = auth_headers(operator_token)

    created = await client.post(
        f"/api/v1/routers/{router_id}/bgp/neighbors",
        json=NEW_NEIGHBOR,
        headers=headers,
    )
    assert created.status_code == 200, created.text

    global_update = await client.put(
        f"/api/v1/routers/{router_id}/bgp/global",
        json={"system_as": 64600, "router_id": "10.255.0.9", "log_neighbor_changes": True},
        headers=headers,
    )
    assert global_update.status_code == 200, global_update.text

    route_map_base = ROUTE_MAP_BASE.format(router_id=router_id)
    route_map = await client.post(route_map_base, json={"name": "OPERATOR-MAP"}, headers=headers)
    assert route_map.status_code == 201, route_map.text
    rule = await client.post(f"{route_map_base}/OPERATOR-MAP/rules", json=NEW_RULE, headers=headers)
    assert rule.status_code == 200, rule.text
    rule_delete = await client.delete(f"{route_map_base}/OPERATOR-MAP/rules/10", headers=headers)
    assert rule_delete.status_code == 200, rule_delete.text
    map_delete = await client.delete(f"{route_map_base}/OPERATOR-MAP", headers=headers)
    assert map_delete.status_code == 204, map_delete.text

    for response in [
        await client.post("/api/v1/routers", json=NEW_ROUTER, headers=headers),
        await client.get("/api/v1/users", headers=headers),
        await client.get("/api/v1/audit", headers=headers),
        await client.delete(f"/api/v1/routers/{router_id}/bgp", headers=headers),
    ]:
        assert response.status_code == 403, response.text


async def test_admin_can_manage_everything(client, admin_token) -> None:
    headers = auth_headers(admin_token)
    device = await create_mock_router(client, admin_token)
    router_id = device["id"]

    assert (await client.get("/api/v1/users", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/audit", headers=headers)).status_code == 200
    deleted = await client.delete(f"/api/v1/routers/{router_id}/bgp", headers=headers)
    assert deleted.status_code == 204
