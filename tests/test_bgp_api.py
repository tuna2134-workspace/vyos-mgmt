"""Integration tests for BGP configuration and status endpoints."""

from __future__ import annotations

from datetime import datetime

from tests.helpers import auth_headers, create_mock_router

CONFIG_FIELDS = {
    "router",
    "configured",
    "global",
    "neighbors",
    "peer_groups",
    "networks",
    "supported_address_families",
}
GLOBAL_FIELDS = {"configured", "system_as", "router_id", "log_neighbor_changes"}
NEIGHBOR_FIELDS = {
    "address",
    "remote_as",
    "description",
    "peer_group",
    "update_source",
    "ebgp_multihop",
    "password_configured",
    "passive",
    "shutdown",
    "timers",
    "local_as",
    "address_families",
}
PEER_GROUP_FIELDS = {
    "name",
    "remote_as",
    "description",
    "update_source",
    "ebgp_multihop",
    "password_configured",
    "address_families",
}
STATUS_FIELDS = {
    "configured",
    "router_id",
    "local_as",
    "peers",
    "total_peers",
    "established_peers",
    "collected_at",
    "error",
}
PEER_FIELDS = {
    "address",
    "remote_as",
    "state",
    "established",
    "uptime",
    "prefixes_received",
    "prefixes_sent",
    "msg_received",
    "msg_sent",
    "description",
    "address_family",
}

NEW_NEIGHBOR = {
    "address": "203.0.113.9",
    "remote_as": 65100,
    "description": "New peer",
    "peer_group": "transit",
    "update_source": "eth0",
    "ebgp_multihop": 2,
    "password": "s3cret-bgp-password",
    "passive": True,
    "shutdown": False,
    "timers": {"keepalive": 30, "holdtime": 90},
    "local_as": 64512,
    "address_families": {
        "ipv4-unicast": {
            "route_reflector_client": False,
            "next_hop_self": True,
            "soft_reconfiguration_inbound": True,
            "default_originate": False,
            "allowas_in": 3,
        }
    },
}


async def _router(client, token) -> str:
    device = await create_mock_router(client, token)
    return device["id"]


