"""Integration tests for the WireGuard API."""

from __future__ import annotations

import uuid

from tests.helpers import auth_headers, create_mock_router
from vyos_mgmt.services.vyos.mock_driver import (
    WIREGUARD_SEED_PEER_PUBLIC_KEY,
    WIREGUARD_SEED_PRESHARED_KEY,
    WIREGUARD_SEED_PRIVATE_KEY,
    WIREGUARD_SEED_ROAD_WARRIOR_PUBLIC_KEY,
)
from vyos_mgmt.services.wireguard_service import derive_public_key

INTERFACE_READ_FIELDS = {
    "name",
    "description",
    "addresses",
    "port",
    "mtu",
    "enabled",
    "public_key",
    "peer_count",
}
PEER_READ_FIELDS = {
    "name",
    "description",
    "public_key",
    "allowed_ips",
    "endpoint",
    "endpoint_port",
    "persistent_keepalive",
    "has_preshared_key",
    "enabled",
}
DETAIL_FIELDS = INTERFACE_READ_FIELDS | {"peers"}
STATUS_FIELDS = {
    "configured",
    "name",
    "public_key",
    "listening_port",
    "peers",
    "collected_at",
    "error",
}
STATUS_PEER_FIELDS = {
    "public_key",
    "endpoint",
    "allowed_ips",
    "latest_handshake",
    "transfer_received",
    "transfer_sent",
}

PRIVATE_KEY = "iJJyEARGK52Ls1GYRCcFvPuTj7WyWYDo//BknoDU0XY="
NEW_PRIVATE_KEY = "4Krkv8h6NkAYMMaBWI957yYDJDMvj9URTHstdlOcDU0="
PUBLIC_KEY = "EKY0dxRrSD98QHjfHOK13mZ5PJ7hnddRZt5woB3szyw="
OTHER_PUBLIC_KEY = "XMrlPykaxhdAAiSjhtPlvi30NVkvLQliQuKP7AI7CyI="
THIRD_PUBLIC_KEY = "OHH2EwZfMNK+1L6BXbYw3bKCtMrfjpR4mCAEeBlFnRs="
PRESHARED_KEY = "J+qO2PNBJ+EpYO4FHcmE1XOBRBHJjQjV4qy+s7R80fo="
NEW_PRESHARED_KEY = "OHH2EwZfMNK+1L6BXbYw3bKCtMrfjpR4mCAEeBlFnRs="


async def _router(client, token: str, name: str = "wg-router") -> str:
    device = await create_mock_router(client, token, name=name)
    return device["id"]


def _base(router_id: str) -> str:
    return f"/api/v1/routers/{router_id}/wireguard"


