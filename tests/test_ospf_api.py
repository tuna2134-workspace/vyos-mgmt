"""Integration tests for the OSPF API."""

from __future__ import annotations

import uuid

from tests.helpers import auth_headers, create_mock_router

CONFIG_FIELDS = {
    "router",
    "version",
    "configured",
    "global",
    "areas",
    "interfaces",
    "redistributions",
    "supported_network_types",
    "supported_redistribute_sources",
}
GLOBAL_FIELDS = {
    "router_id",
    "log_adjacency_changes",
    "auto_cost_reference_bandwidth",
    "default_information_originate",
    "default_information_always",
    "distance_global",
}
AREA_FIELDS = {"area_id", "area_type", "no_summary", "interface_count"}
INTERFACE_FIELDS = {
    "name",
    "area_id",
    "network_type",
    "cost",
    "hello_interval",
    "dead_interval",
    "priority",
    "passive",
    "bfd",
    "mtu_ignore",
    "retransmit_interval",
    "transmit_delay",
}
REDISTRIBUTE_FIELDS = {"source", "metric", "metric_type", "route_map"}
STATUS_FIELDS = {
    "configured",
    "version",
    "router_id",
    "neighbors",
    "total_neighbors",
    "full_neighbors",
    "collected_at",
    "error",
}
NEIGHBOR_FIELDS = {
    "neighbor_id",
    "priority",
    "state",
    "dead_time",
    "address",
    "interface",
    "established",
}


async def _router(client, token: str) -> str:
    device = await create_mock_router(client, token)
    return device["id"]


def _base(router_id: str) -> str:
    return f"/api/v1/routers/{router_id}/ospf"


GLOBAL_BODY = {
    "router_id": "10.255.0.9",
    "log_adjacency_changes": "normal",
    "auto_cost_reference_bandwidth": 2000,
    "default_information_originate": True,
    "default_information_always": False,
    "distance_global": 120,
}


