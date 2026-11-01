"""Integration tests for the static-route API."""

from __future__ import annotations

import uuid
from typing import Any

from tests.helpers import auth_headers, create_mock_router

ROUTE_FIELDS = {
    "family",
    "prefix",
    "description",
    "blackhole",
    "reject",
    "distance",
    "tag",
    "next_hops",
}
NEXT_HOP_FIELDS = {"address", "interface", "distance", "enabled"}


def _create_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "family": "ipv4",
        "prefix": "198.18.0.0/15",
        "description": "Lab block",
        "blackhole": False,
        "reject": False,
        "distance": None,
        "tag": None,
        "next_hops": [
            {"address": "192.0.2.1", "interface": "eth0", "distance": 10, "enabled": True},
            {"interface": "eth1", "address": None, "distance": None, "enabled": True},
        ],
    }
    payload.update(overrides)
    return payload


async def _router(client, token: str) -> str:
    device = await create_mock_router(client, token)
    return device["id"]


async def test_list_and_detail_match_contract(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/static-routes"

    response = await client.get(base, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "total"}
    assert body["total"] == 9
    assert [(item["family"], item["prefix"]) for item in body["items"]] == [
        ("ipv4", "0.0.0.0/0"),
        ("ipv4", "10.0.0.0/8"),
        ("ipv4", "172.16.0.0/12"),
        ("ipv4", "192.168.50.0/24"),
        ("ipv4", "203.0.113.0/24"),
        ("ipv6", "::/0"),
        ("ipv6", "2001:db8:100::/64"),
        ("ipv6", "2001:db8:200::/48"),
        ("ipv6", "2001:db8:300::/48"),
    ]
    for item in body["items"]:
        assert set(item) == ROUTE_FIELDS
        for hop in item["next_hops"]:
            assert set(hop) == NEXT_HOP_FIELDS

    default = body["items"][0]
    assert default["description"] == "Default via transit"
    assert default["next_hops"] == [
        {"address": "192.0.2.254", "interface": None, "distance": None, "enabled": True}
    ]

    blackhole = body["items"][1]
    assert blackhole["blackhole"] is True
    assert blackhole["reject"] is False
    assert (blackhole["distance"], blackhole["tag"]) == (255, 100)
    assert blackhole["next_hops"] == []

    multi_hop = body["items"][4]
    assert [hop["address"] for hop in multi_hop["next_hops"]] == ["192.0.2.1", "198.51.100.1"]
    assert multi_hop["next_hops"][1]["enabled"] is False

    fetched = await client.get(f"{base}/ipv4/203.0.113.0/24", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == multi_hop

    # The prefix path uses a path converter, so literal slashes work...
    literal = await client.get(f"{base}/ipv6/2001:db8:200::/48", headers=headers)
    assert literal.status_code == 200, literal.text
    assert literal.json()["reject"] is True

    # ...as does the URL-encoded form.
    encoded_slash = await client.get(f"{base}/ipv4/10.0.0.0%2F8", headers=headers)
    assert encoded_slash.status_code == 200, encoded_slash.text
    assert encoded_slash.json()["blackhole"] is True

    encoded_all = await client.get(f"{base}/ipv6/2001%3Adb8%3A200%3A%3A%2F48", headers=headers)
    assert encoded_all.status_code == 200, encoded_all.text
    assert encoded_all.json()["prefix"] == "2001:db8:200::/48"

    ipv4 = await client.get(f"{base}?family=ipv4", headers=headers)
    assert ipv4.status_code == 200, ipv4.text
    assert ipv4.json()["total"] == 5
    assert {item["family"] for item in ipv4.json()["items"]} == {"ipv4"}

    ipv6 = await client.get(f"{base}?family=ipv6", headers=headers)
    assert ipv6.status_code == 200, ipv6.text
    assert [item["prefix"] for item in ipv6.json()["items"]] == [
        "::/0",
        "2001:db8:100::/64",
        "2001:db8:200::/48",
        "2001:db8:300::/48",
    ]


async def test_static_route_errors(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/static-routes"

    bad_filter = await client.get(f"{base}?family=ipv5", headers=headers)
    assert bad_filter.status_code == 422
    error = bad_filter.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["loc"] == ["query", "family"]

    bad_family = await client.get(f"{base}/ipv5/10.0.0.0/8", headers=headers)
    assert bad_family.status_code == 422
    assert bad_family.json()["error"]["code"] == "validation_error"
    assert bad_family.json()["error"]["details"][0]["loc"] == ["path", "family"]

    host_bits = await client.get(f"{base}/ipv4/10.0.0.1/8", headers=headers)
    assert host_bits.status_code == 422
    assert host_bits.json()["error"]["details"][0]["loc"] == ["path", "prefix"]

    mismatch = await client.get(f"{base}/ipv6/10.0.0.0/8", headers=headers)
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "validation_error"

    bare_prefix = await client.get(f"{base}/ipv4/10.0.0.0", headers=headers)
    assert bare_prefix.status_code == 422

    missing = await client.get(f"{base}/ipv4/198.51.100.0/24", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "static_route_not_found"

    missing_delete = await client.delete(f"{base}/ipv4/198.51.100.0/24", headers=headers)
    assert missing_delete.status_code == 404
    assert missing_delete.json()["error"]["code"] == "static_route_not_found"

    missing_update = await client.put(
        f"{base}/ipv4/198.51.100.0/24",
        headers=headers,
        json={"next_hops": [{"address": "192.0.2.1"}]},
    )
    assert missing_update.status_code == 404
    assert missing_update.json()["error"]["code"] == "static_route_not_found"

    unknown_router = await client.get(
        f"/api/v1/routers/{uuid.uuid4()}/static-routes", headers=headers
    )
    assert unknown_router.status_code == 404
    assert unknown_router.json()["error"]["code"] == "router_not_found"

    duplicate = await client.post(
        base,
        headers=headers,
        json=_create_payload(prefix="0.0.0.0/0"),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "static_route_exists"


async def test_create_update_delete(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/static-routes"

    created = await client.post(base, headers=headers, json=_create_payload())
    assert created.status_code == 201, created.text
    body = created.json()
    assert set(body) == ROUTE_FIELDS
    assert (body["family"], body["prefix"]) == ("ipv4", "198.18.0.0/15")
    assert body["description"] == "Lab block"
    assert [(hop["address"], hop["interface"]) for hop in body["next_hops"]] == [
        ("192.0.2.1", "eth0"),
        (None, "eth1"),
    ]
    assert body["next_hops"][0]["distance"] == 10
    assert (body["blackhole"], body["reject"]) == (False, False)
    assert (body["distance"], body["tag"]) == (None, None)

    ipv6 = await client.post(
        base,
        headers=headers,
        json={
            "family": "ipv6",
            "prefix": "2001:DB8:5000::/48",
            "next_hops": [{"address": "2001:db8:ffff::2"}],
        },
    )
    assert ipv6.status_code == 201, ipv6.text
    assert ipv6.json()["prefix"] == "2001:db8:5000::/48"
    # The same prefix is a different object in the IPv4 tree (as an error there).
    same_prefix_v4 = await client.post(
        base,
        headers=headers,
        json={"family": "ipv4", "prefix": "2001:db8:5000::/48", "next_hops": []},
    )
    assert same_prefix_v4.status_code == 422

    # Full replacement to blackhole: next hops and description are cleared.
    to_blackhole = await client.put(
        f"{base}/ipv4/198.18.0.0/15",
        headers=headers,
        json={"blackhole": True, "distance": 200, "tag": 7, "next_hops": []},
    )
    assert to_blackhole.status_code == 200, to_blackhole.text
    route = to_blackhole.json()
    assert route["blackhole"] is True
    assert (route["distance"], route["tag"]) == (200, 7)
    assert route["description"] is None
    assert route["next_hops"] == []

    # Reject replaces blackhole.
    to_reject = await client.put(
        f"{base}/ipv4/198.18.0.0/15",
        headers=headers,
        json={"reject": True, "distance": 250, "next_hops": []},
    )
    assert to_reject.status_code == 200, to_reject.text
    assert (to_reject.json()["blackhole"], to_reject.json()["reject"]) == (False, True)
    assert to_reject.json()["tag"] is None

    # Back to unicast, with a new next hop and a description.
    to_unicast = await client.put(
        f"{base}/ipv4/198.18.0.0/15",
        headers=headers,
        json={
            "description": "Restored",
            "next_hops": [
                {"address": "192.0.2.9", "interface": "eth9", "distance": 30, "enabled": False}
            ],
        },
    )
    assert to_unicast.status_code == 200, to_unicast.text
    route = to_unicast.json()
    assert (route["blackhole"], route["reject"]) == (False, False)
    assert (route["distance"], route["tag"]) == (None, None)
    assert route["next_hops"] == [
        {"address": "192.0.2.9", "interface": "eth9", "distance": 30, "enabled": False}
    ]

    deleted = await client.delete(f"{base}/ipv4/198.18.0.0/15", headers=headers)
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert (await client.get(f"{base}/ipv4/198.18.0.0/15", headers=headers)).status_code == 404
    assert (await client.delete(f"{base}/ipv4/198.18.0.0/15", headers=headers)).status_code == 404
    # The IPv6 route created above is untouched.
    assert (await client.get(f"{base}/ipv6/2001:db8:5000::/48", headers=headers)).status_code == 200


async def test_write_validation_errors(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/static-routes"

    invalid_payloads: list[dict[str, Any]] = [
        _create_payload(prefix="10.0.0.1/8"),
        _create_payload(prefix="10.0.0.0"),
        _create_payload(family="ipv6", prefix="198.18.0.0/15"),
        _create_payload(next_hops=[]),
        _create_payload(next_hops=[{"address": None, "interface": None}]),
        _create_payload(next_hops=[{"address": "192.0.2.1"}, {"address": "192.0.2.1"}]),
        _create_payload(next_hops=[{"address": "2001:db8::1"}]),
        _create_payload(next_hops=[{"address": "192.0.2.1", "distance": 0}]),
        _create_payload(blackhole=True, reject=True, next_hops=[]),
        _create_payload(blackhole=True),
        _create_payload(reject=True, next_hops=[{"interface": None, "address": "192.0.2.1"}]),
        _create_payload(distance=10),
        _create_payload(tag=10),
        _create_payload(description="d" * 256),
        _create_payload(blackhole=True, next_hops=[], tag=4_294_967_296),
        {"family": "ipv4", "prefix": "198.18.0.0/15"},
    ]
    for payload in invalid_payloads:
        response = await client.post(base, headers=headers, json=payload)
        assert response.status_code == 422, (payload, response.text)
        assert response.json()["error"]["code"] == "validation_error"

    # Path family mismatch on create is a body/prefix error with a field loc.
    mismatch = await client.post(
        base,
        headers=headers,
        json={
            "family": "ipv6",
            "prefix": "198.18.0.0/15",
            "next_hops": [{"address": "2001:db8::1"}],
        },
    )
    assert mismatch.json()["error"]["details"][0]["loc"] == ["body", "prefix"]

    duplicate_hop = await client.post(
        base,
        headers=headers,
        json=_create_payload(
            next_hops=[
                {"address": "192.0.2.1", "interface": "eth0"},
                {"address": "192.0.2.1", "interface": "eth0"},
            ]
        ),
    )
    assert duplicate_hop.json()["error"]["details"][0]["loc"] == ["body", "next_hops"]

    # The update body has no family; the service enforces it with a field loc.
    await client.post(base, headers=headers, json=_create_payload())
    wrong_family_update = await client.put(
        f"{base}/ipv4/198.18.0.0/15",
        headers=headers,
        json={"next_hops": [{"address": "2001:db8::1"}]},
    )
    assert wrong_family_update.status_code == 422
    error = wrong_family_update.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["loc"] == ["body", "next_hops.0.address"]

    bad_prefix_update = await client.put(
        f"{base}/ipv4/198.18.0.0/15",
        headers=headers,
        json={"next_hops": []},
    )
    assert bad_prefix_update.status_code == 422


async def test_static_route_rbac(client, admin_token, operator_token, viewer_token) -> None:
    router_id = await _router(client, admin_token)
    base = f"/api/v1/routers/{router_id}/static-routes"
    viewer_headers = auth_headers(viewer_token)
    operator_headers = auth_headers(operator_token)

    assert (await client.get(base, headers=viewer_headers)).status_code == 200
    assert (await client.get(f"{base}/ipv4/0.0.0.0/0", headers=viewer_headers)).status_code == 200

    viewer_requests = [
        await client.post(base, headers=viewer_headers, json=_create_payload()),
        await client.put(
            f"{base}/ipv4/203.0.113.0/24",
            headers=viewer_headers,
            json={"next_hops": [{"address": "192.0.2.1"}]},
        ),
        await client.delete(f"{base}/ipv4/0.0.0.0/0", headers=viewer_headers),
    ]
    for response in viewer_requests:
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "forbidden"

    created = await client.post(base, headers=operator_headers, json=_create_payload())
    assert created.status_code == 201, created.text

    updated = await client.put(
        f"{base}/ipv4/198.18.0.0/15",
        headers=operator_headers,
        json={"blackhole": True},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["blackhole"] is True

    deleted = await client.delete(f"{base}/ipv4/198.18.0.0/15", headers=operator_headers)
    assert deleted.status_code == 204


async def test_static_route_audit_entries(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/static-routes"

    created = await client.post(base, headers=headers, json=_create_payload())
    assert created.status_code == 201
    await client.put(
        f"{base}/ipv4/198.18.0.0/15",
        headers=headers,
        json={"blackhole": True, "distance": 100, "tag": 5, "next_hops": []},
    )
    await client.delete(f"{base}/ipv4/198.18.0.0/15", headers=headers)

    response = await client.get("/api/v1/audit", headers=headers, params={"limit": 50})
    assert response.status_code == 200, response.text
    events = [
        item for item in response.json()["items"] if item["action"].startswith("static_route.")
    ]
    assert sorted(event["action"] for event in events) == [
        "static_route.create",
        "static_route.delete",
        "static_route.update",
    ]
    for event in events:
        assert event["status"] == "success"
        assert event["actor_username"] == "admin"
        assert event["router_name"] == "edge-mock"
        assert event["resource_type"] == "static_route"
        assert event["resource_id"] == "ipv4:198.18.0.0/15"
        assert event["request_id"]

    by_action = {event["action"]: event for event in events}
    assert by_action["static_route.create"]["details"] == {
        "family": "ipv4",
        "prefix": "198.18.0.0/15",
        "type": "unicast",
        "next_hop_count": 2,
    }
    assert by_action["static_route.update"]["details"] == {
        "family": "ipv4",
        "prefix": "198.18.0.0/15",
        "type": "blackhole",
        "next_hop_count": 0,
    }
    assert by_action["static_route.delete"]["details"] == {
        "family": "ipv4",
        "prefix": "198.18.0.0/15",
        "type": "blackhole",
        "next_hop_count": 0,
    }
    assert "198.18" in response.text
    assert "private_key" not in response.text
