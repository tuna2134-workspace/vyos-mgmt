"""Unit tests for route-map config parsing and write-op planning."""

from __future__ import annotations

from typing import Any

from vyos_mgmt.schemas.route_map import (
    RouteMapMatch,
    RouteMapRuleCreate,
    RouteMapRuleUpdate,
    RouteMapSet,
)
from vyos_mgmt.services.route_map_service import (
    ROUTE_MAP_ROOT,
    build_map_create_ops,
    build_map_update_ops,
    build_rule_create_ops,
    build_rule_delete_ops,
    build_rule_update_ops,
    collect_route_map_usage,
    parse_route_map,
    parse_route_maps,
)
from vyos_mgmt.services.vyos.base import ConfigOp

RAW_ROUTE_MAPS: dict[str, Any] = {
    "BGP-IN": {
        "description": "Inbound filtering for transit",
        "rule": {
            "50": {
                "action": "permit",
                "description": "Continue elsewhere",
                "on-match": {"next": {}},
                "call": "BGP-OUT",
                "continue": "20",
            },
            "10": {
                "action": "permit",
                "description": "Allow transit prefixes",
                "match": {
                    "ip": {
                        "address": {"prefix-list": "TRANSIT-IN"},
                        "nexthop": {"address": "192.0.2.9"},
                    },
                    "ipv6": {
                        "address": {"prefix-list": "TRANSIT-V6"},
                        "nexthop": {"address": "2001:db8::9"},
                    },
                    "as-path": "AS-LIST",
                    "community": {
                        "community-list": "CUSTOMER-COMM",
                        "exact-match": {},
                    },
                    "large-community": {"large-community-list": "LARGE-COMM"},
                    "extcommunity": "EXT-COMM",
                    "metric": "100",
                    "local-preference": "200",
                    "origin": "igp",
                    "tag": "300",
                    "protocol": "bgp",
                    "rpki": "valid",
                    "interface": "eth0",
                },
                "set": {
                    "local-preference": "250",
                    "metric": "+50",
                    "origin": "egp",
                    "weight": "100",
                    "metric-type": "type-1",
                    "tag": "500",
                    "as-path": {"prepend": {"64512": {}, "64513": {}}},
                    "community": {"add": {"64512:100": {}, "no-export": {}}},
                    "ip-next-hop": "192.0.2.1",
                    "originator-id": "10.0.0.1",
                },
                "on-match": {"goto": "20"},
                "call": "BGP-OUT",
                "continue": "30",
            },
            "20": {
                "action": "deny",
                "description": "Drop bogons",
                "match": {"ip": {"address": {"prefix-list": "TRANSIT-BOGONS"}}},
            },
            "30": {
                "action": "permit",
                "match": {"community": {"community-list": "DEL-COMM"}},
                "set": {"community": {"delete": "DEL-COMM"}},
            },
            "40": {"action": "permit", "set": {"community": {"none": {}}}},
            "not-a-number": {"action": "permit"},
        },
    },
    "VARIANTS": {
        "rule": {
            "1": {
                "action": "permit",
                "set": {
                    "as-path": {"prepend": ["64512", "64513"]},
                    "community": {"replace": ["64512:1", "64512:2"]},
                },
            },
            "2": {
                "action": "permit",
                "set": {
                    "as-path": {"prepend": "64514"},
                    "community": {"delete": "DEL-COMM"},
                },
            },
            "3": {"action": "permit", "set": {"community": {"none": {}}}},
            "4": {"description": "No action configured"},
            "5": {
                "action": "permit",
                "set": {"metric-type": "external"},
            },
            "6": {
                "action": "permit",
                "set": {"metric-type": "internal"},
            },
        },
    },
}


def _paths(ops: list[ConfigOp], op: str = "set") -> list[list[str]]:
    return [item.path for item in ops if item.op == op]


