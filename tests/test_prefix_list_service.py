"""Service tests for prefix lists against the in-memory VyOS emulator."""

from __future__ import annotations

import uuid

import pytest

from vyos_mgmt.db.models import Router
from vyos_mgmt.schemas.prefix_list import (
    PrefixListCreate,
    PrefixListRuleCreate,
    PrefixListRuleUpdate,
    PrefixListUpdate,
)
from vyos_mgmt.services.prefix_list_service import (
    PREFIX_LIST_ROOTS,
    PrefixListExistsError,
    PrefixListInUseError,
    PrefixListNotFoundError,
    PrefixListRuleDuplicateError,
    PrefixListRuleExistsError,
    PrefixListRuleNotFoundError,
    PrefixListService,
    PrefixListValidationError,
)
from vyos_mgmt.services.vyos.base import ConfigOp, DeviceTarget
from vyos_mgmt.services.vyos.mock_driver import MockDriver


def make_target() -> DeviceTarget:
    return DeviceTarget(
        id=uuid.uuid4(),
        name="mock-prefix-lists",
        host="127.0.0.1",
        port=443,
        protocol="https",
        api_key="",
        verify_tls=False,
        driver="mock",
        timeout=1,
    )


async def make_service() -> tuple[PrefixListService, MockDriver]:
    target = make_target()
    driver = MockDriver(target)
    return PrefixListService(driver, Router(id=target.id, name="mock-prefix-lists")), driver


async def test_list_and_get_seeded_prefix_lists() -> None:
    service, _driver = await make_service()

    result = await service.list()
    assert result.total == 3
    assert [item.name for item in result.items] == [
        "TRANSIT-BOGONS",
        "TRANSIT-IN",
        "TRANSIT-V6",
    ]

    by_name = {(item.family, item.name): item for item in result.items}
    transit_in = by_name[("ipv4", "TRANSIT-IN")]
    assert transit_in.description == "Transit customer prefixes"
    assert transit_in.in_use is True
    assert transit_in.used_by == ["Route-map BGP-IN · rule 10 · IPv4 prefix-list"]
    assert [rule.number for rule in transit_in.rules] == [10]
    rule = transit_in.rules[0]
    assert (rule.action, rule.prefix, rule.ge, rule.le) == (
        "permit",
        "203.0.113.0/24",
        24,
        32,
    )

    bogons = by_name[("ipv4", "TRANSIT-BOGONS")]
    assert [rule.number for rule in bogons.rules] == [10, 20, 30, 40]
    assert bogons.used_by == ["Route-map BGP-IN · rule 20 · IPv4 prefix-list"]

    transit_v6 = by_name[("ipv6", "TRANSIT-V6")]
    assert transit_v6.in_use is False
    assert transit_v6.used_by == []
    assert transit_v6.rules[0].prefix == "2001:db8:100::/48"

    assert [item.name for item in (await service.list("ipv4")).items] == [
        "TRANSIT-BOGONS",
        "TRANSIT-IN",
    ]
    assert [item.name for item in (await service.list("ipv6")).items] == ["TRANSIT-V6"]

    assert (await service.get("ipv4", "TRANSIT-IN")).name == "TRANSIT-IN"
    with pytest.raises(PrefixListNotFoundError):
        await service.get("ipv6", "TRANSIT-IN")
    with pytest.raises(PrefixListNotFoundError):
        await service.get("ipv4", "MISSING")