async def _audit_actions(client, admin_token: str) -> list[dict]:
    response = await client.get(
        "/api/v1/audit",
        headers=auth_headers(admin_token),
        params={"limit": 200},
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def test_list_detail_and_status_match_contract(client, viewer_token, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(viewer_token)
    base = _base(router_id)

    listing = await client.get(base, headers=headers)
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert set(body) == {"items", "total"}
    assert body["total"] == 1
    assert set(body["items"][0]) == INTERFACE_READ_FIELDS
    interface = body["items"][0]
    assert interface["name"] == "wg0"
    assert interface["description"] == "Tokyo branch tunnel"
    assert interface["addresses"] == ["10.100.0.1/24", "2001:db8:100::1/64"]
    assert interface["port"] == 51820
    assert interface["mtu"] == 1420
    assert interface["enabled"] is True
    assert interface["public_key"] is not None
    assert interface["peer_count"] == 2
    assert WIREGUARD_SEED_PRIVATE_KEY not in listing.text
    assert WIREGUARD_SEED_PRESHARED_KEY not in listing.text

    detail = await client.get(f"{base}/wg0", headers=headers)
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert set(detail_body) == DETAIL_FIELDS
    assert [peer["name"] for peer in detail_body["peers"]] == [
        "branch-office",
        "road-warrior",
    ]
    for peer in detail_body["peers"]:
        assert set(peer) == PEER_READ_FIELDS
    assert detail_body["peers"][0]["has_preshared_key"] is True
    assert detail_body["peers"][0]["endpoint"] == "198.51.100.10"
    assert detail_body["peers"][0]["endpoint_port"] == 51820
    assert detail_body["peers"][1]["endpoint"] is None
    assert WIREGUARD_SEED_PRIVATE_KEY not in detail.text
    assert WIREGUARD_SEED_PRESHARED_KEY not in detail.text

    status = await client.get(f"{base}/wg0/status", headers=headers)
    assert status.status_code == 200, status.text
    status_body = status.json()
    assert set(status_body) == STATUS_FIELDS
    assert status_body["configured"] is True
    assert status_body["name"] == "wg0"
    assert status_body["listening_port"] == 51820
    assert status_body["error"] is None
    assert len(status_body["peers"]) == 2
    for peer in status_body["peers"]:
        assert set(peer) == STATUS_PEER_FIELDS
    assert status_body["peers"][0]["endpoint"] == "198.51.100.10:51820"
    assert status_body["peers"][0]["transfer_received"] == "1.26 MiB"
    assert WIREGUARD_SEED_PRIVATE_KEY not in status.text
    assert WIREGUARD_SEED_PRESHARED_KEY not in status.text

    for token in (admin_token, viewer_token):
        response = await client.get(base, headers=auth_headers(token))
        assert response.status_code == 200


async def test_missing_interface_and_router_errors(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = _base(router_id)

    for path in (f"{base}/wg9", f"{base}/wg9/status"):
        response = await client.get(path, headers=headers)
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "wireguard_interface_not_found"

    unknown = await client.get(_base(str(uuid.uuid4())), headers=headers)
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "router_not_found"

    for name in ("wg", "wg0a", "WG0", "wg-1"):
        response = await client.get(f"{base}/{name}", headers=headers)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation_error"
        assert response.json()["error"]["details"][0]["loc"] == ["path", "name"]

    unauthenticated = await client.get(base)
    assert unauthenticated.status_code == 401


async def test_interface_crud_and_rbac(client, admin_token, operator_token, viewer_token) -> None:
    router_id = await _router(client, admin_token)
    base = _base(router_id)
    operator_headers = auth_headers(operator_token)

    payload = {
        "name": "wg1",
        "description": "New tunnel",
        "addresses": ["10.9.0.1/24", "2001:db8:9::1/64"],
        "port": 51900,
        "mtu": 1400,
        "enabled": True,
        "private_key": PRIVATE_KEY,
    }

    created = await client.post(base, headers=operator_headers, json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert set(body) == DETAIL_FIELDS
    assert body["name"] == "wg1"
    assert body["description"] == "New tunnel"
    assert body["addresses"] == ["10.9.0.1/24", "2001:db8:9::1/64"]
    assert body["port"] == 51900
    assert body["mtu"] == 1400
    assert body["public_key"] is not None
    assert body["peers"] == []
    assert PRIVATE_KEY not in created.text

    duplicate = await client.post(base, headers=operator_headers, json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "wireguard_interface_exists"

    updated = await client.put(
        f"{base}/wg1",
        headers=operator_headers,
        json={
            "description": "Changed",
            "addresses": ["10.9.0.1/24"],
            "port": None,
            "mtu": None,
            "enabled": False,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "Changed"
    assert updated.json()["addresses"] == ["10.9.0.1/24"]
    assert updated.json()["port"] is None
    assert updated.json()["mtu"] is None
    assert updated.json()["enabled"] is False
    # The private key is untouched by a metadata update.
    assert updated.json()["public_key"] == body["public_key"]
    assert PRIVATE_KEY not in updated.text

    for token in (viewer_token,):
        forbidden = await client.post(
            base, headers=auth_headers(token), json={**payload, "name": "wg2"}
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "forbidden"

    viewer_update = await client.put(
        f"{base}/wg1",
        headers=auth_headers(viewer_token),
        json={"enabled": True},
    )
    assert viewer_update.status_code == 403

    deleted = await client.delete(f"{base}/wg1", headers=operator_headers)
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert (await client.get(f"{base}/wg1", headers=operator_headers)).status_code == 404
    assert (await client.delete(f"{base}/wg1", headers=operator_headers)).status_code == 404


async def test_interface_validation_errors_and_secret_redaction(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    base = _base(router_id)
    headers = auth_headers(admin_token)

    secret = "super-secret-private-key-material"
    invalid_bodies = [
        {"name": "wg", "private_key": PRIVATE_KEY},
        {"name": "wg0a", "private_key": PRIVATE_KEY},
        {"name": "wg2", "private_key": "not-base64"},
        {"name": "wg2", "private_key": PRIVATE_KEY, "addresses": ["10.0.0.1"]},
        {"name": "wg2", "private_key": PRIVATE_KEY, "port": 0},
        {"name": "wg2", "private_key": PRIVATE_KEY, "mtu": 67},
        {"name": "wg2"},
        {"name": "wg2", "private_key": secret},
    ]
    for body in invalid_bodies:
        response = await client.post(base, headers=headers, json=body)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation_error"
        assert secret not in response.text

    redacted = await client.post(base, headers=headers, json={"name": "wg2", "private_key": secret})
    assert redacted.status_code == 422
    error = redacted.json()["error"]
    assert error["details"][0]["loc"] == ["body", "private_key"]
    assert error["details"][0]["input"] == "[redacted]"

    # Unknown fields are ignored by the schema, as elsewhere in the API.
    unknown = await client.post(
        base,
        headers=headers,
        json={"name": "wg3", "private_key": PRIVATE_KEY, "unexpected": True},
    )
    assert unknown.status_code == 201, unknown.text


async def test_private_key_rotation_and_audit_redaction(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    base = _base(router_id)
    headers = auth_headers(admin_token)

    before = await client.get(f"{base}/wg0", headers=headers)
    assert before.status_code == 200
    before_public_key = before.json()["public_key"]

    rotated = await client.put(
        f"{base}/wg0/private-key",
        headers=headers,
        json={"private_key": NEW_PRIVATE_KEY},
    )
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["public_key"] != before_public_key
    assert NEW_PRIVATE_KEY not in rotated.text
    assert WIREGUARD_SEED_PRIVATE_KEY not in rotated.text

    invalid = await client.put(
        f"{base}/wg0/private-key",
        headers=headers,
        json={"private_key": "not-a-key"},
    )
    assert invalid.status_code == 422
    assert "not-a-key" not in invalid.text

    missing = await client.put(
        f"{base}/wg9/private-key",
        headers=headers,
        json={"private_key": NEW_PRIVATE_KEY},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "wireguard_interface_not_found"

    events = await _audit_actions(client, admin_token)
    event = next(item for item in events if item["action"] == "wireguard.private_key.update")
    assert event["resource_type"] == "wireguard_interface"
    assert event["resource_id"] == "wg0"
    assert event["details"] == {"name": "wg0"}
    assert NEW_PRIVATE_KEY not in str(event)
    assert WIREGUARD_SEED_PRIVATE_KEY not in str(event)


async def test_key_generation_endpoints_and_route_ordering(
    client, admin_token, operator_token, viewer_token
) -> None:
    router_id = await _router(client, admin_token)
    base = _base(router_id)
    operator_headers = auth_headers(operator_token)

    keypair = await client.post(f"{base}/keypair", headers=operator_headers)
    assert keypair.status_code == 200, keypair.text
    assert keypair.headers["cache-control"] == "no-store"
    keypair_body = keypair.json()
    assert set(keypair_body) == {"private_key", "public_key"}
    assert keypair_body["private_key"] != keypair_body["public_key"]
    assert derive_public_key(keypair_body["private_key"]) == keypair_body["public_key"]

    # Calling the same route again must not be interpreted as an interface name
    # and must produce a fresh keypair.
    second = await client.post(f"{base}/keypair", headers=operator_headers)
    assert second.status_code == 200
    assert second.json()["private_key"] != keypair_body["private_key"]

    preshared = await client.post(f"{base}/preshared-key", headers=operator_headers)
    assert preshared.status_code == 200, preshared.text
    assert set(preshared.json()) == {"preshared_key"}

    for token in (viewer_token,):
        forbidden = await client.post(f"{base}/keypair", headers=auth_headers(token))
        assert forbidden.status_code == 403
        forbidden_psk = await client.post(f"{base}/preshared-key", headers=auth_headers(token))
        assert forbidden_psk.status_code == 403

    unknown_router = await client.post(
        f"{_base(str(uuid.uuid4()))}/keypair", headers=operator_headers
    )
    assert unknown_router.status_code == 404
    assert unknown_router.json()["error"]["code"] == "router_not_found"

    events = await _audit_actions(client, admin_token)
    assert not any(item["action"].startswith("wireguard.key") for item in events)
    assert not any("keypair" in item["action"] for item in events)
    assert keypair_body["private_key"] not in str(events)
    assert preshared.json()["preshared_key"] not in str(events)


async def test_peer_crud_conflicts_and_psk_tristate(client, admin_token, viewer_token) -> None:
    router_id = await _router(client, admin_token)
    base = _base(router_id)
    headers = auth_headers(admin_token)

    payload = {
        "name": "new-peer",
        "description": "New peer",
        "public_key": THIRD_PUBLIC_KEY,
        "allowed_ips": ["10.250.0.2/32"],
        "endpoint": "203.0.113.20",
        "endpoint_port": 51820,
        "persistent_keepalive": 25,
        "preshared_key": PRESHARED_KEY,
        "enabled": True,
    }
    created = await client.post(f"{base}/wg0/peers", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    peer = next(item for item in body["peers"] if item["name"] == "new-peer")
    assert set(peer) == PEER_READ_FIELDS
    assert peer["has_preshared_key"] is True
    assert peer["endpoint"] == "203.0.113.20"
    assert PRESHARED_KEY not in created.text

    duplicate = await client.post(
        f"{base}/wg0/peers",
        headers=headers,
        json={**payload, "allowed_ips": ["10.250.0.3/32"]},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "wireguard_peer_exists"

    duplicate_key = await client.post(
        f"{base}/wg0/peers",
        headers=headers,
        json={
            **payload,
            "name": "duplicate-key",
            "public_key": WIREGUARD_SEED_PEER_PUBLIC_KEY,
            "allowed_ips": ["10.250.0.4/32"],
        },
    )
    assert duplicate_key.status_code == 422
    assert duplicate_key.json()["error"]["code"] == "wireguard_public_key_conflict"

    duplicate_prefix = await client.post(
        f"{base}/wg0/peers",
        headers=headers,
        json={
            **payload,
            "name": "duplicate-prefix",
            "public_key": OTHER_PUBLIC_KEY,
            "allowed_ips": ["192.168.50.0/24"],
        },
    )
    assert duplicate_prefix.status_code == 422
    error = duplicate_prefix.json()["error"]
    assert error["code"] == "wireguard_allowed_ips_conflict"
    assert error["details"]["allowed_ips"] == ["192.168.50.0/24"]
    assert error["details"]["peers"] == ["branch-office"]
    assert error["details"]["conflicts"] == [
        {"allowed_ip": "192.168.50.0/24", "peer": "branch-office"}
    ]

    # Omitted preshared_key preserves the existing secret.
    preserved = await client.put(
        f"{base}/wg0/peers/new-peer",
        headers=headers,
        json={
            "public_key": OTHER_PUBLIC_KEY,
            "allowed_ips": ["10.250.0.2/32"],
            "endpoint": "vpn.example.com",
            "endpoint_port": 51900,
            "enabled": True,
        },
    )
    assert preserved.status_code == 200, preserved.text
    peer = next(item for item in preserved.json()["peers"] if item["name"] == "new-peer")
    assert peer["public_key"] == OTHER_PUBLIC_KEY
    assert peer["endpoint"] == "vpn.example.com"
    assert peer["has_preshared_key"] is True
    assert PRESHARED_KEY not in preserved.text

    # Explicit null removes it.
    removed = await client.put(
        f"{base}/wg0/peers/new-peer",
        headers=headers,
        json={
            "public_key": OTHER_PUBLIC_KEY,
            "allowed_ips": ["10.250.0.2/32"],
            "preshared_key": None,
            "enabled": True,
        },
    )
    assert removed.status_code == 200, removed.text
    peer = next(item for item in removed.json()["peers"] if item["name"] == "new-peer")
    assert peer["has_preshared_key"] is False

    # A string replaces it.
    replaced = await client.put(
        f"{base}/wg0/peers/new-peer",
        headers=headers,
        json={
            "public_key": OTHER_PUBLIC_KEY,
            "allowed_ips": ["10.250.0.2/32"],
            "preshared_key": NEW_PRESHARED_KEY,
            "enabled": True,
        },
    )
    assert replaced.status_code == 200, replaced.text
    peer = next(item for item in replaced.json()["peers"] if item["name"] == "new-peer")
    assert peer["has_preshared_key"] is True
    assert NEW_PRESHARED_KEY not in replaced.text

    viewer_write = await client.post(
        f"{base}/wg0/peers",
        headers=auth_headers(viewer_token),
        json={**payload, "name": "viewer-peer"},
    )
    assert viewer_write.status_code == 403

    deleted = await client.delete(f"{base}/wg0/peers/new-peer", headers=headers)
    assert deleted.status_code == 204
    assert deleted.content == b""
    missing = await client.delete(f"{base}/wg0/peers/new-peer", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "wireguard_peer_not_found"

    missing_interface = await client.post(
        f"{base}/wg9/peers", headers=headers, json={**payload, "name": "orphan"}
    )
    assert missing_interface.status_code == 404
    assert missing_interface.json()["error"]["code"] == "wireguard_interface_not_found"

    invalid_peer = await client.post(
        f"{base}/wg0/peers",
        headers=headers,
        json={**payload, "name": "bad peer"},
    )
    assert invalid_peer.status_code == 422
    assert invalid_peer.json()["error"]["code"] == "validation_error"

    invalid_secret = await client.post(
        f"{base}/wg0/peers",
        headers=headers,
        json={**payload, "name": "bad-secret", "preshared_key": "super-secret-psk"},
    )
    assert invalid_secret.status_code == 422
    assert "super-secret-psk" not in invalid_secret.text
    assert invalid_secret.json()["error"]["details"][0]["input"] == "[redacted]"


async def test_peer_path_validation(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    base = _base(router_id)
    headers = auth_headers(admin_token)
    for peer in ("has space", "x" * 101):
        response = await client.put(
            f"{base}/wg0/peers/{peer}",
            headers=headers,
            json={"public_key": PUBLIC_KEY, "allowed_ips": ["10.0.0.0/8"]},
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation_error"
        assert response.json()["error"]["details"][0]["loc"] == ["path", "peer"]


async def test_audit_actions_for_interface_and_peer_writes(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    base = _base(router_id)
    headers = auth_headers(admin_token)

    created = await client.post(
        base,
        headers=headers,
        json={
            "name": "wg5",
            "description": "Audited",
            "addresses": ["10.55.0.1/24"],
            "private_key": PRIVATE_KEY,
        },
    )
    assert created.status_code == 201, created.text
    updated = await client.put(
        f"{base}/wg5",
        headers=headers,
        json={
            "description": "Audited updated",
            "addresses": ["10.55.0.1/24"],
            "enabled": True,
        },
    )
    assert updated.status_code == 200, updated.text

    peer_payload = {
        "name": "audited-peer",
        "description": "Peer",
        "public_key": THIRD_PUBLIC_KEY,
        "allowed_ips": ["10.55.0.2/32"],
        "endpoint": "203.0.113.55",
        "preshared_key": PRESHARED_KEY,
    }
    peer_created = await client.post(f"{base}/wg5/peers", headers=headers, json=peer_payload)
    assert peer_created.status_code == 201, peer_created.text
    peer_updated = await client.put(
        f"{base}/wg5/peers/audited-peer",
        headers=headers,
        json={
            "description": "Peer updated",
            "public_key": THIRD_PUBLIC_KEY,
            "allowed_ips": ["10.55.0.2/32"],
        },
    )
    assert peer_updated.status_code == 200, peer_updated.text
    peer_deleted = await client.delete(f"{base}/wg5/peers/audited-peer", headers=headers)
    assert peer_deleted.status_code == 204
    deleted = await client.delete(f"{base}/wg5", headers=headers)
    assert deleted.status_code == 204

    events = await _audit_actions(client, admin_token)
    wireguard_events = [item for item in events if item["action"].startswith("wireguard.")]
    actions = {item["action"] for item in wireguard_events}
    assert actions == {
        "wireguard.interface.create",
        "wireguard.interface.update",
        "wireguard.interface.delete",
        "wireguard.peer.create",
        "wireguard.peer.update",
        "wireguard.peer.delete",
    }

    by_action = {item["action"]: item for item in wireguard_events}
    assert by_action["wireguard.interface.create"]["resource_type"] == "wireguard_interface"
    assert by_action["wireguard.interface.create"]["resource_id"] == "wg5"
    assert by_action["wireguard.interface.create"]["details"]["addresses"] == ["10.55.0.1/24"]
    assert by_action["wireguard.peer.create"]["resource_type"] == "wireguard_peer"
    assert by_action["wireguard.peer.create"]["resource_id"] == "wg5:audited-peer"
    assert by_action["wireguard.peer.create"]["details"]["has_preshared_key"] is True
    assert by_action["wireguard.peer.delete"]["details"] == {
        "interface": "wg5",
        "peer": "audited-peer",
    }

    serialised = str(wireguard_events)
    for secret in (
        PRIVATE_KEY,
        PRESHARED_KEY,
        WIREGUARD_SEED_PRIVATE_KEY,
        WIREGUARD_SEED_PRESHARED_KEY,
    ):
        assert secret not in serialised
    for event in wireguard_events:
        details = event["details"] or {}
        assert "private_key" not in details
        assert "preshared_key" not in details


async def test_status_reports_disabled_interface_as_error(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    base = _base(router_id)
    headers = auth_headers(admin_token)

    disabled = await client.put(
        f"{base}/wg0",
        headers=headers,
        json={
            "description": "Tokyo branch tunnel",
            "addresses": ["10.100.0.1/24", "2001:db8:100::1/64"],
            "port": 51820,
            "mtu": 1420,
            "enabled": False,
        },
    )
    assert disabled.status_code == 200, disabled.text

    status = await client.get(f"{base}/wg0/status", headers=headers)
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["configured"] is True
    assert body["error"] is not None
    assert body["peers"] == []
    assert body["public_key"] is not None
    assert body["listening_port"] == 51820


async def test_peer_update_excludes_itself_from_conflicts(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    base = _base(router_id)
    headers = auth_headers(admin_token)

    response = await client.put(
        f"{base}/wg0/peers/branch-office",
        headers=headers,
        json={
            "description": "Branch router updated",
            "public_key": WIREGUARD_SEED_PEER_PUBLIC_KEY,
            "allowed_ips": ["192.168.50.0/24", "192.168.60.0/24"],
            "endpoint": "198.51.100.10",
            "endpoint_port": 51820,
            "persistent_keepalive": 25,
            "enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    peer = next(item for item in response.json()["peers"] if item["name"] == "branch-office")
    assert peer["description"] == "Branch router updated"
    assert peer["has_preshared_key"] is True

    # The road-warrior peer must not be allowed to reuse the branch prefix.
    conflict = await client.put(
        f"{base}/wg0/peers/road-warrior",
        headers=headers,
        json={
            "public_key": WIREGUARD_SEED_ROAD_WARRIOR_PUBLIC_KEY,
            "allowed_ips": ["192.168.50.0/24"],
        },
    )
    assert conflict.status_code == 422
    assert conflict.json()["error"]["code"] == "wireguard_allowed_ips_conflict"