def test_parse_route_map_matches_contract() -> None:
    route_map = parse_route_map("BGP-IN", RAW_ROUTE_MAPS["BGP-IN"])
    assert route_map.name == "BGP-IN"
    assert route_map.description == "Inbound filtering for transit"
    assert [rule.number for rule in route_map.rules] == [10, 20, 30, 40, 50]
    assert route_map.in_use is False
    assert route_map.used_by == []

    rule = route_map.rules[0]
    assert rule.action == "permit"
    assert rule.description == "Allow transit prefixes"
    match = rule.match
    assert match.ipv4_prefix_list == "TRANSIT-IN"
    assert match.ipv6_prefix_list == "TRANSIT-V6"
    assert match.as_path == "AS-LIST"
    assert match.community_list == "CUSTOMER-COMM"
    assert match.community_exact_match is True
    assert match.large_community_list == "LARGE-COMM"
    assert match.extcommunity == "EXT-COMM"
    assert match.metric == 100
    assert match.local_preference == 200
    assert match.origin == "igp"
    assert match.tag == 300
    assert match.protocol == "bgp"
    assert match.rpki == "valid"
    assert match.ip_nexthop == "192.0.2.9"
    assert match.ipv6_nexthop == "2001:db8::9"
    assert match.interface == "eth0"

    set_values = rule.set
    assert set_values.local_preference == 250
    assert set_values.metric == "+50"
    assert set_values.origin == "egp"
    assert set_values.weight == 100
    assert set_values.metric_type == "type-1"
    assert set_values.tag == 500
    assert set_values.as_path_prepend == [64512, 64513]
    assert set_values.community_action == "add"
    assert set_values.community_values == ["64512:100", "no-export"]
    assert set_values.community_delete is None
    assert set_values.ip_next_hop == "192.0.2.1"
    assert set_values.originator_id == "10.0.0.1"

    assert rule.on_match == "goto"
    assert rule.goto_rule == 20
    assert rule.call == "BGP-OUT"
    assert rule.continue_rule == 30

    next_rule = route_map.rules[-1]
    assert next_rule.on_match == "next"
    assert next_rule.goto_rule is None
    assert next_rule.call == "BGP-OUT"
    assert next_rule.continue_rule == 20


def test_parse_community_delete_and_none() -> None:
    route_map = parse_route_map("BGP-IN", RAW_ROUTE_MAPS["BGP-IN"])
    by_number = {rule.number: rule for rule in route_map.rules}
    assert by_number[30].set.community_action == "delete"
    assert by_number[30].set.community_delete == "DEL-COMM"
    assert by_number[40].set.community_action == "none"
    assert by_number[40].set.community_values == []


def test_parse_multi_value_leaves_from_lists_and_scalars() -> None:
    route_map = parse_route_map("VARIANTS", RAW_ROUTE_MAPS["VARIANTS"])
    by_number = {rule.number: rule for rule in route_map.rules}
    assert [rule.number for rule in route_map.rules] == [1, 2, 3, 5, 6]
    assert by_number[1].set.as_path_prepend == [64512, 64513]
    assert by_number[1].set.community_action == "replace"
    assert by_number[1].set.community_values == ["64512:1", "64512:2"]
    assert by_number[2].set.as_path_prepend == [64514]
    assert by_number[2].set.community_action == "delete"
    assert by_number[3].set.community_action == "none"
    # VyOS only accepts type-1/type-2; unsupported values are ignored on read.
    assert by_number[5].set.metric_type is None
    assert by_number[6].set.metric_type is None


def test_parse_route_maps_sorted_and_missing_paths() -> None:
    parsed = parse_route_maps(RAW_ROUTE_MAPS)
    assert [route_map.name for route_map in parsed] == ["BGP-IN", "VARIANTS"]
    assert parse_route_maps({}) == []
    assert parse_route_map("EMPTY", {}).rules == []


