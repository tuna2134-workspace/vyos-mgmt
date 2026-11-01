"""Integration tests for the prefix-list API and its route-map integration."""

from __future__ import annotations

import copy
import uuid

from tests.helpers import auth_headers, create_mock_router

PREFIX_LIST_FIELDS = {"name", "family", "description", "rules", "in_use", "used_by"}
RULE_FIELDS = {"number", "action", "prefix", "ge", "le", "description"}

RULE_CREATE = {
    "number": 10,
    "action": "permit",
    "prefix": "203.0.113.0/24",
    "ge": 24,
    "le": 32,
    "description": "Customer /24s",
}


async def _router(client, token: str) -> str:
    device = await create_mock_router(client, token)
    return device["id"]


async def _create_list(
    client,
    token: str,
    router_id: str,
    *,
    name: str = "NEW-LIST",
    family: str = "ipv4",
    description: str | None = "New list",
) -> dict:
    response = await client.post(
        f"/api/v1/routers/{router_id}/prefix-lists",
        headers=auth_headers(token),
        json={"name": name, "family": family, "description": description},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_list_and_get_prefix_lists_match_contract(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/prefix-lists"

    response = await client.get(base, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "total"}
    assert body["total"] == 3
    assert [(item["family"], item["name"]) for item in body["items"]] == [
        ("ipv4", "TRANSIT-BOGONS"),
        ("ipv4", "TRANSIT-IN"),
        ("ipv6", "TRANSIT-V6"),
    ]
    for item in body["items"]:
        assert set(item) == PREFIX_LIST_FIELDS
        for rule in item["rules"]:
            assert set(rule) == RULE_FIELDS

    transit_in = body["items"][1]
    assert transit_in["description"] == "Transit customer prefixes"
    assert transit_in["in_use"] is True
    assert transit_in["used_by"] == ["Route-map BGP-IN · rule 10 · IPv4 prefix-list"]
    assert transit_in["rules"] == [
        {
            "number": 10,
            "action": "permit",
            "prefix": "203.0.113.0/24",
            "ge": 24,
            "le": 32,
            "description": "Customer /24s",
        }
    ]

    fetched = await client.get(f"{base}/ipv4/TRANSIT-IN", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == transit_in

    ipv4 = await client.get(f"{base}?family=ipv4", headers=headers)
    assert ipv4.status_code == 200, ipv4.text
    assert ipv4.json()["total"] == 2
    assert {item["family"] for item in ipv4.json()["items"]} == {"ipv4"}

    ipv6 = await client.get(f"{base}?family=ipv6", headers=headers)
    assert ipv6.status_code == 200, ipv6.text
    assert [item["name"] for item in ipv6.json()["items"]] == ["TRANSIT-V6"]

    bad_filter = await client.get(f"{base}?family=ipv5", headers=headers)
    assert bad_filter.status_code == 422
    assert bad_filter.json()["error"]["code"] == "validation_error"

    missing = await client.get(f"{base}/ipv4/DOES-NOT-EXIST", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "prefix_list_not_found"

    bad_family = await client.get(f"{base}/ipv5/TRANSIT-IN", headers=headers)
    assert bad_family.status_code == 422
    assert bad_family.json()["error"]["code"] == "validation_error"

    wrong_family = await client.get(f"{base}/ipv6/TRANSIT-IN", headers=headers)
    assert wrong_family.status_code == 404
    assert wrong_family.json()["error"]["code"] == "prefix_list_not_found"

    unknown_router = await client.get(
        f"/api/v1/routers/{uuid.uuid4()}/prefix-lists", headers=headers
    )
    assert unknown_router.status_code == 404
    assert unknown_router.json()["error"]["code"] == "router_not_found"


async def test_prefix_list_crud(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/prefix-lists"

    created = await _create_list(client, admin_token, router_id, name="NEW-LIST")
    assert set(created) == PREFIX_LIST_FIELDS
    assert created["name"] == "NEW-LIST"
    assert created["family"] == "ipv4"
    assert created["description"] == "New list"
    assert created["rules"] == []
    assert created["in_use"] is False
    assert created["used_by"] == []

    duplicate = await client.post(
        base, headers=headers, json={"name": "NEW-LIST", "family": "ipv4"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "prefix_list_exists"

    # The same name is allowed in the other family.
    ipv6 = await _create_list(
        client, admin_token, router_id, name="NEW-LIST", family="ipv6", description=None
    )
    assert ipv6["family"] == "ipv6"
    assert ipv6["description"] is None

    for payload in (
        {"name": "", "family": "ipv4"},
        {"name": "-bad", "family": "ipv4"},
        {"name": "bad name", "family": "ipv4"},
        {"name": "A" * 129, "family": "ipv4"},
        {"name": "VALID", "family": "ipv5"},
    ):
        invalid = await client.post(base, headers=headers, json=payload)
        assert invalid.status_code == 422, invalid.text
        assert invalid.json()["error"]["code"] == "validation_error"

    updated = await client.put(
        f"{base}/ipv4/NEW-LIST", headers=headers, json={"description": "Changed"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "Changed"

    cleared = await client.put(f"{base}/ipv4/NEW-LIST", headers=headers, json={"description": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["description"] is None

    missing_update = await client.put(
        f"{base}/ipv4/MISSING", headers=headers, json={"description": "x"}
    )
    assert missing_update.status_code == 404
    assert missing_update.json()["error"]["code"] == "prefix_list_not_found"

    deleted = await client.delete(f"{base}/ipv4/NEW-LIST", headers=headers)
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert (await client.get(f"{base}/ipv4/NEW-LIST", headers=headers)).status_code == 404
    assert (await client.delete(f"{base}/ipv4/NEW-LIST", headers=headers)).status_code == 404

    # Deleting the IPv4 object did not touch the IPv6 object with the same name.
    still_there = await client.get(f"{base}/ipv6/NEW-LIST", headers=headers)
    assert still_there.status_code == 200
    assert still_there.json()["family"] == "ipv6"


async def test_rule_crud_and_duplicate_conflicts(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/prefix-lists"
    await _create_list(client, admin_token, router_id, name="RULES")

    created = await client.post(
        f"{base}/ipv4/RULES/rules", headers=headers, json=copy.deepcopy(RULE_CREATE)
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert [rule["number"] for rule in body["rules"]] == [10]
    rule = body["rules"][0]
    assert rule["action"] == "permit"
    assert rule["prefix"] == "203.0.113.0/24"
    assert rule["ge"] == 24
    assert rule["le"] == 32
    assert rule["description"] == "Customer /24s"

    duplicate_number = await client.post(
        f"{base}/ipv4/RULES/rules", headers=headers, json=copy.deepcopy(RULE_CREATE)
    )
    assert duplicate_number.status_code == 409
    assert duplicate_number.json()["error"]["code"] == "prefix_list_rule_exists"

    semantic_duplicate = copy.deepcopy(RULE_CREATE)
    semantic_duplicate["number"] = 20
    semantic_duplicate["description"] = "Different description"
    response = await client.post(
        f"{base}/ipv4/RULES/rules", headers=headers, json=semantic_duplicate
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "prefix_list_rule_duplicate"

    # IPv6 rules use the same body shape; the prefix is canonicalised.
    await _create_list(client, admin_token, router_id, name="V6-RULES", family="ipv6")
    ipv6_rule = await client.post(
        f"{base}/ipv6/V6-RULES/rules",
        headers=headers,
        json={
            "number": 10,
            "action": "permit",
            "prefix": "2001:DB8:0::/32",
            "ge": 32,
            "le": 128,
        },
    )
    assert ipv6_rule.status_code == 200, ipv6_rule.text
    assert ipv6_rule.json()["rules"][0]["prefix"] == "2001:db8::/32"
    assert ipv6_rule.json()["rules"][0]["le"] == 128

    replacement = {
        "number": 999,  # stale body number: the path number wins
        "action": "deny",
        "prefix": "198.51.100.0/24",
        "ge": None,
        "le": None,
        "description": None,
    }
    updated = await client.put(f"{base}/ipv4/RULES/rules/10", headers=headers, json=replacement)
    assert updated.status_code == 200, updated.text
    rule = updated.json()["rules"][0]
    assert rule["number"] == 10
    assert rule["action"] == "deny"
    assert rule["prefix"] == "198.51.100.0/24"
    assert rule["ge"] is None
    assert rule["le"] is None
    assert rule["description"] is None

    missing_rule = await client.put(
        f"{base}/ipv4/RULES/rules/999", headers=headers, json=replacement
    )
    assert missing_rule.status_code == 404
    assert missing_rule.json()["error"]["code"] == "prefix_list_rule_not_found"

    bad_bounds = await client.put(
        f"{base}/ipv4/RULES/rules/10",
        headers=headers,
        json={"action": "permit", "prefix": "10.0.0.0/8", "ge": 7},
    )
    assert bad_bounds.status_code == 422
    assert bad_bounds.json()["error"]["code"] == "validation_error"

    wrong_family = await client.put(
        f"{base}/ipv4/RULES/rules/10",
        headers=headers,
        json={"action": "permit", "prefix": "2001:db8::/32"},
    )
    assert wrong_family.status_code == 422
    assert wrong_family.json()["error"]["code"] == "validation_error"
    assert wrong_family.json()["error"]["details"][0]["loc"] == ["body", "prefix"]

    deleted = await client.delete(f"{base}/ipv4/RULES/rules/10", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["rules"] == []
    missing_delete = await client.delete(f"{base}/ipv4/RULES/rules/10", headers=headers)
    assert missing_delete.status_code == 404
    assert missing_delete.json()["error"]["code"] == "prefix_list_rule_not_found"

    no_list = await client.post(
        f"{base}/ipv4/MISSING/rules", headers=headers, json=copy.deepcopy(RULE_CREATE)
    )
    assert no_list.status_code == 404
    assert no_list.json()["error"]["code"] == "prefix_list_not_found"


async def test_delete_in_use_prefix_list_returns_conflict(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/prefix-lists"

    in_use = await client.delete(f"{base}/ipv4/TRANSIT-IN", headers=headers)
    assert in_use.status_code == 409
    error = in_use.json()["error"]
    assert error["code"] == "prefix_list_in_use"
    assert error["details"] == {"used_by": ["Route-map BGP-IN · rule 10 · IPv4 prefix-list"]}

    bogons = await client.delete(f"{base}/ipv4/TRANSIT-BOGONS", headers=headers)
    assert bogons.status_code == 409
    assert bogons.json()["error"]["details"]["used_by"] == [
        "Route-map BGP-IN · rule 20 · IPv4 prefix-list"
    ]

    unused = await client.delete(f"{base}/ipv6/TRANSIT-V6", headers=headers)
    assert unused.status_code == 204

    missing = await client.delete(f"{base}/ipv4/MISSING", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "prefix_list_not_found"


async def test_prefix_list_rbac(client, admin_token, operator_token, viewer_token) -> None:
    router_id = await _router(client, admin_token)
    base = f"/api/v1/routers/{router_id}/prefix-lists"
    viewer_headers = auth_headers(viewer_token)
    operator_headers = auth_headers(operator_token)

    assert (await client.get(base, headers=viewer_headers)).status_code == 200
    assert (await client.get(f"{base}/ipv4/TRANSIT-IN", headers=viewer_headers)).status_code == 200

    viewer_requests = [
        await client.post(base, headers=viewer_headers, json={"name": "VIEWER", "family": "ipv4"}),
        await client.put(
            f"{base}/ipv4/TRANSIT-IN", headers=viewer_headers, json={"description": "x"}
        ),
        await client.delete(f"{base}/ipv6/TRANSIT-V6", headers=viewer_headers),
        await client.post(
            f"{base}/ipv4/TRANSIT-IN/rules",
            headers=viewer_headers,
            json=copy.deepcopy(RULE_CREATE),
        ),
        await client.put(
            f"{base}/ipv4/TRANSIT-IN/rules/10",
            headers=viewer_headers,
            json={"action": "deny", "prefix": "203.0.113.0/24"},
        ),
        await client.delete(f"{base}/ipv4/TRANSIT-IN/rules/10", headers=viewer_headers),
    ]
    for response in viewer_requests:
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "forbidden"

    created = await client.post(
        base,
        headers=operator_headers,
        json={"name": "OP-LIST", "family": "ipv4", "description": "Operator"},
    )
    assert created.status_code == 201, created.text

    updated = await client.put(
        f"{base}/ipv4/OP-LIST", headers=operator_headers, json={"description": "Updated"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "Updated"

    rule = await client.post(
        f"{base}/ipv4/OP-LIST/rules",
        headers=operator_headers,
        json=copy.deepcopy(RULE_CREATE),
    )
    assert rule.status_code == 200, rule.text

    replacement = await client.put(
        f"{base}/ipv4/OP-LIST/rules/10",
        headers=operator_headers,
        json={"action": "deny", "prefix": "198.51.100.0/24"},
    )
    assert replacement.status_code == 200, replacement.text

    removed = await client.delete(f"{base}/ipv4/OP-LIST/rules/10", headers=operator_headers)
    assert removed.status_code == 200, removed.text

    deleted = await client.delete(f"{base}/ipv4/OP-LIST", headers=operator_headers)
    assert deleted.status_code == 204


async def test_prefix_list_audit_entries(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    base = f"/api/v1/routers/{router_id}/prefix-lists"

    await _create_list(client, admin_token, router_id, name="AUD-LIST")
    await client.put(f"{base}/ipv4/AUD-LIST", headers=headers, json={"description": "Audited"})
    await client.post(
        f"{base}/ipv4/AUD-LIST/rules", headers=headers, json=copy.deepcopy(RULE_CREATE)
    )
    await client.put(
        f"{base}/ipv4/AUD-LIST/rules/10",
        headers=headers,
        json={"action": "deny", "prefix": "198.51.100.0/24"},
    )
    await client.delete(f"{base}/ipv4/AUD-LIST/rules/10", headers=headers)
    await client.delete(f"{base}/ipv4/AUD-LIST", headers=headers)

    response = await client.get("/api/v1/audit", headers=headers, params={"limit": 50})
    assert response.status_code == 200, response.text
    events = [
        item for item in response.json()["items"] if item["action"].startswith("prefix_list.")
    ]

    actions = [event["action"] for event in events]
    assert len(actions) == 6
    assert sorted(actions) == sorted(
        [
            "prefix_list.create",
            "prefix_list.update",
            "prefix_list.delete",
            "prefix_list.rule.create",
            "prefix_list.rule.update",
            "prefix_list.rule.delete",
        ]
    )
    for event in events:
        assert event["status"] == "success"
        assert event["actor_username"] == "admin"
        assert event["router_name"] == "edge-mock"
        assert event["request_id"]

    by_action = {event["action"]: event for event in events}
    assert by_action["prefix_list.create"]["resource_type"] == "prefix_list"
    assert by_action["prefix_list.create"]["resource_id"] == "ipv4:AUD-LIST"
    assert by_action["prefix_list.create"]["details"] == {
        "name": "AUD-LIST",
        "family": "ipv4",
        "description": "New list",
    }
    assert by_action["prefix_list.update"]["details"] == {
        "name": "AUD-LIST",
        "family": "ipv4",
        "description": "Audited",
    }
    assert by_action["prefix_list.rule.create"]["resource_type"] == "prefix_list_rule"
    assert by_action["prefix_list.rule.create"]["resource_id"] == "ipv4:AUD-LIST:10"
    rule_create = by_action["prefix_list.rule.create"]["details"]
    assert rule_create == {
        "name": "AUD-LIST",
        "family": "ipv4",
        "number": 10,
        "action": "permit",
        "prefix": "203.0.113.0/24",
        "ge": 24,
        "le": 32,
        "description": "Customer /24s",
    }
    assert by_action["prefix_list.rule.delete"]["details"] == {
        "name": "AUD-LIST",
        "family": "ipv4",
        "number": 10,
    }
    assert by_action["prefix_list.delete"]["details"] == {
        "name": "AUD-LIST",
        "family": "ipv4",
    }
    assert "password" not in response.text


async def test_route_map_references_require_existing_prefix_lists(client, admin_token) -> None:
    router_id = await _router(client, admin_token)
    headers = auth_headers(admin_token)
    route_maps = f"/api/v1/routers/{router_id}/route-maps"
    prefix_lists = f"/api/v1/routers/{router_id}/prefix-lists"

    created = await client.post(route_maps, headers=headers, json={"name": "RM-INTEGRATION"})
    assert created.status_code == 201, created.text

    missing = await client.post(
        f"{route_maps}/RM-INTEGRATION/rules",
        headers=headers,
        json={
            "number": 10,
            "action": "permit",
            "match": {"ipv4_prefix_list": "MISSING"},
        },
    )
    assert missing.status_code == 422, missing.text
    error = missing.json()["error"]
    assert error["code"] == "prefix_list_not_found"
    assert "MISSING" in error["message"]
    assert "IPv4" in error["message"]
    assert error["details"][0]["loc"] == ["body", "match.ipv4_prefix_list"]

    await _create_list(client, admin_token, router_id, name="V4-ONLY", family="ipv4")
    await _create_list(client, admin_token, router_id, name="V6-ONLY", family="ipv6")

    v4_rule = await client.post(
        f"{route_maps}/RM-INTEGRATION/rules",
        headers=headers,
        json={
            "number": 10,
            "action": "permit",
            "match": {"ipv4_prefix_list": "V4-ONLY"},
        },
    )
    assert v4_rule.status_code == 200, v4_rule.text
    rule = v4_rule.json()["rules"][0]
    assert rule["match"]["ipv4_prefix_list"] == "V4-ONLY"
    assert rule["match"]["ipv6_prefix_list"] is None

    # The new reference makes the prefix list in use for deletion purposes.
    referenced = await client.delete(f"{prefix_lists}/ipv4/V4-ONLY", headers=headers)
    assert referenced.status_code == 409
    assert referenced.json()["error"]["details"]["used_by"] == [
        "Route-map RM-INTEGRATION · rule 10 · IPv4 prefix-list"
    ]

    v6_rule = await client.put(
        f"{route_maps}/RM-INTEGRATION/rules/10",
        headers=headers,
        json={
            "action": "deny",
            "match": {"ipv6_prefix_list": "V6-ONLY"},
        },
    )
    assert v6_rule.status_code == 200, v6_rule.text
    rule = v6_rule.json()["rules"][0]
    assert rule["match"]["ipv4_prefix_list"] is None
    assert rule["match"]["ipv6_prefix_list"] == "V6-ONLY"

    referenced_v6 = await client.delete(f"{prefix_lists}/ipv6/V6-ONLY", headers=headers)
    assert referenced_v6.status_code == 409
    assert referenced_v6.json()["error"]["details"]["used_by"] == [
        "Route-map RM-INTEGRATION · rule 10 · IPv6 prefix-list"
    ]

    # Family scoping: a name that exists only in the other family is rejected.
    family_scoped_v4 = await client.post(
        f"{route_maps}/RM-INTEGRATION/rules",
        headers=headers,
        json={
            "number": 20,
            "action": "permit",
            "match": {"ipv4_prefix_list": "V6-ONLY"},
        },
    )
    assert family_scoped_v4.status_code == 422
    assert family_scoped_v4.json()["error"]["code"] == "prefix_list_not_found"

    family_scoped_v6 = await client.post(
        f"{route_maps}/RM-INTEGRATION/rules",
        headers=headers,
        json={
            "number": 30,
            "action": "permit",
            "match": {"ipv6_prefix_list": "V4-ONLY"},
        },
    )
    assert family_scoped_v6.status_code == 422
    assert family_scoped_v6.json()["error"]["code"] == "prefix_list_not_found"

    missing_on_update = await client.put(
        f"{route_maps}/RM-INTEGRATION/rules/10",
        headers=headers,
        json={
            "action": "permit",
            "match": {"ipv4_prefix_list": "MISSING-ON-UPDATE"},
        },
    )
    assert missing_on_update.status_code == 422
    assert missing_on_update.json()["error"]["code"] == "prefix_list_not_found"

    # Seeded route maps still work with the seeded prefix lists.
    seeded = await client.post(
        f"{route_maps}/BGP-IN/rules",
        headers=headers,
        json={
            "number": 30,
            "action": "permit",
            "match": {"ipv4_prefix_list": "TRANSIT-IN"},
        },
    )
    assert seeded.status_code == 200, seeded.text

    await client.delete(f"{route_maps}/RM-INTEGRATION/rules/10", headers=headers)
    assert (await client.delete(f"{prefix_lists}/ipv6/V6-ONLY", headers=headers)).status_code == 204
    assert (await client.delete(f"{prefix_lists}/ipv4/V4-ONLY", headers=headers)).status_code == 204
