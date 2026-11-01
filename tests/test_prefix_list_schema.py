"""Validation tests for the prefix-list schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from vyos_mgmt.schemas.prefix_list import (
    PrefixListCreate,
    PrefixListRuleCreate,
    PrefixListRuleRead,
    PrefixListRuleUpdate,
    PrefixListUpdate,
)


def test_prefix_list_name_shape_is_family_independent() -> None:
    for name in ("TRANSIT-IN", "a", "A.b_c-1", "A" * 128):
        created = PrefixListCreate(name=name, family="ipv4")
        assert created.name == name

    for name in ("", "-bad", ".bad", "bad name", "a/b", "A" * 129):
        with pytest.raises(ValidationError):
            PrefixListCreate(name=name, family="ipv4")

    ipv4 = PrefixListCreate(name="SHARED", family="ipv4")
    ipv6 = PrefixListCreate(name="SHARED", family="ipv6")
    assert ipv4.name == ipv6.name == "SHARED"
    assert (ipv4.family, ipv6.family) == ("ipv4", "ipv6")

    with pytest.raises(ValidationError):
        PrefixListCreate(name="VALID", family="ipv5")  # type: ignore[arg-type]


def test_prefix_list_description_validation() -> None:
    created = PrefixListCreate(name="LIST", family="ipv4", description="  text  ")
    assert created.description == "text"
    assert PrefixListCreate(name="LIST", family="ipv4", description="   ").description is None
    assert PrefixListUpdate(description=None).description is None

    with pytest.raises(ValidationError):
        PrefixListCreate(name="LIST", family="ipv4", description="x" * 256)


def test_rule_prefix_must_be_a_canonical_network() -> None:
    rule = PrefixListRuleCreate(number=10, action="permit", prefix="203.0.113.0/24")
    assert rule.prefix == "203.0.113.0/24"

    # Host bits must be zero (strict CIDR).
    with pytest.raises(ValidationError):
        PrefixListRuleCreate(number=10, action="permit", prefix="203.0.113.1/24")
    with pytest.raises(ValidationError):
        PrefixListRuleCreate(number=10, action="permit", prefix="not-a-prefix")

    ipv6 = PrefixListRuleCreate(number=10, action="deny", prefix="2001:DB8:0::/32")
    assert ipv6.prefix == "2001:db8::/32"


def test_rule_ge_le_ranges_are_family_aware() -> None:
    # IPv4 bounds are 0..32.
    assert (
        PrefixListRuleCreate(number=10, action="permit", prefix="10.0.0.0/8", ge=8, le=32).le == 32
    )
    assert PrefixListRuleCreate(number=10, action="permit", prefix="0.0.0.0/0", ge=0, le=32).ge == 0

    for ge, le in ((33, None), (None, 33), (8, 7)):
        with pytest.raises(ValidationError):
            PrefixListRuleCreate(number=10, action="permit", prefix="10.0.0.0/8", ge=ge, le=le)

    # Bounds must be >= the prefix length.
    with pytest.raises(ValidationError):
        PrefixListRuleCreate(number=10, action="permit", prefix="10.0.0.0/8", ge=7)
    with pytest.raises(ValidationError):
        PrefixListRuleCreate(number=10, action="permit", prefix="10.0.0.0/8", le=7)

    # IPv6 bounds are 0..128.
    assert (
        PrefixListRuleCreate(number=10, action="permit", prefix="2001:db8::/32", ge=32, le=128).le
        == 128
    )
    for ge, le in ((129, None), (None, 129), (64, 63)):
        with pytest.raises(ValidationError):
            PrefixListRuleCreate(number=10, action="permit", prefix="2001:db8::/32", ge=ge, le=le)
    with pytest.raises(ValidationError):
        PrefixListRuleCreate(number=10, action="permit", prefix="2001:db8::/64", ge=32)

    with pytest.raises(ValidationError):
        PrefixListRuleCreate(
            number=10,
            action="permit",
            prefix="10.0.0.0/8",
            ge=True,  # type: ignore[arg-type]
        )


def test_rule_action_number_and_description_validation() -> None:
    for action in ("permit", "deny"):
        assert PrefixListRuleCreate(number=1, action=action, prefix="10.0.0.0/8").action == action

    with pytest.raises(ValidationError):
        PrefixListRuleCreate(number=1, action="allow", prefix="10.0.0.0/8")  # type: ignore[arg-type]
    for number in (0, 65_536):
        with pytest.raises(ValidationError):
            PrefixListRuleCreate(number=number, action="permit", prefix="10.0.0.0/8")

    rule = PrefixListRuleCreate(
        number=10, action="permit", prefix="10.0.0.0/8", description="  text  "
    )
    assert rule.description == "text"
    with pytest.raises(ValidationError):
        PrefixListRuleCreate(number=10, action="permit", prefix="10.0.0.0/8", description="x" * 256)


def test_update_body_number_is_optional_and_authoritative_path_wins() -> None:
    without_number = PrefixListRuleUpdate(action="permit", prefix="10.0.0.0/8")
    assert without_number.number is None

    with_number = PrefixListRuleUpdate(number=99, action="permit", prefix="10.0.0.0/8")
    assert with_number.number == 99

    read = PrefixListRuleRead(
        number=10,
        action="permit",
        prefix="10.0.0.0/8",
        ge=None,
        le=32,
        description=None,
    )
    assert read.model_dump() == {
        "action": "permit",
        "prefix": "10.0.0.0/8",
        "ge": None,
        "le": 32,
        "description": None,
        "number": 10,
    }
