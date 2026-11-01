"""Integration tests for the route-map API."""

from __future__ import annotations

import copy
import uuid

from tests.helpers import auth_headers, create_mock_router

ROUTE_MAP_FIELDS = {"name", "description", "rules", "in_use", "used_by"}
RULE_FIELDS = {
    "number",
    "action",
    "description",
    "match",
    "set",
    "on_match",
    "goto_rule",
    "call",
    "continue_rule",
}
MATCH_FIELDS = {
    "ipv4_prefix_list",
    "ipv6_prefix_list",
    "as_path",
    "community_list",
    "community_exact_match",
    "large_community_list",
    "extcommunity",
    "metric",
    "local_preference",
    "origin",
    "tag",
    "protocol",
    "rpki",
    "ip_nexthop",
    "ipv6_nexthop",
    "interface",
}
SET_FIELDS = {
    "local_preference",
    "metric",
    "origin",
    "weight",
    "metric_type",
    "tag",
    "as_path_prepend",
    "community_action",
    "community_values",
    "community_delete",
    "ip_next_hop",
    "originator_id",
}

RULE_BODY = {
    "number": 10,
    "action": "permit",
    "description": "Allow transit prefixes",
    "match": {
        "ipv4_prefix_list": "TRANSIT-IN",
        "ipv6_prefix_list": None,
        "as_path": None,
        "community_list": "CUSTOMER-COMM",
        "community_exact_match": False,
        "large_community_list": None,
        "extcommunity": None,
        "metric": None,
        "local_preference": None,
        "origin": "igp",
        "tag": None,
        "protocol": "bgp",
        "rpki": "valid",
        "ip_nexthop": None,
        "ipv6_nexthop": None,
        "interface": None,
    },
    "set": {
        "local_preference": 200,
        "metric": "+50",
        "origin": None,
        "weight": None,
        "metric_type": None,
        "tag": None,
        "as_path_prepend": [64512, 64513],
        "community_action": "add",
        "community_values": ["64512:100", "no-export"],
        "community_delete": None,
        "ip_next_hop": None,
        "originator_id": None,
    },
    "on_match": "next",
    "goto_rule": None,
    "call": None,
    "continue_rule": None,
}

RULE_UPDATE = {
    "action": "deny",
    "description": None,
    "match": {
        "ipv6_prefix_list": "TRANSIT-V6",
        "community_list": "DEL-COMM",
        "community_exact_match": True,
        "metric": 100,
    },
    "set": {
        "local_preference": 300,
        "metric": "+100",
        "as_path_prepend": [64512],
        "community_action": "delete",
        "community_delete": "DEL-COMM",
    },
    "on_match": "goto",
    "goto_rule": 20,
    "call": "BGP-OUT",
    "continue_rule": 30,
}


async def _router(client, token: str) -> str:
    device = await create_mock_router(client, token)
    return device["id"]


