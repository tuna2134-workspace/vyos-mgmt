"""Validation tests for the static-route schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from vyos_mgmt.schemas.static_route import (
    StaticNextHop,
    StaticRouteCreate,
    StaticRouteList,
    StaticRouteRead,
    StaticRouteUpdate,
    canonical_host_address,
    canonical_route_prefix,
    route_type,
    validate_interface_name,
)


def _hop(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"address": "192.0.2.1"}
    payload.update(overrides)
    return payload


def _create(**overrides: object) -> StaticRouteCreate:
    payload: dict[str, object] = {
        "family": "ipv4",
        "prefix": "10.0.0.0/8",
        "next_hops": [_hop()],
    }
    payload.update(overrides)
    return StaticRouteCreate.model_validate(payload)


def test_prefix_canonicalisation_and_host_bits() -> None:
    assert canonical_route_prefix(" 10.0.0.0/8 ") == "10.0.0.0/8"
    assert canonical_route_prefix("2001:DB8:0:0::/32") == "2001:db8::/32"
    assert canonical_route_prefix("::ffff:c000:200/120") == "::ffff:192.0.2.0/120"
    assert canonical_route_prefix("0.0.0.0/0") == "0.0.0.0/0"

    create = _create(prefix="198.51.100.0/24")
    assert create.prefix == "198.51.100.0/24"

    for bad in ("10.0.0.1/8", "10.0.0.0", "", "not-a-prefix", "10.0.0.0/33"):
        with pytest.raises(ValueError):
            canonical_route_prefix(bad)

    with pytest.raises(ValueError):
        canonical_route_prefix(10)  # type: ignore[arg-type]


def test_prefix_family_mismatch_is_rejected() -> None:
    # Family mismatch on the prefix field reports the prefix loc.
    with pytest.raises(ValidationError) as mismatch:
        _create(family="ipv6", prefix="10.0.0.0/8")
    assert mismatch.value.errors()[0]["loc"] == ("prefix",)
    assert "IPv4" in mismatch.value.errors()[0]["msg"]
    assert "ipv6" in mismatch.value.errors()[0]["msg"]

    with pytest.raises(ValidationError):
        _create(family="ipv4", prefix="2001:db8::/32", next_hops=[_hop(interface="eth0")])

    with pytest.raises(ValidationError):
        StaticRouteRead(family="ipv6", prefix="10.0.0.0/8", next_hops=[_hop()])

    with pytest.raises(ValidationError):
        _create(prefix="10.0.0.1/8")

    with pytest.raises(ValidationError):
        _create(family="ipv5")


def test_next_hop_combinations_and_canonicalisation() -> None:
    assert StaticNextHop(address=" 192.0.2.1 ").address == "192.0.2.1"
    assert StaticNextHop(address="2001:0DB8::1").address == "2001:db8::1"
    assert StaticNextHop(interface="eth0").address is None
    both = StaticNextHop(address="192.0.2.1", interface="eth0.100")
    assert (both.address, both.interface) == ("192.0.2.1", "eth0.100")
    assert both.enabled is True
    assert both.distance is None

    # Blank strings behave like null.
    assert StaticNextHop(address=" ", interface="eth0").address is None
    assert StaticNextHop(address="192.0.2.1", interface="  ").interface is None

    for payload in (
        {},
        {"address": None, "interface": None},
        {"address": "", "interface": ""},
        {"address": "192.0.2.1/32"},
        {"address": "192.0.2.256"},
        {"address": "not-an-address"},
        {"interface": "not a-interface"},
        {"interface": "eth0.100.200"},
        {"address": "192.0.2.1", "distance": 0},
        {"address": "192.0.2.1", "distance": 256},
        {"address": "192.0.2.1", "distance": True},
    ):
        with pytest.raises(ValidationError):
            StaticNextHop.model_validate(payload)

    assert StaticNextHop(address="192.0.2.1", distance=255).distance == 255
    assert StaticNextHop(address="192.0.2.1", distance=1).distance == 1


def test_interface_name_shape() -> None:
    for valid in ("eth0", "eth0.100", "br0", "bond0.42", "wg0", "tun0", "vtun0", "lo", "pod-ab"):
        assert validate_interface_name(f" {valid} ") == valid

    for invalid in ("", "eth", "Eth0", "eth-0", "switch0", "en", "eth0.100.1", "eth 0", "a" * 40):
        with pytest.raises(ValueError):
            validate_interface_name(invalid)

    with pytest.raises(ValueError):
        validate_interface_name(10)  # type: ignore[arg-type]


def test_duplicate_next_hops_are_rejected() -> None:
    with pytest.raises(ValidationError) as duplicate:
        _create(
            next_hops=[
                {"address": "192.0.2.1", "interface": "eth0"},
                {"address": "192.0.2.1", "interface": "eth0"},
            ]
        )
    assert duplicate.value.errors()[0]["loc"] == ("next_hops",)
    assert "Duplicate next hop" in duplicate.value.errors()[0]["msg"]

    with pytest.raises(ValidationError):
        _create(next_hops=[{"address": "192.0.2.1"}, {"address": "192.0.2.1"}])

    with pytest.raises(ValidationError):
        _create(next_hops=[{"interface": "eth0"}, {"interface": "eth0"}])

    # Same address with a different interface, and same interface with a
    # different address, are distinct next hops.
    distinct = _create(
        next_hops=[
            {"address": "192.0.2.1", "interface": "eth0"},
            {"address": "192.0.2.1", "interface": "eth1"},
            {"address": "192.0.2.2", "interface": "eth0"},
            {"interface": "eth2"},
        ]
    )
    assert len(distinct.next_hops) == 4


def test_next_hop_family_must_match_the_route() -> None:
    with pytest.raises(ValidationError) as mismatch:
        _create(
            family="ipv6",
            prefix="2001:db8::/32",
            next_hops=[{"address": "192.0.2.1"}],
        )
    assert mismatch.value.errors()[0]["loc"] == ("next_hops",)
    assert "IPv4" in mismatch.value.errors()[0]["msg"]

    with pytest.raises(ValidationError):
        _create(next_hops=[{"address": "2001:db8::1"}])

    ipv6 = _create(
        family="ipv6",
        prefix="2001:db8::/32",
        next_hops=[{"address": "2001:db8::1", "interface": "eth0"}],
    )
    assert ipv6.next_hops[0].address == "2001:db8::1"


def test_blackhole_and_reject_rules() -> None:
    blackhole = _create(blackhole=True, next_hops=[], distance=255, tag=100)
    assert (blackhole.blackhole, blackhole.reject) == (True, False)
    assert (blackhole.distance, blackhole.tag) == (255, 100)

    reject = _create(reject=True, next_hops=[], distance=None, tag=None)
    assert (reject.blackhole, reject.reject) == (False, True)
    assert reject.next_hops == []

    with pytest.raises(ValidationError):
        _create(blackhole=True, reject=True, next_hops=[])
    with pytest.raises(ValidationError):
        _create(blackhole=True, next_hops=[_hop()])
    with pytest.raises(ValidationError):
        _create(reject=True, next_hops=[{"interface": "eth0"}])
    with pytest.raises(ValidationError):
        _create(next_hops=[_hop()], distance=10)
    with pytest.raises(ValidationError):
        _create(next_hops=[_hop()], tag=10)
    with pytest.raises(ValidationError):
        _create(next_hops=[])

    # Ranges on the discard types.
    for value in (0, 256, True):
        with pytest.raises(ValidationError):
            _create(blackhole=True, next_hops=[], distance=value)
    for value in (0, 4_294_967_296, True):
        with pytest.raises(ValidationError):
            _create(blackhole=True, next_hops=[], tag=value)
    assert _create(blackhole=True, next_hops=[], tag=4_294_967_295).tag == 4_294_967_295


def test_description_length_and_trimming() -> None:
    assert _create(description="  Lab block  ").description == "Lab block"
    assert _create(description="   ").description is None
    assert _create(description=None).description is None
    assert len(_create(description="d" * 255).description or "") == 255
    with pytest.raises(ValidationError):
        _create(description="d" * 256)

    read = StaticRouteRead(
        family="ipv4",
        prefix="10.0.0.0/8",
        description="  spaced ",
        next_hops=[_hop()],
    )
    assert read.description == "spaced"


def test_update_model_is_a_full_replacement_body() -> None:
    update = StaticRouteUpdate(next_hops=[{"address": "198.51.100.1"}])
    assert (update.description, update.blackhole, update.reject) == (None, False, False)
    assert (update.distance, update.tag) == (None, None)

    # A round-tripped read body is accepted; the path stays authoritative.
    round_trip = StaticRouteUpdate.model_validate(
        {
            "family": "ipv4",
            "prefix": "10.0.0.0/8",
            "description": "x",
            "blackhole": True,
            "next_hops": [],
        }
    )
    assert (round_trip.family, round_trip.prefix) == ("ipv4", "10.0.0.0/8")
    assert round_trip.blackhole is True

    with pytest.raises(ValidationError):
        StaticRouteUpdate.model_validate({"prefix": "10.0.0.1/8", "next_hops": [_hop()]})

    with pytest.raises(ValidationError):
        StaticRouteUpdate(blackhole=True, next_hops=[_hop()])


def test_read_and_list_models() -> None:
    read = StaticRouteRead(
        family="ipv6",
        prefix="2001:0DB8::/32",
        blackhole=False,
        reject=True,
        distance=250,
        tag=300,
        next_hops=[],
    )
    assert read.prefix == "2001:db8::/32"
    assert read.distance == 250

    listing = StaticRouteList(items=[read], total=1)
    assert listing.total == 1
    assert StaticRouteList().items == []
    assert StaticRouteList().total == 0


def test_helper_functions() -> None:
    assert canonical_host_address(" 2001:DB8::1 ") == "2001:db8::1"
    with pytest.raises(ValueError):
        canonical_host_address("10.0.0.0/8")

    assert route_type(True, False) == "blackhole"
    assert route_type(False, True) == "reject"
    assert route_type(False, False) == "unicast"