async def test_list_crud_is_family_scoped() -> None:
    service, _driver = await make_service()

    ipv4 = await service.create(PrefixListCreate(name="SHARED", family="ipv4", description="v4"))
    assert ipv4.name == "SHARED"
    assert ipv4.family == "ipv4"
    assert ipv4.description == "v4"
    assert ipv4.rules == []
    assert ipv4.in_use is False

    ipv6 = await service.create(PrefixListCreate(name="SHARED", family="ipv6", description="v6"))
    assert ipv6.family == "ipv6"
    assert ipv6.description == "v6"

    with pytest.raises(PrefixListExistsError):
        await service.create(PrefixListCreate(name="SHARED", family="ipv4"))

    names = [item.name for item in (await service.list("ipv4")).items]
    assert names == ["SHARED", "TRANSIT-BOGONS", "TRANSIT-IN"]

    updated = await service.update("ipv4", "SHARED", PrefixListUpdate(description="Changed"))
    assert updated.description == "Changed"
    cleared = await service.update("ipv4", "SHARED", PrefixListUpdate(description=None))
    assert cleared.description is None

    with pytest.raises(PrefixListNotFoundError):
        await service.update("ipv4", "MISSING", PrefixListUpdate(description="x"))

    await service.delete("ipv4", "SHARED")
    with pytest.raises(PrefixListNotFoundError):
        await service.get("ipv4", "SHARED")
    with pytest.raises(PrefixListNotFoundError):
        await service.delete("ipv4", "SHARED")
    # The IPv6 object with the same name is untouched.
    assert (await service.get("ipv6", "SHARED")).description == "v6"


async def test_rule_crud_and_duplicate_detection() -> None:
    service, _driver = await make_service()
    await service.create(PrefixListCreate(name="RULES", family="ipv4"))

    payload = PrefixListRuleCreate(
        number=10,
        action="permit",
        prefix="203.0.113.0/24",
        ge=24,
        le=32,
        description="Customer /24s",
    )
    created = await service.create_rule("ipv4", "RULES", payload)
    assert [rule.number for rule in created.rules] == [10]
    assert created.rules[0].description == "Customer /24s"

    with pytest.raises(PrefixListRuleExistsError):
        await service.create_rule("ipv4", "RULES", payload)

    # Same action/prefix/ge/le under another number is a semantic duplicate.
    duplicate = payload.model_copy(update={"number": 20, "description": "Different text"})
    with pytest.raises(PrefixListRuleDuplicateError):
        await service.create_rule("ipv4", "RULES", duplicate)

    # A description-only change keeps the signature and is not a duplicate.
    renamed = await service.update_rule(
        "ipv4",
        "RULES",
        10,
        PrefixListRuleUpdate(
            action="permit",
            prefix="203.0.113.0/24",
            ge=24,
            le=32,
            description="Renamed",
        ),
    )
    assert renamed.rules[0].description == "Renamed"

    # A genuinely different definition is accepted.
    other = await service.create_rule(
        "ipv4",
        "RULES",
        PrefixListRuleCreate(number=20, action="deny", prefix="0.0.0.0/0", le=32),
    )
    assert [rule.number for rule in other.rules] == [10, 20]

    replacement = PrefixListRuleUpdate(
        number=999,  # ignored: the path number is authoritative
        action="deny",
        prefix="198.51.100.0/24",
        ge=24,
        le=28,
        description=None,
    )
    updated = await service.update_rule("ipv4", "RULES", 10, replacement)
    rule = next(item for item in updated.rules if item.number == 10)
    assert rule.action == "deny"
    assert rule.prefix == "198.51.100.0/24"
    assert (rule.ge, rule.le) == (24, 28)
    assert rule.description is None

    # Updating rule 20 to rule 10's definition is rejected.
    with pytest.raises(PrefixListRuleDuplicateError):
        await service.update_rule(
            "ipv4",
            "RULES",
            20,
            PrefixListRuleUpdate(action="deny", prefix="198.51.100.0/24", ge=24, le=28),
        )

    removed = await service.delete_rule("ipv4", "RULES", 10)
    assert [rule.number for rule in removed.rules] == [20]
    with pytest.raises(PrefixListRuleNotFoundError):
        await service.delete_rule("ipv4", "RULES", 10)
    with pytest.raises(PrefixListRuleNotFoundError):
        await service.update_rule(
            "ipv4", "RULES", 10, PrefixListRuleUpdate(action="permit", prefix="10.0.0.0/8")
        )

    with pytest.raises(PrefixListNotFoundError):
        await service.create_rule(
            "ipv4", "MISSING", PrefixListRuleCreate(number=10, action="permit", prefix="10.0.0.0/8")
        )
    with pytest.raises(PrefixListNotFoundError):
        await service.delete_rule("ipv4", "MISSING", 10)


