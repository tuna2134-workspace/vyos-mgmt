"""Unit tests for prefix-list config parsing, usage detection and op planning."""

from __future__ import annotations

from typing import Any

from vyos_mgmt.schemas.prefix_list import (
    PrefixListRuleCreate,
    PrefixListRuleUpdate,
)
from vyos_mgmt.services.prefix_list_service import (
    PREFIX_LIST_ROOTS,
    build_list_create_ops,
    build_list_delete_ops,
    build_list_update_ops,
    build_rule_create_ops,
    build_rule_delete_ops,
    build_rule_update_ops,
    collect_prefix_list_usage,
    parse_prefix_list,
    parse_prefix_lists,
)
from vyos_mgmt.services.vyos.base import ConfigOp

RAW_IPV4: dict[str, Any] = {
    "TRANSIT-IN": {
        "description": "Transit customer prefixes",
        "rule": {
            "20": {"action": "permit", "prefix": "198.51.100.0/24", "le": "32"},
            "10": {
                "action": "permit",
                "prefix": "203.0.113.0/24",
                "ge": "24",
                "le": "32",
                "description": "Customer /24s",
            },
        },
    },
    "VARIANTS": {
        "description": {"Variant list": {}},
        "rule": {
            "1": {
                "action": {"permit": {}},
                "prefix": {"10.0.0.0/8": {}},
                "ge": "8",
                "le": "16",
            },
            "2": {"action": "deny", "prefix": "192.168.0.0/16"},
            "3": {"action": "permit", "prefix": "2001:db8::/32"},
            "4": {"action": "permit"},
            "5": {"prefix": "10.0.0.0/8"},
            "6": {"action": "permit", "prefix": "10.0.0.0/8", "ge": "7"},
            "not-a-number": {"action": "permit", "prefix": "10.0.0.0/8"},
        },
    },
}

RAW_IPV6: dict[str, Any] = {
    "TRANSIT-V6": {
        "description": "Transit IPv6 customer prefixes",
        "rule": {
            "10": {
                "action": "permit",
                "prefix": "2001:DB8:0::/32",
                "ge": "32",
                "le": "128",
            }
        },
    }
}


def _paths(ops: list[ConfigOp], op: str = "set") -> list[list[str]]:
    return [item.path for item in ops if item.op == op]


def test_parse_ipv4_prefix_list_sorts_rules_and_values() -> None:
    prefix_list = parse_prefix_list("ipv4", "TRANSIT-IN", RAW_IPV4["TRANSIT-IN"])
    assert prefix_list.name == "TRANSIT-IN"
    assert prefix_list.family == "ipv4"
    assert prefix_list.description == "Transit customer prefixes"
    assert [rule.number for rule in prefix_list.rules] == [10, 20]
    assert prefix_list.in_use is False
    assert prefix_list.used_by == []

    rule = prefix_list.rules[0]
    assert rule.action == "permit"
    assert rule.prefix == "203.0.113.0/24"
    assert rule.ge == 24
    assert rule.le == 32
    assert rule.description == "Customer /24s"

    assert prefix_list.rules[1].ge is None
    assert prefix_list.rules[1].le == 32


def test_parse_ipv6_canonicalises_prefixes() -> None:
    prefix_list = parse_prefix_list("ipv6", "TRANSIT-V6", RAW_IPV6["TRANSIT-V6"])
    assert prefix_list.family == "ipv6"
    assert [rule.number for rule in prefix_list.rules] == [10]
    assert prefix_list.rules[0].prefix == "2001:db8::/32"
    assert prefix_list.rules[0].ge == 32
    assert prefix_list.rules[0].le == 128


def test_parse_tolerates_dict_scalars_and_skips_unrepresentable_rules() -> None:
    prefix_list = parse_prefix_list("ipv4", "VARIANTS", RAW_IPV4["VARIANTS"])
    assert prefix_list.description == "Variant list"
    # Rule 3 is an IPv6 prefix in the IPv4 tree, 4/5 lack mandatory fields and
    # 6 has ge smaller than the prefix length: all are unrepresentable.
    assert [rule.number for rule in prefix_list.rules] == [1, 2]
    single_key_dict = prefix_list.rules[0]
    assert single_key_dict.action == "permit"
    assert single_key_dict.prefix == "10.0.0.0/8"
    assert single_key_dict.ge == 8
    assert single_key_dict.le == 16