def test_route_map_usage_labels_are_precise_and_deduped() -> None:
    bgp_raw: dict[str, Any] = {
        "neighbor": {
            "192.0.2.1": {
                "address-family": {
                    "ipv4-unicast": {"route-map": {"import": "BGP-IN", "export": {"BGP-OUT": {}}}}
                }
            }
        },
        "peer-group": {
            "transit": {"address-family": {"ipv4-unicast": {"route-map": {"import": "BGP-IN"}}}}
        },
        "address-family": {
            "ipv4-unicast": {
                "redistribute": {"connected": {"route-map": "REDIST"}},
                "network": {"203.0.113.0/24": {"route-map": "NET-MAP"}},
            }
        },
    }
    route_maps_raw = {
        "BGP-IN": {"rule": {"50": {"action": "permit", "call": "BGP-OUT"}}},
        "BGP-OUT": {},
        "REDIST": {},
        "NET-MAP": {},
    }

    usage = collect_route_map_usage(bgp_raw, route_maps_raw)

    assert usage["BGP-IN"] == [
        "BGP neighbor 192.0.2.1 · ipv4-unicast · import",
        "BGP peer-group transit · ipv4-unicast · import",
    ]
    assert usage["BGP-OUT"] == [
        "BGP neighbor 192.0.2.1 · ipv4-unicast · export",
        "Route-map BGP-IN rule 50 call",
    ]
    assert usage["REDIST"] == ["BGP redistribute connected · ipv4-unicast"]
    assert usage["NET-MAP"] == ["BGP network 203.0.113.0/24 · ipv4-unicast"]
    assert usage["BGP-IN"] == sorted(set(usage["BGP-IN"]))
    assert collect_route_map_usage({}, {}) == {}


def test_route_map_usage_includes_ospf_redistribution() -> None:
    ospf_raw: dict[str, Any] = {
        "redistribute": {
            "connected": {"route-map": "OSPF-OUT"},
            "static": {"route-map": "STATIC-MAP"},
        }
    }
    ospfv3_raw: dict[str, Any] = {
        "redistribute": {
            "connected": {"route-map": "OSPF-OUT"},
            "ripng": {"route-map": "RIPNG-MAP"},
        }
    }

    usage = collect_route_map_usage({}, {}, ospf_raw=ospf_raw, ospfv3_raw=ospfv3_raw)
    assert usage["OSPF-OUT"] == [
        "OSPFv2 redistribute connected · route-map",
        "OSPFv3 redistribute connected · route-map",
    ]
    assert usage["STATIC-MAP"] == ["OSPFv2 redistribute static · route-map"]
    assert usage["RIPNG-MAP"] == ["OSPFv3 redistribute ripng · route-map"]

    # Existing callers keep working without the OSPF arguments.
    assert collect_route_map_usage({}, {}) == {}
    assert collect_route_map_usage({}, {}, ospf_raw={"redistribute": {}}) == {}


def test_build_map_create_and_update_ops() -> None:
    assert _paths(build_map_create_ops("NEW-MAP", None)) == [[*ROUTE_MAP_ROOT, "NEW-MAP"]]
    with_description = _paths(build_map_create_ops("NEW-MAP", "text"))
    assert with_description == [
        [*ROUTE_MAP_ROOT, "NEW-MAP"],
        [*ROUTE_MAP_ROOT, "NEW-MAP", "description", "text"],
    ]

    base = [*ROUTE_MAP_ROOT, "BGP-IN"]
    update = build_map_update_ops("BGP-IN", "new text", RAW_ROUTE_MAPS["BGP-IN"])
    assert _paths(update) == [[*base, "description", "new text"]]

    clear = build_map_update_ops("BGP-IN", None, RAW_ROUTE_MAPS["BGP-IN"])
    assert _paths(clear, "delete") == [[*base, "description"]]

    assert (
        build_map_update_ops("BGP-IN", "Inbound filtering for transit", RAW_ROUTE_MAPS["BGP-IN"])
        == []
    )