async def test_rule_prefix_must_match_list_family() -> None:
    service, _driver = await make_service()
    await service.create(PrefixListCreate(name="V4", family="ipv4"))
    await service.create(PrefixListCreate(name="V6", family="ipv6"))

    with pytest.raises(PrefixListValidationError) as wrong_create:
        await service.create_rule(
            "ipv4",
            "V4",
            PrefixListRuleCreate(number=10, action="permit", prefix="2001:db8::/32"),
        )
    assert wrong_create.value.field == "prefix"

    created = await service.create_rule(
        "ipv4", "V4", PrefixListRuleCreate(number=10, action="permit", prefix="10.0.0.0/8")
    )
    assert created.rules[0].prefix == "10.0.0.0/8"

    with pytest.raises(PrefixListValidationError):
        await service.update_rule(
            "ipv4",
            "V4",
            10,
            PrefixListRuleUpdate(action="permit", prefix="2001:db8::/32"),
        )

    # The same IPv6 prefix is fine in the IPv6 tree.
    ipv6 = await service.create_rule(
        "ipv6", "V6", PrefixListRuleCreate(number=10, action="permit", prefix="2001:db8::/32")
    )
    assert ipv6.rules[0].prefix == "2001:db8::/32"


async def test_rule_update_preserves_unknown_device_fields() -> None:
    service, driver = await make_service()
    await service.create(PrefixListCreate(name="UNKNOWN", family="ipv4"))
    await service.create_rule(
        "ipv4",
        "UNKNOWN",
        PrefixListRuleCreate(
            number=10,
            action="permit",
            prefix="203.0.113.0/24",
            ge=24,
            le=32,
            description="old",
        ),
    )
    rule_base = [*PREFIX_LIST_ROOTS["ipv4"], "UNKNOWN", "rule", "10"]
    await driver.apply(
        [
            ConfigOp("set", [*rule_base, "vendor-rule-flag"]),
            ConfigOp("set", [*rule_base, "vendor-container", "keep"]),
        ]
    )

    updated = await service.update_rule(
        "ipv4",
        "UNKNOWN",
        10,
        PrefixListRuleUpdate(
            action="deny",
            prefix="198.51.100.0/24",
            ge=None,
            le=None,
            description=None,
        ),
    )
    rule = updated.rules[0]
    assert (rule.ge, rule.le, rule.description) == (None, None, None)

    raw_rule = await driver.get_config(rule_base)
    assert raw_rule["action"] == "deny"
    assert raw_rule["prefix"] == "198.51.100.0/24"
    assert "ge" not in raw_rule
    assert "le" not in raw_rule
    assert "description" not in raw_rule
    assert "vendor-rule-flag" in raw_rule
    assert raw_rule["vendor-container"] == {"keep": {}}


async def test_delete_refuses_in_use_prefix_lists() -> None:
    service, _driver = await make_service()

    with pytest.raises(PrefixListInUseError) as transit_in:
        await service.delete("ipv4", "TRANSIT-IN")
    assert transit_in.value.used_by == ["Route-map BGP-IN · rule 10 · IPv4 prefix-list"]

    with pytest.raises(PrefixListInUseError) as bogons:
        await service.delete("ipv4", "TRANSIT-BOGONS")
    assert bogons.value.used_by == ["Route-map BGP-IN · rule 20 · IPv4 prefix-list"]

    # TRANSIT-V6 is not referenced by the seed, so it can be removed.
    await service.delete("ipv6", "TRANSIT-V6")
    assert [item.name for item in (await service.list("ipv6")).items] == []