async def test_get_config_matches_contract_for_both_versions(
    client, viewer_token, admin_token
) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(viewer_token)

    response = await client.get(f"{_base(router_id)}/v2", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == CONFIG_FIELDS
    assert body["version"] == "v2"
    assert body["configured"] is True
    assert body["router"]["id"] == router_id
    assert body["router"]["name"] == "edge-mock"
    assert set(body["global"]) == GLOBAL_FIELDS
    assert body["global"]["router_id"] == "10.255.0.1"
    assert body["global"]["log_adjacency_changes"] == "detail"
    assert body["global"]["default_information_originate"] is True
    assert body["global"]["default_information_always"] is False
    assert [area["area_id"] for area in body["areas"]] == ["0.0.0.0", "0.0.0.1"]
    for area in body["areas"]:
        assert set(area) == AREA_FIELDS
    assert body["areas"][1] == {
        "area_id": "0.0.0.1",
        "area_type": "stub",
        "no_summary": True,
        "interface_count": 1,
    }
    for interface in body["interfaces"]:
        assert set(interface) == INTERFACE_FIELDS
    eth0 = body["interfaces"][0]
    assert eth0["name"] == "eth0"
    assert eth0["area_id"] == "0.0.0.0"
    assert eth0["network_type"] == "point-to-point"
    assert eth0["cost"] == 10
    assert eth0["bfd"] is True
    assert eth0["retransmit_interval"] is None
    for redistribution in body["redistributions"]:
        assert set(redistribution) == REDISTRIBUTE_FIELDS
    assert body["redistributions"][0]["route_map"] == "OSPF-OUT"
    assert body["supported_network_types"] == [
        "broadcast",
        "non-broadcast",
        "point-to-multipoint",
        "point-to-point",
    ]
    assert body["supported_redistribute_sources"] == [
        "babel",
        "bgp",
        "connected",
        "isis",
        "kernel",
        "rip",
        "static",
    ]

    v3 = await client.get(f"{_base(router_id)}/v3", headers=headers)
    assert v3.status_code == 200, v3.text
    v3_body = v3.json()
    assert v3_body["version"] == "v3"
    assert v3_body["supported_network_types"] == ["broadcast", "point-to-point"]
    assert "ripng" in v3_body["supported_redistribute_sources"]
    assert v3_body["areas"][1]["area_type"] == "nssa"

    unknown = await client.get(f"{_base(router_id)}/v4", headers=headers)
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "version_not_found"

    missing_router = await client.get(f"/api/v1/routers/{uuid.uuid4()}/ospf/v2", headers=headers)
    assert missing_router.status_code == 404
    assert missing_router.json()["error"]["code"] == "router_not_found"


async def test_global_update_and_validation(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)

    updated = await client.put(f"{_base(router_id)}/v2/global", headers=headers, json=GLOBAL_BODY)
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["global"] == GLOBAL_BODY

    cleared = await client.put(
        f"{_base(router_id)}/v3/global",
        headers=headers,
        json={
            "router_id": None,
            "log_adjacency_changes": "none",
            "auto_cost_reference_bandwidth": None,
            "default_information_originate": False,
            "default_information_always": False,
            "distance_global": None,
        },
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["global"] == {
        "router_id": None,
        "log_adjacency_changes": "none",
        "auto_cost_reference_bandwidth": None,
        "default_information_originate": False,
        "default_information_always": False,
        "distance_global": None,
    }

    invalid = await client.put(
        f"{_base(router_id)}/v2/global",
        headers=headers,
        json={
            **GLOBAL_BODY,
            "default_information_originate": False,
            "default_information_always": True,
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"

    for bad in (
        {**GLOBAL_BODY, "router_id": "not-an-ip"},
        {**GLOBAL_BODY, "distance_global": 0},
        {**GLOBAL_BODY, "auto_cost_reference_bandwidth": 0},
        {**GLOBAL_BODY, "log_adjacency_changes": "verbose"},
    ):
        response = await client.put(f"{_base(router_id)}/v2/global", headers=headers, json=bad)
        assert response.status_code == 422, response.text


async def test_area_crud_conflicts_and_in_use(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"{_base(router_id)}/v2/areas"

    created = await client.post(
        base,
        headers=headers,
        json={"area_id": "10", "area_type": "stub", "no_summary": True},
    )
    assert created.status_code == 201, created.text
    areas = created.json()["areas"]
    area = next(item for item in areas if item["area_id"] == "0.0.0.10")
    assert area == {
        "area_id": "0.0.0.10",
        "area_type": "stub",
        "no_summary": True,
        "interface_count": 0,
    }

    duplicate = await client.post(base, headers=headers, json={"area_id": "0.0.0.10"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "ospf_area_exists"

    updated = await client.put(
        f"{base}/10", headers=headers, json={"area_type": "nssa", "no_summary": False}
    )
    assert updated.status_code == 200, updated.text
    area = next(item for item in updated.json()["areas"] if item["area_id"] == "0.0.0.10")
    assert area["area_type"] == "nssa"
    assert area["no_summary"] is False

    in_use = await client.delete(f"{base}/0.0.0.0", headers=headers)
    assert in_use.status_code == 409
    body = in_use.json()["error"]
    assert body["code"] == "ospf_area_in_use"
    assert body["details"]["used_by"] == ["eth0"]

    deleted = await client.delete(f"{base}/0.0.0.10", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert all(item["area_id"] != "0.0.0.10" for item in deleted.json()["areas"])

    missing = await client.put(f"{base}/0.0.0.99", headers=headers, json={"area_type": "normal"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ospf_area_not_found"
    assert (await client.delete(f"{base}/0.0.0.99", headers=headers)).status_code == 404

    invalid_path = await client.put(
        f"{base}/not-an-area", headers=headers, json={"area_type": "normal"}
    )
    assert invalid_path.status_code == 422
    assert invalid_path.json()["error"]["code"] == "validation_error"

    invalid_type = await client.post(
        base, headers=headers, json={"area_id": "0", "area_type": "backbone"}
    )
    assert invalid_type.status_code == 422, invalid_type.text


async def test_interface_crud_validation_and_preservation(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"{_base(router_id)}/v2/interfaces"

    body = {
        "name": "eth2",
        "area_id": "1",
        "network_type": "point-to-point",
        "cost": 10,
        "hello_interval": 10,
        "dead_interval": 40,
        "priority": 1,
        "passive": False,
        "bfd": True,
        "mtu_ignore": False,
        "retransmit_interval": None,
        "transmit_delay": None,
    }
    created = await client.post(base, headers=headers, json=body)
    assert created.status_code == 201, created.text
    interface = next(item for item in created.json()["interfaces"] if item["name"] == "eth2")
    assert interface["area_id"] == "0.0.0.1"
    assert interface["network_type"] == "point-to-point"
    assert interface["bfd"] is True

    duplicate = await client.post(base, headers=headers, json=body)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "ospf_interface_exists"

    missing_area = await client.post(
        base, headers=headers, json={**body, "name": "eth3", "area_id": "0.0.0.99"}
    )
    assert missing_area.status_code == 422
    assert missing_area.json()["error"]["code"] == "ospf_area_not_found"

    invalid_network = await client.post(
        base,
        headers=headers,
        json={**body, "name": "eth3", "network_type": "non-broadcast"},
    )
    assert invalid_network.status_code == 201, invalid_network.text

    updated = await client.put(
        f"{base}/eth2",
        headers=headers,
        json={**body, "network_type": "broadcast", "cost": 30, "passive": True},
    )
    assert updated.status_code == 200, updated.text
    interface = next(item for item in updated.json()["interfaces"] if item["name"] == "eth2")
    assert interface["network_type"] == "broadcast"
    assert interface["cost"] == 30
    assert interface["passive"] is True

    missing_update = await client.put(f"{base}/eth9", headers=headers, json=body)
    assert missing_update.status_code == 404
    assert missing_update.json()["error"]["code"] == "ospf_interface_not_found"

    bad_name = await client.post(base, headers=headers, json={**body, "name": "1eth0"})
    assert bad_name.status_code == 422, bad_name.text

    deleted = await client.delete(f"{base}/eth2", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert all(item["name"] != "eth2" for item in deleted.json()["interfaces"])
    assert (await client.delete(f"{base}/eth2", headers=headers)).status_code == 404


async def test_v3_rejects_ipv4_only_network_types(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"{_base(router_id)}/v3/interfaces"

    response = await client.post(
        base,
        headers=headers,
        json={"name": "eth2", "area_id": "0", "network_type": "non-broadcast"},
    )
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"][0]["loc"] == ["body", "network_type"]

    ok = await client.post(
        base,
        headers=headers,
        json={"name": "eth2", "area_id": "0", "network_type": "broadcast"},
    )
    assert ok.status_code == 201, ok.text


async def test_redistribute_crud_and_route_map_validation(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"{_base(router_id)}/v2/redistribute"

    body = {"source": "static", "metric": 30, "metric_type": 1, "route_map": "BGP-IN"}
    created = await client.post(base, headers=headers, json=body)
    assert created.status_code == 201, created.text
    item = next(entry for entry in created.json()["redistributions"] if entry["source"] == "static")
    assert item == {"source": "static", "metric": 30, "metric_type": 1, "route_map": "BGP-IN"}

    duplicate = await client.post(base, headers=headers, json={"source": "static"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "ospf_redistribute_exists"

    missing_map = await client.post(
        base, headers=headers, json={"source": "kernel", "route_map": "MISSING-MAP"}
    )
    assert missing_map.status_code == 422
    assert missing_map.json()["error"]["code"] == "route_map_not_found"

    invalid_source = await client.post(base, headers=headers, json={"source": "ripng"})
    assert invalid_source.status_code == 422, invalid_source.text

    updated = await client.put(
        f"{base}/static",
        headers=headers,
        json={"metric": None, "metric_type": 2, "route_map": "OSPF-OUT"},
    )
    assert updated.status_code == 200, updated.text
    item = next(entry for entry in updated.json()["redistributions"] if entry["source"] == "static")
    assert item == {
        "source": "static",
        "metric": None,
        "metric_type": 2,
        "route_map": "OSPF-OUT",
    }

    missing_update = await client.put(f"{base}/kernel", headers=headers, json={"metric": 1})
    assert missing_update.status_code == 404
    assert missing_update.json()["error"]["code"] == "ospf_redistribute_not_found"

    deleted = await client.delete(f"{base}/static", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert (await client.delete(f"{base}/static", headers=headers)).status_code == 404

    v3 = await client.post(
        f"{_base(router_id)}/v3/redistribute",
        headers=headers,
        json={"source": "ripng"},
    )
    assert v3.status_code == 201, v3.text


async def test_status_endpoints(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)

    v2 = await client.get(f"{_base(router_id)}/v2/status", headers=headers)
    assert v2.status_code == 200, v2.text
    body = v2.json()
    assert set(body) == STATUS_FIELDS
    assert body["configured"] is True
    assert body["version"] == "v2"
    assert body["router_id"] == "10.255.0.1"
    assert body["total_neighbors"] == 2
    assert body["full_neighbors"] == 2
    assert body["error"] is None
    for neighbor in body["neighbors"]:
        assert set(neighbor) == NEIGHBOR_FIELDS
    assert body["neighbors"][0]["state"] == "Full/DR"
    assert body["neighbors"][0]["established"] is True

    v3 = await client.get(f"{_base(router_id)}/v3/status", headers=headers)
    assert v3.status_code == 200, v3.text
    v3_body = v3.json()
    assert v3_body["total_neighbors"] == 2
    assert v3_body["full_neighbors"] == 1
    assert v3_body["neighbors"][1]["state"] == "2-Way/DROther"
    assert v3_body["neighbors"][1]["established"] is False


async def test_delete_process_requires_admin_and_is_idempotent(
    client, admin_token, operator_token
) -> None:
    router_id = await _router(client, admin_token)
    operator_headers = auth_headers(operator_token)
    admin_headers = auth_headers(admin_token)

    forbidden = await client.delete(f"{_base(router_id)}/v2", headers=operator_headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"

    deleted = await client.delete(f"{_base(router_id)}/v2", headers=admin_headers)
    assert deleted.status_code == 204
    config = await client.get(f"{_base(router_id)}/v2", headers=admin_headers)
    assert config.json()["configured"] is False
    status = await client.get(f"{_base(router_id)}/v2/status", headers=admin_headers)
    assert status.json()["configured"] is False
    assert status.json()["neighbors"] == []

    again = await client.delete(f"{_base(router_id)}/v2", headers=admin_headers)
    assert again.status_code == 204


async def test_rbac_matrix(client, admin_token, operator_token, viewer_token) -> None:
    router_id = await _router(client, admin_token)
    base = _base(router_id)
    viewer = auth_headers(viewer_token)
    operator = auth_headers(operator_token)

    for path in (f"{base}/v2", f"{base}/v3", f"{base}/v2/status"):
        assert (await client.get(path, headers=viewer)).status_code == 200

    body = {
        "router_id": "10.255.0.9",
        "log_adjacency_changes": "normal",
        "auto_cost_reference_bandwidth": 1000,
        "default_information_originate": False,
        "default_information_always": False,
        "distance_global": 110,
    }
    forbidden = [
        await client.put(f"{base}/v2/global", headers=viewer, json=body),
        await client.post(f"{base}/v2/areas", headers=viewer, json={"area_id": "5"}),
        await client.put(f"{base}/v2/areas/0.0.0.0", headers=viewer, json={"area_type": "normal"}),
        await client.delete(f"{base}/v2/areas/0.0.0.0", headers=viewer),
        await client.post(
            f"{base}/v2/interfaces",
            headers=viewer,
            json={"name": "eth5", "area_id": "0"},
        ),
        await client.put(f"{base}/v2/interfaces/eth0", headers=viewer, json={"area_id": "0"}),
        await client.delete(f"{base}/v2/interfaces/eth0", headers=viewer),
        await client.post(f"{base}/v2/redistribute", headers=viewer, json={"source": "static"}),
        await client.put(f"{base}/v2/redistribute/connected", headers=viewer, json={"metric": 1}),
        await client.delete(f"{base}/v2/redistribute/connected", headers=viewer),
        await client.delete(f"{base}/v2", headers=viewer),
    ]
    for response in forbidden:
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "forbidden"

    # Operator can mutate everything except deleting the whole process.
    assert (await client.put(f"{base}/v2/global", headers=operator, json=body)).status_code == 200
    assert (
        await client.post(f"{base}/v2/areas", headers=operator, json={"area_id": "5"})
    ).status_code == 201
    assert (
        await client.put(f"{base}/v2/areas/0.0.0.5", headers=operator, json={"area_type": "stub"})
    ).status_code == 200
    assert (await client.delete(f"{base}/v2/areas/0.0.0.5", headers=operator)).status_code == 200
    assert (
        await client.post(
            f"{base}/v2/interfaces",
            headers=operator,
            json={"name": "eth5", "area_id": "0"},
        )
    ).status_code == 201
    assert (
        await client.put(
            f"{base}/v2/interfaces/eth5", headers=operator, json={"area_id": "0", "cost": 5}
        )
    ).status_code == 200
    assert (await client.delete(f"{base}/v2/interfaces/eth5", headers=operator)).status_code == 200
    assert (
        await client.post(f"{base}/v2/redistribute", headers=operator, json={"source": "static"})
    ).status_code == 201
    assert (
        await client.put(f"{base}/v2/redistribute/static", headers=operator, json={"metric": 5})
    ).status_code == 200
    assert (
        await client.delete(f"{base}/v2/redistribute/static", headers=operator)
    ).status_code == 200
    assert (await client.delete(f"{base}/v2", headers=operator)).status_code == 403
    assert (await client.delete(f"{base}/v2", headers=auth_headers(admin_token))).status_code == 204


async def test_audit_actions_are_recorded(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = _base(router_id)

    assert (
        await client.put(f"{base}/v2/global", headers=headers, json=GLOBAL_BODY)
    ).status_code == 200
    assert (
        await client.post(f"{base}/v2/areas", headers=headers, json={"area_id": "5"})
    ).status_code == 201
    assert (
        await client.put(f"{base}/v2/areas/0.0.0.5", headers=headers, json={"area_type": "stub"})
    ).status_code == 200
    assert (await client.delete(f"{base}/v2/areas/0.0.0.5", headers=headers)).status_code == 200
    assert (
        await client.post(
            f"{base}/v2/interfaces",
            headers=headers,
            json={"name": "eth5", "area_id": "0"},
        )
    ).status_code == 201
    assert (
        await client.put(
            f"{base}/v2/interfaces/eth5", headers=headers, json={"area_id": "0", "cost": 5}
        )
    ).status_code == 200
    assert (await client.delete(f"{base}/v2/interfaces/eth5", headers=headers)).status_code == 200
    assert (
        await client.post(f"{base}/v2/redistribute", headers=headers, json={"source": "static"})
    ).status_code == 201
    assert (
        await client.put(f"{base}/v2/redistribute/static", headers=headers, json={"metric": 5})
    ).status_code == 200
    assert (
        await client.delete(f"{base}/v2/redistribute/static", headers=headers)
    ).status_code == 200
    assert (await client.delete(f"{base}/v2", headers=headers)).status_code == 204

    audit = await client.get("/api/v1/audit", headers=headers, params={"limit": 100})
    assert audit.status_code == 200, audit.text
    items = audit.json()["items"]
    actions = {item["action"] for item in items}
    assert {
        "ospf.global.update",
        "ospf.area.create",
        "ospf.area.update",
        "ospf.area.delete",
        "ospf.interface.create",
        "ospf.interface.update",
        "ospf.interface.delete",
        "ospf.redistribute.create",
        "ospf.redistribute.update",
        "ospf.redistribute.delete",
        "ospf.delete",
    } <= actions

    resource_types = {item["action"]: item["resource_type"] for item in items}
    assert resource_types["ospf.area.create"] == "ospf_area"
    assert resource_types["ospf.interface.update"] == "ospf_interface"
    assert resource_types["ospf.redistribute.delete"] == "ospf_redistribute"
    assert resource_types["ospf.global.update"] == "ospf_process"

    details = {item["action"]: item["details"] for item in items}
    assert details["ospf.area.create"]["area_id"] == "0.0.0.5"
    assert details["ospf.interface.create"]["name"] == "eth5"
    assert details["ospf.redistribute.create"]["source"] == "static"
    assert details["ospf.delete"]["version"] == "v2"


async def test_route_map_usage_and_delete_refusal(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    route_maps = f"/api/v1/routers/{router_id}/route-maps"

    fetched = await client.get(f"{route_maps}/OSPF-OUT", headers=headers)
    assert fetched.status_code == 200, fetched.text
    body = fetched.json()
    assert body["in_use"] is True
    assert body["used_by"] == [
        "OSPFv2 redistribute connected · route-map",
        "OSPFv3 redistribute connected · route-map",
    ]

    deleted = await client.delete(f"{route_maps}/OSPF-OUT", headers=headers)
    assert deleted.status_code == 409
    error = deleted.json()["error"]
    assert error["code"] == "route_map_in_use"
    assert "OSPFv2 redistribute connected · route-map" in error["details"]["used_by"]
    assert "OSPFv3 redistribute connected · route-map" in error["details"]["used_by"]


async def test_unreachable_router_maps_to_502(client, admin_token) -> None:
    headers = auth_headers(admin_token)
    created = await client.post(
        "/api/v1/routers",
        headers=headers,
        json={
            "name": "unreachable-ospf",
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

    for path in (
        f"/api/v1/routers/{router_id}/ospf/v2",
        f"/api/v1/routers/{router_id}/ospf/v2/status",
    ):
        response = await client.get(path, headers=headers)
        assert response.status_code == 502, response.text
        assert response.json()["error"]["code"] in {
            "router_unreachable",
            "router_command_failed",
        }


async def test_route_map_usage_tolerates_missing_ospf_config(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    route_maps = f"/api/v1/routers/{router_id}/route-maps"

    for version in ("v2", "v3"):
        deleted = await client.delete(f"{_base(router_id)}/{version}", headers=headers)
        assert deleted.status_code == 204

    fetched = await client.get(f"{route_maps}/OSPF-OUT", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["in_use"] is False
    assert fetched.json()["used_by"] == []

    # With the OSPF references gone the route map can be deleted.
    assert (await client.delete(f"{route_maps}/OSPF-OUT", headers=headers)).status_code == 204