def test_parse_prefix_lists_is_sorted_and_handles_empty_trees() -> None:
    parsed = parse_prefix_lists("ipv4", RAW_IPV4)
    assert [item.name for item in parsed] == ["TRANSIT-IN", "VARIANTS"]
    assert parse_prefix_lists("ipv4", {}) == []
    assert parse_prefix_list("ipv4", "EMPTY", {}).rules == []


def test_collect_prefix_list_usage_from_route_maps_and_bgp() -> None:
    route_maps_raw: dict[str, Any] = {
        "BGP-IN": {
            "rule": {
                "10": {
                    "action": "permit",
                    "match": {"ip": {"address": {"prefix-list": "TRANSIT-IN"}}},
                },
                "20": {
                    "action": "deny",
                    "match": {"ipv6": {"address": {"prefix-list": "TRANSIT-V6"}}},
                },
                "30": {
                    "action": "deny",
                    "match": {
                        "ip": {"nexthop": {"prefix-list": "NH-V4"}},
                        "ipv6": {"nexthop": {"prefix-list": "NH-V6"}},
                    },
                },
                "40": {
                    "action": "permit",
                    "match": {"ip": {"address": {"prefix-list": {"A": {}, "B": {}}}}},
                },
            }
        }
    }
    bgp_raw: dict[str, Any] = {
        "neighbor": {
            "192.0.2.1": {
                "address-family": {
                    "ipv4-unicast": {"prefix-list": {"import": "BGP-V4", "export": "BGP-V4-OUT"}},
                    "ipv6-unicast": {"prefix-list": {"import": "BGP-V6"}},
                }
            }
        },
        "peer-group": {
            "transit": {"address-family": {"ipv6-unicast": {"prefix-list": {"import": "GROUP-V6"}}}}
        },
        "address-family": {
            "ipv4-unicast": {"redistribute": {"connected": {"prefix-list": "REDIST-V4"}}}
        },
    }

    usage = collect_prefix_list_usage(route_maps_raw, bgp_raw)

    assert usage[("ipv4", "TRANSIT-IN")] == ["Route-map BGP-IN · rule 10 · IPv4 prefix-list"]
    assert usage[("ipv6", "TRANSIT-V6")] == ["Route-map BGP-IN · rule 20 · IPv6 prefix-list"]
    assert usage[("ipv4", "NH-V4")] == ["Route-map BGP-IN · rule 30 · IPv4 nexthop prefix-list"]
    assert usage[("ipv6", "NH-V6")] == ["Route-map BGP-IN · rule 30 · IPv6 nexthop prefix-list"]
    assert usage[("ipv4", "A")] == ["Route-map BGP-IN · rule 40 · IPv4 prefix-list"]
    assert usage[("ipv4", "B")] == ["Route-map BGP-IN · rule 40 · IPv4 prefix-list"]
    assert usage[("ipv4", "BGP-V4")] == [
        "BGP neighbor 192.0.2.1 · ipv4-unicast · prefix-list import"
    ]
    assert usage[("ipv4", "BGP-V4-OUT")] == [
        "BGP neighbor 192.0.2.1 · ipv4-unicast · prefix-list export"
    ]
    assert usage[("ipv6", "BGP-V6")] == [
        "BGP neighbor 192.0.2.1 · ipv6-unicast · prefix-list import"
    ]
    assert usage[("ipv6", "GROUP-V6")] == [
        "BGP peer-group transit · ipv6-unicast · prefix-list import"
    ]
    assert usage[("ipv4", "REDIST-V4")] == ["BGP redistribute connected · ipv4-unicast"]

    for labels in usage.values():
        assert labels == sorted(set(labels))
    assert collect_prefix_list_usage({}, {}) == {}