async def test_usage_detection_includes_route_maps_and_bgp() -> None:
    service, driver = await make_service()
    await service.create(PrefixListCreate(name="FILTER", family="ipv4"))
    await service.create(PrefixListCreate(name="FILTER", family="ipv6"))

    await driver.apply(
        [
            ConfigOp("set", ["policy", "route-map", "RM-USAGE"]),
            ConfigOp("set", ["policy", "route-map", "RM-USAGE", "rule", "10"]),
            ConfigOp("set", ["policy", "route-map", "RM-USAGE", "rule", "10", "action", "permit"]),
            ConfigOp(
                "set",
                [
                    "policy",
                    "route-map",
                    "RM-USAGE",
                    "rule",
                    "10",
                    "match",
                    "ip",
                    "address",
                    "prefix-list",
                    "FILTER",
                ],
            ),
            ConfigOp("set", ["policy", "route-map", "RM-USAGE", "rule", "20"]),
            ConfigOp("set", ["policy", "route-map", "RM-USAGE", "rule", "20", "action", "deny"]),
            ConfigOp(
                "set",
                [
                    "policy",
                    "route-map",
                    "RM-USAGE",
                    "rule",
                    "20",
                    "match",
                    "ipv6",
                    "nexthop",
                    "prefix-list",
                    "FILTER",
                ],
            ),
            ConfigOp(
                "set",
                [
                    "protocols",
                    "bgp",
                    "neighbor",
                    "192.0.2.9",
                    "address-family",
                    "ipv4-unicast",
                    "prefix-list",
                    "import",
                    "FILTER",
                ],
            ),
        ]
    )

    ipv4 = await service.get("ipv4", "FILTER")
    assert ipv4.in_use is True
    assert ipv4.used_by == [
        "BGP neighbor 192.0.2.9 · ipv4-unicast · prefix-list import",
        "Route-map RM-USAGE · rule 10 · IPv4 prefix-list",
    ]

    ipv6 = await service.get("ipv6", "FILTER")
    assert ipv6.in_use is True
    assert ipv6.used_by == ["Route-map RM-USAGE · rule 20 · IPv6 nexthop prefix-list"]

    with pytest.raises(PrefixListInUseError) as in_use:
        await service.delete("ipv4", "FILTER")
    assert "BGP neighbor 192.0.2.9 · ipv4-unicast · prefix-list import" in in_use.value.used_by


async def test_empty_policy_tree_is_treated_as_no_prefix_lists() -> None:
    service, driver = await make_service()
    await driver.apply([ConfigOp("delete", ["policy"])])

    assert (await service.list()).items == []
    with pytest.raises(PrefixListNotFoundError):
        await service.get("ipv4", "TRANSIT-IN")

    created = await service.create(PrefixListCreate(name="FRESH", family="ipv4"))
    assert created.family == "ipv4"
    assert (await service.get("ipv4", "FRESH")).name == "FRESH"


class _CountingDriver(MockDriver):
    def __init__(self, target: DeviceTarget) -> None:
        super().__init__(target)
        self.apply_calls = 0

    async def apply(self, ops: list[ConfigOp]) -> None:
        self.apply_calls += 1
        await super().apply(ops)


async def test_mutations_are_single_atomic_batches() -> None:
    target = make_target()
    driver = _CountingDriver(target)
    service = PrefixListService(driver, Router(id=target.id, name="mock-prefix-lists"))

    driver.apply_calls = 0
    await service.create(PrefixListCreate(name="ATOMIC", family="ipv4", description="x"))
    assert driver.apply_calls == 1

    driver.apply_calls = 0
    await service.update("ipv4", "ATOMIC", PrefixListUpdate(description="y"))
    assert driver.apply_calls == 1

    driver.apply_calls = 0
    await service.update("ipv4", "ATOMIC", PrefixListUpdate(description="y"))
    assert driver.apply_calls == 0

    rule = PrefixListRuleCreate(
        number=10,
        action="permit",
        prefix="203.0.113.0/24",
        ge=24,
        le=32,
        description="Customer /24s",
    )
    driver.apply_calls = 0
    await service.create_rule("ipv4", "ATOMIC", rule)
    assert driver.apply_calls == 1

    driver.apply_calls = 0
    await service.update_rule(
        "ipv4",
        "ATOMIC",
        10,
        PrefixListRuleUpdate(
            action="permit",
            prefix="203.0.113.0/24",
            ge=24,
            le=32,
            description="Customer /24s",
        ),
    )
    assert driver.apply_calls == 0

    driver.apply_calls = 0
    await service.update_rule(
        "ipv4",
        "ATOMIC",
        10,
        PrefixListRuleUpdate(action="deny", prefix="203.0.113.0/24"),
    )
    assert driver.apply_calls == 1

    driver.apply_calls = 0
    await service.delete_rule("ipv4", "ATOMIC", 10)
    assert driver.apply_calls == 1

    driver.apply_calls = 0
    await service.delete("ipv4", "ATOMIC")
    assert driver.apply_calls == 1