async def _create_map(client, token: str, router_id: str, name: str) -> dict:
    response = await client.post(
        f"/api/v1/routers/{router_id}/route-maps",
        headers=auth_headers(token),
        json={"name": name, "description": f"{name} map"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_list_and_get_route_maps_match_contract(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/route-maps"

    response = await client.get(base, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "total"}
    assert body["total"] == 4
    assert [item["name"] for item in body["items"]] == [
        "BGP-IN",
        "BGP-OUT",
        "LOCAL-PREF",
        "OSPF-OUT",
    ]
    for item in body["items"]:
        assert set(item) == ROUTE_MAP_FIELDS
        for rule in item["rules"]:
            assert set(rule) == RULE_FIELDS
            assert set(rule["match"]) == MATCH_FIELDS
            assert set(rule["set"]) == SET_FIELDS

    bgp_in = body["items"][0]
    assert bgp_in["description"] == "Inbound filtering for transit"
    assert bgp_in["in_use"] is True
    assert bgp_in["used_by"] == ["BGP neighbor 192.0.2.1 · ipv4-unicast · import"]
    assert [rule["number"] for rule in bgp_in["rules"]] == [10, 20]
    rule = bgp_in["rules"][0]
    assert rule["action"] == "permit"
    assert rule["match"]["ipv4_prefix_list"] == "TRANSIT-IN"
    assert rule["match"]["community_list"] == "CUSTOMER-COMM"
    assert rule["match"]["origin"] == "igp"
    assert rule["match"]["protocol"] == "bgp"
    assert rule["match"]["rpki"] == "valid"
    assert rule["set"]["local_preference"] == 200
    assert rule["set"]["metric"] == "+50"
    assert rule["set"]["as_path_prepend"] == []
    assert rule["set"]["community_action"] == "add"
    assert rule["set"]["community_values"] == ["64512:100"]
    assert rule["on_match"] == "next"

    bgp_out = body["items"][1]
    assert "Route-map LOCAL-PREF rule 10 call" in bgp_out["used_by"]
    assert bgp_out["rules"][0]["set"]["as_path_prepend"] == [64512]
    assert bgp_out["rules"][0]["set"]["community_values"] == ["64512:200", "no-export"]

    fetched = await client.get(f"{base}/BGP-IN", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == bgp_in

    missing = await client.get(f"{base}/DOES-NOT-EXIST", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "route_map_not_found"

    unknown_router = await client.get(f"/api/v1/routers/{uuid.uuid4()}/route-maps", headers=headers)
    assert unknown_router.status_code == 404
    assert unknown_router.json()["error"]["code"] == "router_not_found"


async def test_route_map_crud(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/route-maps"

    created = await client.post(
        base, headers=headers, json={"name": "NEW-MAP", "description": "New map"}
    )
    assert created.status_code == 201, created.text
    assert set(created.json()) == ROUTE_MAP_FIELDS
    assert created.json()["name"] == "NEW-MAP"
    assert created.json()["description"] == "New map"
    assert created.json()["rules"] == []
    assert created.json()["in_use"] is False
    assert created.json()["used_by"] == []

    duplicate = await client.post(base, headers=headers, json={"name": "NEW-MAP"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "route_map_exists"

    for name in ("", "-bad", "bad name", "A" * 65):
        invalid = await client.post(base, headers=headers, json={"name": name})
        assert invalid.status_code == 422, invalid.text
        assert invalid.json()["error"]["code"] == "validation_error"

    updated = await client.put(f"{base}/NEW-MAP", headers=headers, json={"description": "Changed"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "Changed"

    cleared = await client.put(f"{base}/NEW-MAP", headers=headers, json={"description": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["description"] is None

    missing_update = await client.put(f"{base}/MISSING", headers=headers, json={"description": "x"})
    assert missing_update.status_code == 404
    assert missing_update.json()["error"]["code"] == "route_map_not_found"

    deleted = await client.delete(f"{base}/NEW-MAP", headers=headers)
    assert deleted.status_code == 204
    assert deleted.content == b""

    gone = await client.get(f"{base}/NEW-MAP", headers=headers)
    assert gone.status_code == 404
    assert gone.json()["error"]["code"] == "route_map_not_found"
    assert (await client.delete(f"{base}/NEW-MAP", headers=headers)).status_code == 404


async def test_rule_crud(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/route-maps"
    await _create_map(client, admin_token, router_id, "RULES")

    created = await client.post(
        f"{base}/RULES/rules", headers=headers, json=copy.deepcopy(RULE_BODY)
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["name"] == "RULES"
    assert [rule["number"] for rule in body["rules"]] == [10]
    rule = body["rules"][0]
    assert rule["action"] == "permit"
    assert rule["description"] == "Allow transit prefixes"
    assert rule["match"]["ipv4_prefix_list"] == "TRANSIT-IN"
    assert rule["match"]["community_list"] == "CUSTOMER-COMM"
    assert rule["match"]["origin"] == "igp"
    assert rule["set"]["local_preference"] == 200
    assert rule["set"]["metric"] == "+50"
    assert rule["set"]["as_path_prepend"] == [64512, 64513]
    assert rule["set"]["community_values"] == ["64512:100", "no-export"]
    assert rule["on_match"] == "next"

    duplicate = await client.post(
        f"{base}/RULES/rules", headers=headers, json=copy.deepcopy(RULE_BODY)
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "rule_exists"

    updated = await client.put(
        f"{base}/RULES/rules/10", headers=headers, json=copy.deepcopy(RULE_UPDATE)
    )
    assert updated.status_code == 200, updated.text
    rule = updated.json()["rules"][0]
    assert rule["number"] == 10
    assert rule["action"] == "deny"
    assert rule["description"] is None
    assert rule["match"]["ipv4_prefix_list"] is None
    assert rule["match"]["ipv6_prefix_list"] == "TRANSIT-V6"
    assert rule["match"]["community_list"] == "DEL-COMM"
    assert rule["match"]["community_exact_match"] is True
    assert rule["match"]["metric"] == 100
    assert rule["set"]["local_preference"] == 300
    assert rule["set"]["metric"] == "+100"
    assert rule["set"]["as_path_prepend"] == [64512]
    assert rule["set"]["community_action"] == "delete"
    assert rule["set"]["community_delete"] == "DEL-COMM"
    assert rule["on_match"] == "goto"
    assert rule["goto_rule"] == 20
    assert rule["call"] == "BGP-OUT"
    assert rule["continue_rule"] == 30

    # The path number is authoritative even if a stale body still carries one.
    stale_number = copy.deepcopy(RULE_UPDATE)
    stale_number["number"] = 99
    path_wins = await client.put(f"{base}/RULES/rules/10", headers=headers, json=stale_number)
    assert path_wins.status_code == 200, path_wins.text
    assert path_wins.json()["rules"][0]["number"] == 10

    missing_rule = await client.put(
        f"{base}/RULES/rules/999", headers=headers, json=copy.deepcopy(RULE_UPDATE)
    )
    assert missing_rule.status_code == 404
    assert missing_rule.json()["error"]["code"] == "rule_not_found"

    goto_self = copy.deepcopy(RULE_UPDATE)
    goto_self["goto_rule"] = 10
    rejected = await client.put(f"{base}/RULES/rules/10", headers=headers, json=goto_self)
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "validation_error"
    assert rejected.json()["error"]["details"][0]["loc"] == ["body", "goto_rule"]

    deleted = await client.delete(f"{base}/RULES/rules/10", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["rules"] == []
    missing_delete = await client.delete(f"{base}/RULES/rules/10", headers=headers)
    assert missing_delete.status_code == 404
    assert missing_delete.json()["error"]["code"] == "rule_not_found"

    no_map = await client.post(
        f"{base}/MISSING/rules", headers=headers, json=copy.deepcopy(RULE_BODY)
    )
    assert no_map.status_code == 404
    assert no_map.json()["error"]["code"] == "route_map_not_found"


async def test_rule_body_validation(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/route-maps"
    await _create_map(client, admin_token, router_id, "VALIDATION")

    invalid_rules = [
        {**copy.deepcopy(RULE_BODY), "action": "allow"},
        {key: value for key, value in RULE_BODY.items() if key != "number"},
        {**copy.deepcopy(RULE_BODY), "on_match": "goto"},
        {**copy.deepcopy(RULE_BODY), "on_match": "goto", "goto_rule": 10},
        {**copy.deepcopy(RULE_BODY), "continue_rule": 0},
        {**copy.deepcopy(RULE_BODY), "set": {"metric": "9999999999"}},
        {
            **copy.deepcopy(RULE_BODY),
            "set": {"community_action": "add", "community_values": ["70000:1"]},
        },
        {
            **copy.deepcopy(RULE_BODY),
            "match": {"community_list": "C", "community_exact_match": True},
            "set": {"metric": "-rtt"},
        },
    ]
    for payload in invalid_rules[:-1]:
        response = await client.post(f"{base}/VALIDATION/rules", headers=headers, json=payload)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation_error"

    # The final payload is valid: -rtt is an accepted metric expression.
    valid = invalid_rules[-1]
    response = await client.post(f"{base}/VALIDATION/rules", headers=headers, json=valid)
    assert response.status_code == 200, response.text
    assert response.json()["rules"][0]["set"]["metric"] == "-rtt"
    assert response.json()["rules"][0]["match"]["community_exact_match"] is True


async def test_delete_in_use_route_map_returns_conflict(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/route-maps"

    used_by_neighbor = "BGP neighbor 192.0.2.1 · ipv4-unicast · import"
    in_use = await client.delete(f"{base}/BGP-IN", headers=headers)
    assert in_use.status_code == 409
    body = in_use.json()["error"]
    assert body["code"] == "route_map_in_use"
    assert body["details"] == {"used_by": [used_by_neighbor]}

    call_reference = await client.delete(f"{base}/BGP-OUT", headers=headers)
    assert call_reference.status_code == 409
    assert call_reference.json()["error"]["details"]["used_by"] == [
        "BGP neighbor 192.0.2.1 · ipv4-unicast · export",
        "Route-map LOCAL-PREF rule 10 call",
    ]

    unused = await client.delete(f"{base}/LOCAL-PREF", headers=headers)
    assert unused.status_code == 204

    outbound = await client.get(f"{base}/BGP-OUT", headers=headers)
    assert outbound.status_code == 200
    assert outbound.json()["used_by"] == ["BGP neighbor 192.0.2.1 · ipv4-unicast · export"]


async def test_route_map_rbac(client, admin_token, operator_token, viewer_token) -> None:
    router_id = await _router(client, admin_token)
    base = f"/api/v1/routers/{router_id}/route-maps"
    viewer_headers = auth_headers(viewer_token)
    operator_headers = auth_headers(operator_token)

    assert (await client.get(base, headers=viewer_headers)).status_code == 200
    assert (await client.get(f"{base}/BGP-IN", headers=viewer_headers)).status_code == 200

    viewer_requests = [
        await client.post(base, headers=viewer_headers, json={"name": "VIEWER-MAP"}),
        await client.put(f"{base}/BGP-IN", headers=viewer_headers, json={"description": "x"}),
        await client.delete(f"{base}/LOCAL-PREF", headers=viewer_headers),
        await client.post(
            f"{base}/LOCAL-PREF/rules",
            headers=viewer_headers,
            json=copy.deepcopy(RULE_BODY),
        ),
        await client.put(
            f"{base}/LOCAL-PREF/rules/10",
            headers=viewer_headers,
            json=copy.deepcopy(RULE_UPDATE),
        ),
        await client.delete(f"{base}/LOCAL-PREF/rules/10", headers=viewer_headers),
    ]
    for response in viewer_requests:
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "forbidden"

    created = await client.post(
        base, headers=operator_headers, json={"name": "OP-MAP", "description": "Operator"}
    )
    assert created.status_code == 201, created.text
    updated = await client.put(
        f"{base}/OP-MAP", headers=operator_headers, json={"description": "Updated"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "Updated"

    rule = await client.post(
        f"{base}/OP-MAP/rules",
        headers=operator_headers,
        json=copy.deepcopy(RULE_BODY),
    )
    assert rule.status_code == 200, rule.text
    replacement = await client.put(
        f"{base}/OP-MAP/rules/10",
        headers=operator_headers,
        json=copy.deepcopy(RULE_UPDATE),
    )
    assert replacement.status_code == 200, replacement.text
    removed = await client.delete(f"{base}/OP-MAP/rules/10", headers=operator_headers)
    assert removed.status_code == 200, removed.text
    deleted = await client.delete(f"{base}/OP-MAP", headers=operator_headers)
    assert deleted.status_code == 204


async def test_route_map_audit_entries(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/route-maps"

    await _create_map(client, admin_token, router_id, "AUD-MAP")
    await client.put(f"{base}/AUD-MAP", headers=headers, json={"description": "Audited"})
    await client.post(f"{base}/AUD-MAP/rules", headers=headers, json=copy.deepcopy(RULE_BODY))
    await client.put(
        f"{base}/AUD-MAP/rules/10",
        headers=headers,
        json=copy.deepcopy(RULE_UPDATE),
    )
    await client.delete(f"{base}/AUD-MAP/rules/10", headers=headers)
    await client.delete(f"{base}/AUD-MAP", headers=headers)

    response = await client.get("/api/v1/audit", headers=headers, params={"limit": 50})
    assert response.status_code == 200, response.text
    events = [item for item in response.json()["items"] if item["action"].startswith("route_map.")]

    actions = [event["action"] for event in events]
    assert len(actions) == 6
    assert sorted(actions) == sorted(
        [
            "route_map.create",
            "route_map.update",
            "route_map.delete",
            "route_map.rule.create",
            "route_map.rule.update",
            "route_map.rule.delete",
        ]
    )
    for event in events:
        assert event["status"] == "success"
        assert event["actor_username"] == "admin"
        assert event["router_name"] == "edge-mock"
        assert event["request_id"]

    by_action = {event["action"]: event for event in events}
    assert by_action["route_map.create"]["resource_type"] == "route_map"
    assert by_action["route_map.create"]["resource_id"] == "AUD-MAP"
    assert by_action["route_map.create"]["details"] == {
        "name": "AUD-MAP",
        "description": "AUD-MAP map",
    }
    assert by_action["route_map.update"]["details"] == {
        "name": "AUD-MAP",
        "description": "Audited",
    }
    rule_create = by_action["route_map.rule.create"]
    assert rule_create["resource_type"] == "route_map_rule"
    assert rule_create["resource_id"] == "AUD-MAP:10"
    assert rule_create["details"]["name"] == "AUD-MAP"
    assert rule_create["details"]["number"] == 10
    assert rule_create["details"]["action"] == "permit"
    assert rule_create["details"]["match"]["ipv4_prefix_list"] == "TRANSIT-IN"
    assert rule_create["details"]["set"]["community_values"] == [
        "64512:100",
        "no-export",
    ]
    assert "password" not in response.text
    assert by_action["route_map.rule.delete"]["details"] == {"name": "AUD-MAP", "number": 10}
    assert by_action["route_map.delete"]["details"] == {"name": "AUD-MAP"}


async def test_bgp_address_family_route_map_fields(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    bgp = f"/api/v1/routers/{router_id}/bgp"
    route_maps = f"/api/v1/routers/{router_id}/route-maps"

    config = await client.get(bgp, headers=headers)
    transit = next(item for item in config.json()["neighbors"] if item["address"] == "192.0.2.1")
    assert transit["address_families"]["ipv4-unicast"]["route_map_import"] == "BGP-IN"
    assert transit["address_families"]["ipv4-unicast"]["route_map_export"] == "BGP-OUT"

    created = await client.post(
        f"{bgp}/neighbors",
        headers=headers,
        json={
            "address": "203.0.113.50",
            "remote_as": 65050,
            "description": "Route-map peer",
            "address_families": {
                "ipv4-unicast": {
                    "next_hop_self": True,
                    "route_map_import": "BGP-IN",
                    "route_map_export": "BGP-OUT",
                }
            },
        },
    )
    assert created.status_code == 200, created.text
    neighbor = next(
        item for item in created.json()["neighbors"] if item["address"] == "203.0.113.50"
    )
    af = neighbor["address_families"]["ipv4-unicast"]
    assert af["route_map_import"] == "BGP-IN"
    assert af["route_map_export"] == "BGP-OUT"

    # A partial neighbor update without address_families leaves them untouched.
    patched = await client.patch(
        f"{bgp}/neighbors/203.0.113.50",
        headers=headers,
        json={"description": "Renamed"},
    )
    assert patched.status_code == 200, patched.text
    neighbor = next(
        item for item in patched.json()["neighbors"] if item["address"] == "203.0.113.50"
    )
    assert neighbor["address_families"]["ipv4-unicast"]["route_map_import"] == "BGP-IN"
    assert neighbor["address_families"]["ipv4-unicast"]["route_map_export"] == "BGP-OUT"

    # Included address-family settings preserve the names.
    included = await client.patch(
        f"{bgp}/neighbors/203.0.113.50",
        headers=headers,
        json={
            "address_families": {
                "ipv4-unicast": {
                    "next_hop_self": True,
                    "route_map_import": "BGP-IN",
                    "route_map_export": "BGP-OUT",
                }
            }
        },
    )
    assert included.status_code == 200, included.text
    af = next(item for item in included.json()["neighbors"] if item["address"] == "203.0.113.50")[
        "address_families"
    ]["ipv4-unicast"]
    assert af["route_map_import"] == "BGP-IN"
    assert af["route_map_export"] == "BGP-OUT"

    # Null values clear the bindings.
    cleared = await client.patch(
        f"{bgp}/neighbors/203.0.113.50",
        headers=headers,
        json={"address_families": {"ipv4-unicast": {"next_hop_self": True}}},
    )
    assert cleared.status_code == 200, cleared.text
    af = next(item for item in cleared.json()["neighbors"] if item["address"] == "203.0.113.50")[
        "address_families"
    ]["ipv4-unicast"]
    assert af["route_map_import"] is None
    assert af["route_map_export"] is None

    invalid = await client.patch(
        f"{bgp}/neighbors/203.0.113.50",
        headers=headers,
        json={"address_families": {"ipv4-unicast": {"route_map_import": "bad name"}}},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"

    group = await client.post(
        f"{bgp}/peer-groups",
        headers=headers,
        json={
            "name": "route-map-group",
            "remote_as": 65060,
            "address_families": {
                "ipv6-unicast": {
                    "route_map_import": "BGP-IN",
                    "route_map_export": "BGP-OUT",
                }
            },
        },
    )
    assert group.status_code == 200, group.text
    peer_group = next(
        item for item in group.json()["peer_groups"] if item["name"] == "route-map-group"
    )
    assert peer_group["address_families"]["ipv6-unicast"]["route_map_import"] == "BGP-IN"
    assert peer_group["address_families"]["ipv6-unicast"]["route_map_export"] == "BGP-OUT"

    # Usage is derived from the live BGP config, including the new bindings.
    used_by = (await client.get(f"{route_maps}/BGP-IN", headers=headers)).json()["used_by"]
    assert "BGP neighbor 203.0.113.50 · ipv4-unicast · import" not in used_by
    # The binding was cleared above, so only the original neighbor and the new
    # peer group (IPv6) reference BGP-IN.
    assert ("BGP peer-group route-map-group · ipv6-unicast · import") in used_by
