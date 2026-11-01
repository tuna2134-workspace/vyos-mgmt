"""End-to-end service tests against the in-memory VyOS emulator."""

from __future__ import annotations

import uuid

import pytest

from vyos_mgmt.db.models import Router
from vyos_mgmt.schemas.route_map import (
    RouteMapCreate,
    RouteMapMatch,
    RouteMapRuleCreate,
    RouteMapRuleUpdate,
    RouteMapSet,
    RouteMapUpdate,
)
from vyos_mgmt.services.route_map_service import (
    ROUTE_MAP_ROOT,
    RouteMapExistsError,
    RouteMapInUseError,
    RouteMapNotFoundError,
    RouteMapRuleExistsError,
    RouteMapRuleNotFoundError,
    RouteMapService,
    RouteMapValidationError,
)
from vyos_mgmt.services.vyos.base import ConfigOp, DeviceTarget
from vyos_mgmt.services.vyos.mock_driver import MockDriver


def make_target() -> DeviceTarget:
    return DeviceTarget(
        id=uuid.uuid4(),
        name="mock-route-maps",
        host="127.0.0.1",
        port=443,
        protocol="https",
        api_key="",
        verify_tls=False,
        driver="mock",
        timeout=1,
    )


async def make_service() -> tuple[RouteMapService, MockDriver]:
    target = make_target()
    driver = MockDriver(target)
    return RouteMapService(driver, Router(id=target.id, name="mock-route-maps")), driver


async def test_list_and_get_seeded_route_maps() -> None:
    service, _driver = await make_service()

    result = await service.list()
    assert [item.name for item in result.items] == [
        "BGP-IN",
        "BGP-OUT",
        "LOCAL-PREF",
        "OSPF-OUT",
    ]
    assert result.total == 4

    bgp_in = result.items[0]
    assert bgp_in.in_use is True
    assert bgp_in.used_by == ["BGP neighbor 192.0.2.1 · ipv4-unicast · import"]
    assert [rule.number for rule in bgp_in.rules] == [10, 20]

    bgp_out = result.items[1]
    assert bgp_out.in_use is True
    assert bgp_out.used_by == [
        "BGP neighbor 192.0.2.1 · ipv4-unicast · export",
        "Route-map LOCAL-PREF rule 10 call",
    ]

    local_pref = result.items[2]
    assert local_pref.in_use is False
    assert local_pref.used_by == []

    fetched = await service.get("BGP-IN")
    assert fetched.description == "Inbound filtering for transit"
    rule = fetched.rules[0]
    assert rule.action == "permit"
    assert rule.match.ipv4_prefix_list == "TRANSIT-IN"
    assert rule.match.community_list == "CUSTOMER-COMM"
    assert rule.match.community_exact_match is False
    assert rule.match.origin == "igp"
    assert rule.match.protocol == "bgp"
    assert rule.match.rpki == "valid"
    assert rule.set.local_preference == 200
    assert rule.set.metric == "+50"
    assert rule.set.community_action == "add"
    assert rule.set.community_values == ["64512:100"]
    assert rule.on_match == "next"


async def test_map_crud_against_mock_driver() -> None:
    service, _driver = await make_service()

    created = await service.create(RouteMapCreate(name="NEW-MAP", description="Test map"))
    assert created.name == "NEW-MAP"
    assert created.description == "Test map"
    assert created.rules == []
    assert created.in_use is False

    with pytest.raises(RouteMapExistsError):
        await service.create(RouteMapCreate(name="NEW-MAP"))

    updated = await service.update("NEW-MAP", RouteMapUpdate(description="Changed"))
    assert updated.description == "Changed"

    cleared = await service.update("NEW-MAP", RouteMapUpdate(description=None))
    assert cleared.description is None

    await service.delete("NEW-MAP")
    with pytest.raises(RouteMapNotFoundError):
        await service.get("NEW-MAP")
    with pytest.raises(RouteMapNotFoundError):
        await service.delete("NEW-MAP")
    with pytest.raises(RouteMapNotFoundError):
        await service.update("NEW-MAP", RouteMapUpdate(description="x"))