def test_build_list_create_update_and_delete_ops() -> None:
    ipv4_root = PREFIX_LIST_ROOTS["ipv4"]
    ipv6_root = PREFIX_LIST_ROOTS["ipv6"]
    assert ipv4_root == ["policy", "prefix-list"]
    assert ipv6_root == ["policy", "prefix-list6"]

    assert _paths(build_list_create_ops("ipv4", "NEW", None)) == [[*ipv4_root, "NEW"]]
    assert _paths(build_list_create_ops("ipv6", "NEW", "text")) == [
        [*ipv6_root, "NEW"],
        [*ipv6_root, "NEW", "description", "text"],
    ]

    existing = {"description": "old"}
    assert _paths(build_list_update_ops("ipv4", "LIST", "new", existing)) == [
        [*ipv4_root, "LIST", "description", "new"]
    ]
    assert _paths(build_list_update_ops("ipv4", "LIST", None, existing), "delete") == [
        [*ipv4_root, "LIST", "description"]
    ]
    assert build_list_update_ops("ipv4", "LIST", "old", existing) == []

    assert _paths(build_list_delete_ops("ipv6", "LIST"), "delete") == [[*ipv6_root, "LIST"]]


def test_build_rule_create_ops_covers_all_managed_fields() -> None:
    rule = PrefixListRuleCreate(
        number=10,
        action="permit",
        prefix="203.0.113.0/24",
        ge=24,
        le=32,
        description="Customer /24s",
    )
    assert _paths(build_rule_create_ops("ipv4", "TRANSIT-IN", rule)) == [
        ["policy", "prefix-list", "TRANSIT-IN", "rule", "10"],
        ["policy", "prefix-list", "TRANSIT-IN", "rule", "10", "action", "permit"],
        ["policy", "prefix-list", "TRANSIT-IN", "rule", "10", "prefix", "203.0.113.0/24"],
        ["policy", "prefix-list", "TRANSIT-IN", "rule", "10", "ge", "24"],
        ["policy", "prefix-list", "TRANSIT-IN", "rule", "10", "le", "32"],
        [
            "policy",
            "prefix-list",
            "TRANSIT-IN",
            "rule",
            "10",
            "description",
            "Customer /24s",
        ],
    ]
    assert _paths(build_rule_create_ops("ipv4", "TRANSIT-IN", rule), "delete") == []


def test_rule_update_syncs_managed_leaves_and_preserves_unknown_fields() -> None:
    base = ["policy", "prefix-list", "TRANSIT-IN", "rule", "10"]
    existing: dict[str, Any] = {
        "action": "permit",
        "prefix": "203.0.113.0/24",
        "ge": "24",
        "le": "32",
        "description": "old",
        "vendor-rule-flag": {},
        "vendor-container": {"keep": {}},
    }
    desired = PrefixListRuleUpdate(
        action="deny",
        prefix="198.51.100.0/24",
        ge=None,
        le=None,
        description=None,
    )
    ops = build_rule_update_ops("ipv4", "TRANSIT-IN", 10, desired, existing)

    assert _paths(ops) == [
        [*base, "action", "deny"],
        [*base, "prefix", "198.51.100.0/24"],
    ]
    assert _paths(ops, "delete") == [
        [*base, "ge"],
        [*base, "le"],
        [*base, "description"],
    ]
    for path in [*_paths(ops), *_paths(ops, "delete")]:
        assert path[: len(base)] == base
        assert "vendor-rule-flag" not in path
        assert "vendor-container" not in path

    same = PrefixListRuleUpdate(
        action="permit",
        prefix="203.0.113.0/24",
        ge=24,
        le=32,
        description="old",
    )
    assert build_rule_update_ops("ipv4", "TRANSIT-IN", 10, same, existing) == []

    # Device values may be non-canonical; comparison is canonical.
    canonical_existing = {"action": "permit", "prefix": "2001:0DB8::/32"}
    canonical_desired = PrefixListRuleUpdate(action="permit", prefix="2001:db8::/32")
    assert build_rule_update_ops("ipv6", "LIST", 10, canonical_desired, canonical_existing) == []

    # Setting a previously cleared bound emits a single set op.
    add_bounds = PrefixListRuleUpdate(
        action="permit",
        prefix="203.0.113.0/24",
        ge=24,
        le=32,
        description=None,
    )
    add_ops = build_rule_update_ops(
        "ipv4", "TRANSIT-IN", 10, add_bounds, {"action": "permit", "prefix": "203.0.113.0/24"}
    )
    assert _paths(add_ops) == [[*base, "ge", "24"], [*base, "le", "32"]]


def test_rule_delete_ops() -> None:
    assert _paths(build_rule_delete_ops("ipv6", "TRANSIT-V6", 10), "delete") == [
        ["policy", "prefix-list6", "TRANSIT-V6", "rule", "10"]
    ]
