"""Validation tests for route-map schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from vyos_mgmt.schemas.route_map import (
    WELL_KNOWN_COMMUNITIES,
    RouteMapCreate,
    RouteMapMatch,
    RouteMapRuleCreate,
    RouteMapRuleRead,
    RouteMapRuleUpdate,
    RouteMapSet,
    RouteMapUpdate,
)


def _rule(**overrides: object) -> RouteMapRuleCreate:
    payload: dict[str, object] = {"number": 10, "action": "permit"}
    payload.update(overrides)
    return RouteMapRuleCreate.model_validate(payload)


def test_route_map_name_shape() -> None:
    assert RouteMapCreate(name="BGP-IN").name == "BGP-IN"
    assert RouteMapCreate(name="a").name == "a"
    assert RouteMapCreate(name="A" * 64).name == "A" * 64

    for name in ("", "-leading", ".leading", "_leading", "has space", "bad/name", "A" * 65):
        with pytest.raises(ValidationError):
            RouteMapCreate(name=name)

    assert _rule(call="BGP-OUT").call == "BGP-OUT"
    with pytest.raises(ValidationError):
        _rule(call="bad name")
    with pytest.raises(ValidationError):
        _rule(call="A" * 65)

    # Referenced policy objects may be up to 128 characters.
    match = RouteMapMatch(ipv4_prefix_list="P" * 128)
    assert match.ipv4_prefix_list == "P" * 128
    with pytest.raises(ValidationError):
        RouteMapMatch(ipv4_prefix_list="P" * 129)


def test_action_is_required_and_restricted() -> None:
    with pytest.raises(ValidationError):
        RouteMapRuleCreate.model_validate({"number": 10})
    with pytest.raises(ValidationError):
        _rule(action="allow")
    assert _rule(action="deny").action == "deny"


def test_description_blank_becomes_null() -> None:
    assert RouteMapCreate(name="X", description="  ").description is None
    assert RouteMapUpdate(description="  ").description is None
    assert _rule(description="").description is None


def test_match_ranges_and_enums() -> None:
    valid = RouteMapMatch(
        metric=1,
        local_preference=4_294_967_295,
        tag=65_535,
        origin="igp",
        protocol="bgp",
        rpki="valid",
        ip_nexthop="192.0.2.1",
        ipv6_nexthop="2001:db8::1",
        interface="eth0",
    )
    assert valid.metric == 1
    assert valid.local_preference == 4_294_967_295

    for payload in (
        {"metric": 0},
        {"metric": 65_536},
        {"local_preference": -1},
        {"local_preference": 4_294_967_296},
        {"tag": 0},
        {"tag": 65_536},
        {"origin": "local"},
        {"protocol": "eigrp"},
        {"rpki": "unknown"},
        {"ip_nexthop": "not-an-ip"},
        {"ipv6_nexthop": "192.0.2.1"},
        {"interface": "1bad"},
    ):
        with pytest.raises(ValidationError):
            RouteMapMatch.model_validate(payload)


def test_community_exact_match_requires_list() -> None:
    with pytest.raises(ValidationError):
        RouteMapMatch(community_exact_match=True)
    match = RouteMapMatch(community_list="CUSTOMER-COMM", community_exact_match=True)
    assert match.community_exact_match is True


def test_set_metric_expressions() -> None:
    valid = {
        "0": "0",
        "4294967295": "4294967295",
        "+50": "+50",
        "-50": "-50",
        "rtt": "rtt",
        "+rtt": "+rtt",
        "-RTT": "-rtt",
        50: "50",
        "007": "7",
    }
    for value, expected in valid.items():
        assert RouteMapSet(metric=value).metric == expected

    for value in (
        "4294967296",
        "+4294967296",
        "-4294967296",
        "rtt2",
        "--1",
        "1.5",
        "abc",
        True,
    ):
        with pytest.raises(ValidationError):
            RouteMapSet(metric=value)

    assert RouteMapSet(metric="").metric is None


def test_set_ranges_and_as_path() -> None:
    assert RouteMapSet(local_preference=0, weight=4_294_967_295, tag=65_535)
    for payload in (
        {"local_preference": -1},
        {"local_preference": 4_294_967_296},
        {"weight": -1},
        {"weight": 4_294_967_296},
        {"tag": 0},
        {"tag": 65_536},
        {"metric_type": "type-3"},
        {"origin": "local"},
    ):
        with pytest.raises(ValidationError):
            RouteMapSet.model_validate(payload)

    for metric_type in ("type-1", "type-2"):
        assert RouteMapSet(metric_type=metric_type).metric_type == metric_type

    assert RouteMapSet(as_path_prepend=[1, 4_294_967_295]).as_path_prepend == [1, 4_294_967_295]
    assert RouteMapSet(as_path_prepend=list(range(1, 21))).as_path_prepend == list(range(1, 21))
    with pytest.raises(ValidationError):
        RouteMapSet(as_path_prepend=list(range(1, 22)))
    with pytest.raises(ValidationError):
        RouteMapSet(as_path_prepend=[0])
    with pytest.raises(ValidationError):
        RouteMapSet(as_path_prepend=[4_294_967_296])


def test_community_values_and_coherence() -> None:
    for name in WELL_KNOWN_COMMUNITIES:
        assert RouteMapSet(community_action="add", community_values=[name]).community_values == [
            name
        ]
    assert RouteMapSet(
        community_action="replace", community_values=["65535:65535", "0:0"]
    ).community_values == ["65535:65535", "0:0"]
    assert RouteMapSet(community_action="add", community_values=["NO-EXPORT"]).community_values == [
        "no-export"
    ]

    for value in ("65536:1", "1:65536", "65000", "not:1", "64512:", "1:2:3", ""):
        with pytest.raises(ValidationError):
            RouteMapSet(community_action="add", community_values=[value])

    with pytest.raises(ValidationError):
        RouteMapSet(community_action="add")
    with pytest.raises(ValidationError):
        RouteMapSet(
            community_action="add",
            community_values=["64512:100"],
            community_delete="SOME-LIST",
        )
    with pytest.raises(ValidationError):
        RouteMapSet(community_action="delete")
    with pytest.raises(ValidationError):
        RouteMapSet(community_action="delete", community_values=["64512:100"])
    with pytest.raises(ValidationError):
        RouteMapSet(community_action="none", community_values=["64512:100"])
    with pytest.raises(ValidationError):
        RouteMapSet(community_values=["64512:100"])

    assert RouteMapSet(community_action="delete", community_delete="DEL-COMM")
    assert RouteMapSet(community_action="none").community_action == "none"
    assert RouteMapSet().community_action is None


def test_next_hop_and_originator_validation() -> None:
    assert RouteMapSet(ip_next_hop="192.0.2.1").ip_next_hop == "192.0.2.1"
    assert RouteMapSet(ip_next_hop="unchanged").ip_next_hop == "unchanged"
    assert RouteMapSet(ip_next_hop="peer-address").ip_next_hop == "peer-address"
    assert RouteMapSet(originator_id="10.0.0.1").originator_id == "10.0.0.1"
    for payload in (
        {"ip_next_hop": "router"},
        {"ip_next_hop": "2001:db8::1"},
        {"originator_id": "not-an-ip"},
        {"originator_id": "2001:db8::1"},
    ):
        with pytest.raises(ValidationError):
            RouteMapSet.model_validate(payload)


def test_on_match_goto_consistency() -> None:
    with pytest.raises(ValidationError):
        _rule(on_match="goto")
    with pytest.raises(ValidationError):
        _rule(on_match="goto", goto_rule=10)
    with pytest.raises(ValidationError):
        _rule(on_match="next", goto_rule=20)
    with pytest.raises(ValidationError):
        _rule(goto_rule=20)
    with pytest.raises(ValidationError):
        _rule(on_match="goto", goto_rule=0)
    with pytest.raises(ValidationError):
        _rule(on_match="goto", goto_rule=65_536)

    rule = _rule(on_match="goto", goto_rule=20)
    assert rule.on_match == "goto"
    assert rule.goto_rule == 20
    assert _rule(on_match="next").goto_rule is None

    assert _rule(continue_rule=1).continue_rule == 1
    assert _rule(continue_rule=65_535).continue_rule == 65_535
    for value in (0, 65_536):
        with pytest.raises(ValidationError):
            _rule(continue_rule=value)


def test_rule_update_accepts_body_number_but_allows_omission() -> None:
    update = RouteMapRuleUpdate(action="permit", number=10)
    assert update.number == 10
    assert RouteMapRuleUpdate(action="permit").number is None
    with pytest.raises(ValidationError):
        RouteMapRuleUpdate(action="permit", on_match="goto", goto_rule=10, number=10)
    # Without a body number the service validates goto against the path number.
    assert RouteMapRuleUpdate(action="permit", on_match="goto", goto_rule=10).goto_rule == 10


def test_read_model_serialises_contract_field_names() -> None:
    rule = RouteMapRuleRead(
        number=10,
        action="permit",
        match=RouteMapMatch(ipv4_prefix_list="TRANSIT-IN"),
        set=RouteMapSet(metric="+50", community_action="add", community_values=["64512:100"]),
    )
    data = rule.model_dump(mode="json")
    assert data["number"] == 10
    assert data["match"]["ipv4_prefix_list"] == "TRANSIT-IN"
    assert data["set"]["metric"] == "+50"
    assert data["set"]["community_values"] == ["64512:100"]
    assert data["on_match"] is None
    assert data["continue_rule"] is None


def test_rule_list_fields_are_always_arrays() -> None:
    data = RouteMapSet().model_dump(mode="json")
    assert data["as_path_prepend"] == []
    assert data["community_values"] == []

    read = RouteMapRuleRead(number=1, action="permit").model_dump(mode="json")
    assert read["set"]["as_path_prepend"] == []
    assert read["set"]["community_values"] == []

    for payload in (
        {"as_path_prepend": None},
        {"community_values": None},
    ):
        with pytest.raises(ValidationError):
            RouteMapSet.model_validate(payload)