def test_build_rule_create_ops_covers_all_managed_fields() -> None:
    rule = RouteMapRuleCreate(
        number=10,
        action="permit",
        description="Full rule",
        match=RouteMapMatch(
            ipv4_prefix_list="TRANSIT-IN",
            ipv6_prefix_list="TRANSIT-V6",
            as_path="AS-LIST",
            community_list="CUSTOMER-COMM",
            community_exact_match=True,
            large_community_list="LARGE-COMM",
            extcommunity="EXT-COMM",
            metric=100,
            local_preference=200,
            origin="igp",
            tag=300,
            protocol="bgp",
            rpki="valid",
            ip_nexthop="192.0.2.9",
            ipv6_nexthop="2001:db8::9",
            interface="eth0",
        ),
        set=RouteMapSet(
            local_preference=250,
            metric="+50",
            origin="egp",
            weight=100,
            metric_type="type-1",
            tag=500,
            as_path_prepend=[64512, 64513],
            community_action="add",
            community_values=["64512:100", "no-export"],
            ip_next_hop="192.0.2.1",
            originator_id="10.0.0.1",
        ),
        on_match="goto",
        goto_rule=20,
        call="BGP-OUT",
        continue_rule=30,
    )
    ops = build_rule_create_ops("NEW-MAP", rule)
    paths = _paths(ops)
    base = [*ROUTE_MAP_ROOT, "NEW-MAP", "rule", "10"]
    expected = [
        base,
        [*base, "action", "permit"],
        [*base, "description", "Full rule"],
        [*base, "match", "ip", "address", "prefix-list", "TRANSIT-IN"],
        [*base, "match", "ipv6", "address", "prefix-list", "TRANSIT-V6"],
        [*base, "match", "as-path", "AS-LIST"],
        [*base, "match", "community", "community-list", "CUSTOMER-COMM"],
        [*base, "match", "large-community", "large-community-list", "LARGE-COMM"],
        [*base, "match", "extcommunity", "EXT-COMM"],
        [*base, "match", "metric", "100"],
        [*base, "match", "local-preference", "200"],
        [*base, "match", "origin", "igp"],
        [*base, "match", "tag", "300"],
        [*base, "match", "protocol", "bgp"],
        [*base, "match", "rpki", "valid"],
        [*base, "match", "ip", "nexthop", "address", "192.0.2.9"],
        [*base, "match", "ipv6", "nexthop", "address", "2001:db8::9"],
        [*base, "match", "interface", "eth0"],
        [*base, "match", "community", "exact-match"],
        [*base, "set", "local-preference", "250"],
        [*base, "set", "metric", "+50"],
        [*base, "set", "origin", "egp"],
        [*base, "set", "weight", "100"],
        [*base, "set", "metric-type", "type-1"],
        [*base, "set", "tag", "500"],
        [*base, "set", "ip-next-hop", "192.0.2.1"],
        [*base, "set", "originator-id", "10.0.0.1"],
        [*base, "set", "as-path", "prepend", "64512"],
        [*base, "set", "as-path", "prepend", "64513"],
        [*base, "set", "community", "add", "64512:100"],
        [*base, "set", "community", "add", "no-export"],
        [*base, "on-match", "goto", "20"],
        [*base, "call", "BGP-OUT"],
        [*base, "continue", "30"],
    ]
    assert paths == expected
    assert _paths(ops, "delete") == []