async def test_rule_crud_against_mock_driver() -> None:
    service, _driver = await make_service()
    await service.create(RouteMapCreate(name="RULE-MAP"))

    payload = RouteMapRuleCreate(
        number=10,
        action="permit",
        description="Allow",
        match=RouteMapMatch(
            ipv4_prefix_list="TRANSIT-IN",
            community_list="CUSTOMER-COMM",
            community_exact_match=True,
            metric=100,
            origin="igp",
            ip_nexthop="192.0.2.9",
            ipv6_nexthop="2001:db8::9",
        ),
        set=RouteMapSet(
            local_preference=200,
            metric="+50",
            as_path_prepend=[64512, 64513],
            community_action="add",
            community_values=["64512:100", "no-export"],
            ip_next_hop="192.0.2.1",
        ),
        on_match="goto",
        goto_rule=20,
        call="BGP-OUT",
        continue_rule=30,
    )
    created = await service.create_rule("RULE-MAP", payload)
    assert [rule.number for rule in created.rules] == [10]
    rule = created.rules[0]
    assert rule.match.ipv4_prefix_list == "TRANSIT-IN"
    assert rule.match.community_exact_match is True
    assert rule.match.metric == 100
    assert rule.match.ip_nexthop == "192.0.2.9"
    assert rule.match.ipv6_nexthop == "2001:db8::9"
    assert rule.set.as_path_prepend == [64512, 64513]
    assert rule.set.community_values == ["64512:100", "no-export"]
    assert rule.on_match == "goto"
    assert rule.goto_rule == 20
    assert rule.call == "BGP-OUT"
    assert rule.continue_rule == 30

    with pytest.raises(RouteMapRuleExistsError):
        await service.create_rule("RULE-MAP", payload)

    replacement = RouteMapRuleUpdate(
        action="deny",
        description=None,
        match=RouteMapMatch(ipv6_prefix_list="TRANSIT-V6"),
        set=RouteMapSet(metric="rtt"),
        on_match=None,
        call=None,
        continue_rule=None,
    )
    updated = await service.update_rule("RULE-MAP", 10, replacement)
    rule = updated.rules[0]
    assert rule.action == "deny"
    assert rule.description is None
    assert rule.match.ipv4_prefix_list is None
    assert rule.match.ipv6_prefix_list == "TRANSIT-V6"
    assert rule.set.metric == "rtt"
    assert rule.set.as_path_prepend == []
    assert rule.set.community_action is None
    assert rule.on_match is None
    assert rule.call is None

    emptied = await service.delete_rule("RULE-MAP", 10)
    assert emptied.rules == []
    with pytest.raises(RouteMapRuleNotFoundError):
        await service.delete_rule("RULE-MAP", 10)
    with pytest.raises(RouteMapRuleNotFoundError):
        await service.update_rule("RULE-MAP", 10, replacement)


async def test_rule_update_preserves_unknown_device_fields() -> None:
    service, driver = await make_service()
    rule_base = [*ROUTE_MAP_ROOT, "BGP-IN", "rule", "10"]
    await driver.apply(
        [
            ConfigOp("set", [*rule_base, "match", "vendor-extension"]),
            ConfigOp("set", [*rule_base, "set", "vendor-flag"]),
            ConfigOp("set", [*rule_base, "vendor-rule-flag"]),
            ConfigOp("set", [*rule_base, "set", "vendor-value", "keep-me"]),
        ]
    )

    replacement = RouteMapRuleUpdate(
        action="permit",
        description=None,
        match=RouteMapMatch(ipv4_prefix_list="TRANSIT-BOGONS"),
        set=RouteMapSet(local_preference=300),
        on_match=None,
        call=None,
        continue_rule=None,
    )
    updated = await service.update_rule("BGP-IN", 10, replacement)
    rule = updated.rules[0]
    assert rule.description is None
    assert rule.match.ipv4_prefix_list == "TRANSIT-BOGONS"
    assert rule.match.community_list is None
    assert rule.set.local_preference == 300
    assert rule.set.metric is None
    assert rule.set.community_action is None
    assert rule.on_match is None

    raw = await driver.get_config(ROUTE_MAP_ROOT)
    raw_rule = raw["BGP-IN"]["rule"]["10"]
    assert "vendor-extension" in raw_rule["match"]
    assert "vendor-flag" in raw_rule["set"]
    assert "vendor-rule-flag" in raw_rule
    assert raw_rule["set"]["vendor-value"] == {"keep-me": {}}
    assert raw_rule["match"]["ip"]["address"]["prefix-list"] == "TRANSIT-BOGONS"
    assert "community-list" not in raw_rule["match"]["community"]
    assert "on-match" not in raw_rule