async def test_get_config_matches_contract(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    response = await client.get(
        f"/api/v1/routers/{router_id}/bgp", headers=auth_headers(admin_token)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == CONFIG_FIELDS
    assert body["router"]["id"] == router_id
    assert body["configured"] is True
    assert set(body["global"]) == GLOBAL_FIELDS
    assert body["global"] == {
        "configured": True,
        "system_as": 64512,
        "router_id": "10.255.0.1",
        "log_neighbor_changes": True,
    }
    assert body["supported_address_families"] == ["ipv4-unicast", "ipv6-unicast"]

    assert len(body["neighbors"]) == 3
    for neighbor in body["neighbors"]:
        assert set(neighbor) == NEIGHBOR_FIELDS
    transit = next(item for item in body["neighbors"] if item["address"] == "192.0.2.1")
    assert transit["remote_as"] == 65001
    assert transit["description"] == "Transit A"
    assert transit["ebgp_multihop"] == 2
    assert transit["password_configured"] is False
    assert transit["address_families"]["ipv4-unicast"]["route_reflector_client"] is True
    assert transit["address_families"]["ipv4-unicast"]["soft_reconfiguration_inbound"] is True
    assert transit["address_families"]["ipv4-unicast"]["route_map_import"] == "BGP-IN"
    assert transit["address_families"]["ipv4-unicast"]["route_map_export"] == "BGP-OUT"

    for group in body["peer_groups"]:
        assert set(group) == PEER_GROUP_FIELDS
    assert {(network["af"], network["prefix"]) for network in body["networks"]} == {
        ("ipv4-unicast", "203.0.113.0/24"),
        ("ipv6-unicast", "2001:db8:100::/48"),
    }


async def test_global_update_and_router_id_removal(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    url = f"/api/v1/routers/{router_id}/bgp/global"

    response = await client.put(
        url,
        headers=headers,
        json={"system_as": 64600, "router_id": "10.255.0.9", "log_neighbor_changes": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["global"]["system_as"] == 64600
    assert response.json()["global"]["router_id"] == "10.255.0.9"

    removed = await client.put(
        url,
        headers=headers,
        json={"system_as": 64600, "router_id": None, "log_neighbor_changes": False},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["global"]["router_id"] is None
    assert removed.json()["global"]["log_neighbor_changes"] is False

    invalid = await client.put(
        url,
        headers=headers,
        json={"system_as": 64600, "router_id": "not-an-ip"},
    )
    assert invalid.status_code == 422


async def test_neighbor_crud(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/bgp/neighbors"

    created = await client.post(base, headers=headers, json=NEW_NEIGHBOR)
    assert created.status_code == 200, created.text
    assert set(created.json()) == CONFIG_FIELDS
    neighbor = next(
        item for item in created.json()["neighbors"] if item["address"] == "203.0.113.9"
    )
    assert neighbor["remote_as"] == 65100
    assert neighbor["description"] == "New peer"
    assert neighbor["peer_group"] == "transit"
    assert neighbor["update_source"] == "eth0"
    assert neighbor["ebgp_multihop"] == 2
    assert neighbor["password_configured"] is True
    assert neighbor["passive"] is True
    assert neighbor["timers"] == {"keepalive": 30, "holdtime": 90}
    assert neighbor["local_as"] == 64512
    assert neighbor["address_families"]["ipv4-unicast"]["next_hop_self"] is True
    assert neighbor["address_families"]["ipv4-unicast"]["allowas_in"] == 3
    assert "password" not in neighbor
    assert NEW_NEIGHBOR["password"] not in created.text

    duplicate = await client.post(base, headers=headers, json=NEW_NEIGHBOR)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "neighbor_exists"

    updated = await client.patch(
        f"{base}/203.0.113.9",
        headers=headers,
        json={"description": None, "password": "", "timers": None},
    )
    assert updated.status_code == 200, updated.text
    neighbor = next(
        item for item in updated.json()["neighbors"] if item["address"] == "203.0.113.9"
    )
    assert neighbor["description"] is None
    assert neighbor["password_configured"] is False
    assert neighbor["timers"] is None
    assert neighbor["remote_as"] == 65100

    # address_families is authoritative for the managed families.
    switched = await client.patch(
        f"{base}/203.0.113.9",
        headers=headers,
        json={"address_families": {"ipv6-unicast": {"next_hop_self": True}}},
    )
    assert switched.status_code == 200, switched.text
    neighbor = next(
        item for item in switched.json()["neighbors"] if item["address"] == "203.0.113.9"
    )
    assert set(neighbor["address_families"]) == {"ipv6-unicast"}
    assert neighbor["address_families"]["ipv6-unicast"]["next_hop_self"] is True

    emptied = await client.patch(
        f"{base}/203.0.113.9", headers=headers, json={"address_families": {}}
    )
    assert emptied.status_code == 200, emptied.text
    neighbor = next(
        item for item in emptied.json()["neighbors"] if item["address"] == "203.0.113.9"
    )
    assert neighbor["address_families"] == {}

    deleted = await client.delete(f"{base}/203.0.113.9", headers=headers)
    assert deleted.status_code == 200
    assert all(item["address"] != "203.0.113.9" for item in deleted.json()["neighbors"])

    missing = await client.delete(f"{base}/203.0.113.9", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "neighbor_not_found"


async def test_network_crud(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/bgp/networks"

    created = await client.post(
        base, headers=headers, json={"af": "ipv4-unicast", "prefix": "198.18.0.0/15"}
    )
    assert created.status_code == 200, created.text
    assert {"af": "ipv4-unicast", "prefix": "198.18.0.0/15"} in created.json()["networks"]

    duplicate = await client.post(
        base, headers=headers, json={"af": "ipv4-unicast", "prefix": "198.18.0.0/15"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "network_exists"

    for payload in [
        {"af": "ipv4-unicast", "prefix": "198.18.0.1/15"},
        {"af": "ipv4-unicast", "prefix": "2001:db8::/32"},
        {"af": "ipv6-unicast", "prefix": "198.18.0.0/15"},
        {"af": "ipv4-unicast", "prefix": "not-a-prefix"},
    ]:
        invalid = await client.post(base, headers=headers, json=payload)
        assert invalid.status_code == 422, invalid.text
        assert invalid.json()["error"]["code"] == "validation_error"

    deleted = await client.delete(
        base,
        headers=headers,
        params={"af": "ipv4-unicast", "prefix": "198.18.0.0/15"},
    )
    assert deleted.status_code == 200, deleted.text
    assert {"af": "ipv4-unicast", "prefix": "198.18.0.0/15"} not in deleted.json()["networks"]

    missing = await client.delete(
        base,
        headers=headers,
        params={"af": "ipv4-unicast", "prefix": "198.18.0.0/15"},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "network_not_found"


async def test_peer_group_crud(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/bgp/peer-groups"

    created = await client.post(
        base,
        headers=headers,
        json={"name": "ix", "remote_as": 65200, "description": "IX peers"},
    )
    assert created.status_code == 200, created.text
    group = next(item for item in created.json()["peer_groups"] if item["name"] == "ix")
    assert group["remote_as"] == 65200
    assert group["description"] == "IX peers"
    assert set(group["address_families"]) == {"ipv4-unicast"}

    duplicate = await client.post(base, headers=headers, json={"name": "ix", "remote_as": 65201})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "peer_group_exists"

    updated = await client.patch(
        f"{base}/ix", headers=headers, json={"description": None, "ebgp_multihop": 3}
    )
    assert updated.status_code == 200, updated.text
    group = next(item for item in updated.json()["peer_groups"] if item["name"] == "ix")
    assert group["description"] is None
    assert group["ebgp_multihop"] == 3

    deleted = await client.delete(f"{base}/ix", headers=headers)
    assert deleted.status_code == 200
    assert all(item["name"] != "ix" for item in deleted.json()["peer_groups"])

    missing = await client.delete(f"{base}/ix", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "peer_group_not_found"


async def test_status_contract(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    response = await client.get(f"/api/v1/routers/{router_id}/bgp/status", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == STATUS_FIELDS
    assert body["configured"] is True
    assert body["router_id"] == "10.255.0.1"
    assert body["local_as"] == 64512
    assert body["total_peers"] == 3
    assert body["established_peers"] == 2
    assert body["error"] is None
    datetime.fromisoformat(body["collected_at"])
    for peer in body["peers"]:
        assert set(peer) == PEER_FIELDS
    down = next(peer for peer in body["peers"] if peer["address"] == "198.51.100.1")
    assert down["established"] is False
    assert down["state"] == "Idle (Admin)"


async def test_delete_bgp_and_status_not_configured(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)

    deleted = await client.delete(f"/api/v1/routers/{router_id}/bgp", headers=headers)
    assert deleted.status_code == 204

    config = await client.get(f"/api/v1/routers/{router_id}/bgp", headers=headers)
    assert config.status_code == 200
    assert config.json()["configured"] is False
    assert config.json()["neighbors"] == []

    status = await client.get(f"/api/v1/routers/{router_id}/bgp/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["configured"] is False
    assert status.json()["peers"] == []

    # Idempotent delete.
    assert (
        await client.delete(f"/api/v1/routers/{router_id}/bgp", headers=headers)
    ).status_code == 204


async def test_unreachable_router_maps_to_502(client, admin_token) -> None:
    headers = auth_headers(admin_token)
    created = await client.post(
        "/api/v1/routers",
        headers=headers,
        json={
            "name": "unreachable-bgp",
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

    response = await client.get(f"/api/v1/routers/{router_id}/bgp", headers=headers)
    assert response.status_code == 502
    assert response.json()["error"]["code"] in {
        "router_unreachable",
        "router_command_failed",
    }