def test_rule_update_preserves_unknown_fields_and_syncs_managed_fields() -> None:
    base = [*ROUTE_MAP_ROOT, "BGP-IN", "rule", "10"]
    existing: dict[str, Any] = {
        "action": "permit",
        "description": "old",
        "match": {
            "ip": {"address": {"prefix-list": "OLD"}},
            "as-path": "OLD-AS",
            "community": {"community-list": "OLD-COMM", "exact-match": {}},
            "vendor-extension": {"keep": {}},
        },
        "set": {
            "local-preference": "100",
            "metric": "+5",
            "as-path": {"prepend": {"64512": {}}},
            "community": {"add": {"64512:100": {}}},
            "vendor-flag": {},
        },
        "on-match": {"next": {}},
        "call": "OLD-CALL",
        "continue": "99",
        "vendor-rule-flag": {},
    }
    desired = RouteMapRuleUpdate(
        action="permit",
        description=None,
        match=RouteMapMatch(ipv4_prefix_list="NEW"),
        set=RouteMapSet(
            local_preference=200,
            community_action="add",
            community_values=["64512:200"],
        ),
        on_match=None,
        call=None,
        continue_rule=None,
    )

    ops = build_rule_update_ops("BGP-IN", 10, desired, existing)
    set_paths = _paths(ops)
    delete_paths = _paths(ops, "delete")

    assert [*base, "match", "ip", "address", "prefix-list", "NEW"] in set_paths
    assert [*base, "set", "local-preference", "200"] in set_paths
    assert [*base, "set", "community", "add", "64512:200"] in set_paths

    assert [*base, "description"] in delete_paths
    assert [*base, "match", "as-path"] in delete_paths
    assert [*base, "match", "community", "community-list"] in delete_paths
    assert [*base, "match", "community", "exact-match"] in delete_paths
    assert [*base, "set", "metric"] in delete_paths
    assert [*base, "set", "as-path", "prepend"] in delete_paths
    assert [*base, "set", "community", "add"] in delete_paths
    assert [*base, "on-match"] in delete_paths
    assert [*base, "call"] in delete_paths
    assert [*base, "continue"] in delete_paths

    # The rule and its match/set containers are never deleted wholesale, and
    # unknown directives are never targeted.
    assert base not in delete_paths
    assert [*base, "match"] not in delete_paths
    assert [*base, "set"] not in delete_paths
    for path in [*set_paths, *delete_paths]:
        assert "vendor-extension" not in path
        assert "vendor-flag" not in path
        assert "vendor-rule-flag" not in path
    assert [*base, "action", "permit"] not in set_paths

    # Idempotent update: identical values produce no operations.
    same = RouteMapRuleUpdate(
        action="permit",
        description="old",
        match=RouteMapMatch(
            ipv4_prefix_list="OLD",
            as_path="OLD-AS",
            community_list="OLD-COMM",
            community_exact_match=True,
        ),
        set=RouteMapSet(
            local_preference=100,
            metric="+5",
            as_path_prepend=[64512],
            community_action="add",
            community_values=["64512:100"],
        ),
        on_match="next",
        call="OLD-CALL",
        continue_rule=99,
    )
    assert build_rule_update_ops("BGP-IN", 10, same, existing) == []


def test_rule_update_switches_on_match_mode() -> None:
    base = [*ROUTE_MAP_ROOT, "BGP-IN", "rule", "10"]
    next_existing = {"action": "permit", "on-match": {"next": {}}}
    to_goto = RouteMapRuleUpdate(action="permit", on_match="goto", goto_rule=20)
    ops = build_rule_update_ops("BGP-IN", 10, to_goto, next_existing)
    assert _paths(ops, "delete") == [[*base, "on-match"]]
    assert _paths(ops) == [[*base, "on-match", "goto", "20"]]

    goto_existing = {"action": "permit", "on-match": {"goto": "20"}}
    to_next = RouteMapRuleUpdate(action="permit", on_match="next")
    ops = build_rule_update_ops("BGP-IN", 10, to_next, goto_existing)
    assert _paths(ops, "delete") == [[*base, "on-match"]]
    assert _paths(ops) == [[*base, "on-match", "next"]]


def test_rule_delete_ops() -> None:
    assert _paths(build_rule_delete_ops("BGP-IN", 10), "delete") == [
        [*ROUTE_MAP_ROOT, "BGP-IN", "rule", "10"]
    ]


def test_metric_type_ops_support_type_1_and_2() -> None:
    base = [*ROUTE_MAP_ROOT, "BGP-IN", "rule", "10"]
    for metric_type in ("type-1", "type-2"):
        rule = RouteMapRuleCreate(
            number=10,
            action="permit",
            set=RouteMapSet(metric_type=metric_type),
        )
        assert [*base, "set", "metric-type", metric_type] in _paths(
            build_rule_create_ops("BGP-IN", rule)
        )

    existing = {"action": "permit", "set": {"metric-type": "type-1"}}
    update = RouteMapRuleUpdate(action="permit", set=RouteMapSet(metric_type="type-2"))
    ops = build_rule_update_ops("BGP-IN", 10, update, existing)
    assert _paths(ops) == [[*base, "set", "metric-type", "type-2"]]
    assert _paths(ops, "delete") == []