async def test_delete_refuses_in_use_route_maps() -> None:
    service, _driver = await make_service()

    with pytest.raises(RouteMapInUseError) as inbound:
        await service.delete("BGP-IN")
    assert inbound.value.used_by == ["BGP neighbor 192.0.2.1 · ipv4-unicast · import"]

    with pytest.raises(RouteMapInUseError) as outbound:
        await service.delete("BGP-OUT")
    assert outbound.value.used_by == [
        "BGP neighbor 192.0.2.1 · ipv4-unicast · export",
        "Route-map LOCAL-PREF rule 10 call",
    ]

    await service.delete("LOCAL-PREF")
    assert [item.name for item in (await service.list()).items] == [
        "BGP-IN",
        "BGP-OUT",
        "OSPF-OUT",
    ]


async def test_missing_maps_and_rules_raise_domain_errors() -> None:
    service, _driver = await make_service()
    payload = RouteMapRuleCreate(number=10, action="permit")
    replacement = RouteMapRuleUpdate(action="permit")

    with pytest.raises(RouteMapNotFoundError):
        await service.create_rule("MISSING", payload)
    with pytest.raises(RouteMapNotFoundError):
        await service.update_rule("MISSING", 10, replacement)
    with pytest.raises(RouteMapNotFoundError):
        await service.delete_rule("MISSING", 10)
    with pytest.raises(RouteMapRuleNotFoundError):
        await service.update_rule("BGP-IN", 999, replacement)
    with pytest.raises(RouteMapRuleNotFoundError):
        await service.delete_rule("BGP-IN", 999)


async def test_update_rule_validates_goto_against_path_number() -> None:
    service, _driver = await make_service()
    replacement = RouteMapRuleUpdate(action="permit", on_match="goto", goto_rule=10)
    with pytest.raises(RouteMapValidationError) as excinfo:
        await service.update_rule("BGP-IN", 10, replacement)
    assert excinfo.value.field == "goto_rule"


async def test_empty_policy_tree_is_treated_as_no_route_maps() -> None:
    service, driver = await make_service()
    await driver.apply([ConfigOp("delete", ["policy"])])
    result = await service.list()
    assert result.items == []
    assert result.total == 0


class _CountingDriver(MockDriver):
    def __init__(self, target: DeviceTarget) -> None:
        super().__init__(target)
        self.apply_calls = 0

    async def apply(self, ops: list[ConfigOp]) -> None:
        self.apply_calls += 1
        await super().apply(ops)


async def test_rule_mutations_are_single_atomic_batches() -> None:
    target = make_target()
    driver = _CountingDriver(target)
    service = RouteMapService(driver, Router(id=target.id, name="mock-route-maps"))
    await service.create(RouteMapCreate(name="ATOMIC"))

    driver.apply_calls = 0
    await service.create_rule("ATOMIC", RouteMapRuleCreate(number=10, action="permit"))
    assert driver.apply_calls == 1

    driver.apply_calls = 0
    await service.update_rule(
        "ATOMIC",
        10,
        RouteMapRuleUpdate(action="deny", on_match="goto", goto_rule=20),
    )
    assert driver.apply_calls == 1

    # A no-op update does not touch the device at all.
    driver.apply_calls = 0
    await service.update_rule(
        "ATOMIC",
        10,
        RouteMapRuleUpdate(action="deny", on_match="goto", goto_rule=20),
    )
    assert driver.apply_calls == 0

    driver.apply_calls = 0
    await service.delete_rule("ATOMIC", 10)
    assert driver.apply_calls == 1
