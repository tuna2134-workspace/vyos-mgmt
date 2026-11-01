"""Service tests for static routes against the in-memory VyOS emulator."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from vyos_mgmt.db.models import Router
from vyos_mgmt.schemas.static_route import (
    StaticNextHop,
    StaticRouteCreate,
    StaticRouteUpdate,
)
from vyos_mgmt.services.static_route_service import (
    STATIC_ROUTE_ROOTS,
    StaticRouteExistsError,
    StaticRouteNotFoundError,
    StaticRouteService,
    StaticRouteValidationError,
    build_create_ops,
    build_delete_ops,
    build_update_ops,
    parse_next_hops,
    parse_static_route,
)
from vyos_mgmt.services.vyos.base import ConfigOp, DeviceTarget
from vyos_mgmt.services.vyos.mock_driver import MockDriver


def make_target() -> DeviceTarget:
    return DeviceTarget(
        id=uuid.uuid4(),
        name="mock-static-routes",
        host="127.0.0.1",
        port=443,
        protocol="https",
        api_key="",
        verify_tls=False,
        driver="mock",
        timeout=1,
    )


async def make_service() -> tuple[StaticRouteService, MockDriver]:
    target = make_target()
    driver = MockDriver(target)
    return StaticRouteService(driver, Router(id=target.id, name="mock-static-routes")), driver


def _route_base(family: str, prefix: str) -> list[str]:
    return [*STATIC_ROUTE_ROOTS[family], prefix]  # type: ignore[index]


async def _raw(driver: MockDriver, family: str, prefix: str) -> dict[str, Any]:
    return await driver.get_config(_route_base(family, prefix))


async def test_list_and_get_seeded_routes() -> None:
    service, _driver = await make_service()

    result = await service.list()
    assert result.total == 9
    assert [(item.family, item.prefix) for item in result.items] == [
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

    by_key = {(item.family, item.prefix): item for item in result.items}

    default = by_key[("ipv4", "0.0.0.0/0")]
    assert default.description == "Default via transit"
    assert (default.blackhole, default.reject) == (False, False)
    assert default.distance is None
    assert default.tag is None
    assert [hop.model_dump() for hop in default.next_hops] == [
        {"address": "192.0.2.254", "interface": None, "distance": None, "enabled": True}
    ]

    multi = by_key[("ipv4", "203.0.113.0/24")]
    # Addressed hops sort before interface-only hops; both are canonical.
    assert [(hop.address, hop.interface) for hop in multi.next_hops] == [
        ("192.0.2.1", "eth0"),
        ("198.51.100.1", None),
    ]
    assert [hop.distance for hop in multi.next_hops] == [10, None]
    assert [hop.enabled for hop in multi.next_hops] == [True, False]

    interface_only = by_key[("ipv4", "192.168.50.0/24")]
    assert interface_only.next_hops[0].address is None
    assert interface_only.next_hops[0].interface == "eth1"

    blackhole = by_key[("ipv4", "10.0.0.0/8")]
    assert (blackhole.blackhole, blackhole.reject) == (True, False)
    assert (blackhole.distance, blackhole.tag) == (255, 100)
    assert blackhole.next_hops == []

    reject = by_key[("ipv4", "172.16.0.0/12")]
    assert (reject.blackhole, reject.reject) == (False, True)
    assert (reject.distance, reject.tag) == (250, 200)

    ipv6_default = by_key[("ipv6", "::/0")]
    assert ipv6_default.next_hops[0].address == "2001:db8:ffff::1"
    ipv6_reject = by_key[("ipv6", "2001:db8:200::/48")]
    assert ipv6_reject.reject is True
    assert (ipv6_reject.distance, ipv6_reject.tag) == (250, 300)

    assert [item.prefix for item in (await service.list("ipv4")).items] == [
        "0.0.0.0/0",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.50.0/24",
        "203.0.113.0/24",
    ]
    assert [item.prefix for item in (await service.list("ipv6")).items] == [
        "::/0",
        "2001:db8:100::/64",
        "2001:db8:200::/48",
        "2001:db8:300::/48",
    ]

    assert (await service.get("ipv4", "10.0.0.0/8")).blackhole is True
    with pytest.raises(StaticRouteValidationError):
        await service.get("ipv6", "10.0.0.0/8")
    with pytest.raises(StaticRouteNotFoundError):
        await service.get("ipv4", "198.51.100.0/24")
    with pytest.raises(StaticRouteValidationError):
        await service.get("ipv4", "10.0.0.1/8")


async def test_parse_next_hops_and_route_helpers() -> None:
    raw = {
        "description": "manual",
        "next-hop": {
            "2001:0DB8::1": {"interface": "eth0", "distance": "20", "disable": {}},
            "2001:db8::2": {},
            "not-an-address": {},
        },
        "interface": {"eth1": {"distance": "30"}},
    }
    hops = parse_next_hops(raw, "ipv6")
    assert [hop.model_dump() for hop in hops] == [
        {
            "address": "2001:db8::1",
            "interface": "eth0",
            "distance": 20,
            "enabled": False,
        },
        {"address": "2001:db8::2", "interface": None, "distance": None, "enabled": True},
        {"address": None, "interface": "eth1", "distance": 30, "enabled": True},
    ]

    # Wrong-family addressed hops are dropped for an IPv4 tree; the
    # interface-only hop has no family and stays.
    assert [hop.interface for hop in parse_next_hops(raw, "ipv4")] == ["eth1"]

    route = parse_static_route("ipv6", "2001:0DB8::/32", raw)
    assert route is not None
    assert route.prefix == "2001:db8::/32"
    assert route.description == "manual"

    assert parse_static_route("ipv4", "2001:db8::/32", raw) is None
    assert parse_static_route("ipv6", "2001:db8::/32", {}) is None
    assert parse_static_route("ipv6", "garbage", raw) is None


async def test_create_update_delete_round_trip() -> None:
    service, driver = await make_service()

    created = await service.create(
        StaticRouteCreate(
            family="ipv4",
            prefix="198.18.0.0/15",
            description="  Lab block  ",
            next_hops=[
                StaticNextHop(address="192.0.2.1", interface="eth0", distance=10),
                StaticNextHop(interface="eth1", enabled=False),
            ],
        )
    )
    assert created.prefix == "198.18.0.0/15"
    assert created.description == "Lab block"
    assert [(hop.address, hop.interface) for hop in created.next_hops] == [
        ("192.0.2.1", "eth0"),
        (None, "eth1"),
    ]
    assert created.next_hops[1].enabled is False

    raw = await _raw(driver, "ipv4", "198.18.0.0/15")
    assert raw == {
        "description": "Lab block",
        "next-hop": {"192.0.2.1": {"interface": "eth0", "distance": "10"}},
        "interface": {"eth1": {"disable": {}}},
    }

    with pytest.raises(StaticRouteExistsError):
        await service.create(
            StaticRouteCreate(
                family="ipv4", prefix="198.18.0.0/15", next_hops=[{"address": "192.0.2.2"}]
            )
        )

    # Re-enabling a retained interface-only hop removes its ``disable`` node.
    reenabled = await service.update(
        "ipv4",
        "198.18.0.0/15",
        StaticRouteUpdate(
            description="Lab block",
            next_hops=[
                {"address": "192.0.2.1", "interface": "eth0", "distance": 10},
                {"interface": "eth1", "distance": 5},
            ],
        ),
    )
    assert reenabled.next_hops[1].enabled is True
    assert reenabled.next_hops[1].distance == 5
    raw = await _raw(driver, "ipv4", "198.18.0.0/15")
    assert raw["interface"]["eth1"] == {"distance": "5"}

    updated = await service.update(
        "ipv4",
        "198.18.0.0/15",
        StaticRouteUpdate(
            description=None,
            next_hops=[{"address": "192.0.2.1", "interface": "eth2", "distance": None}],
        ),
    )
    assert updated.description is None
    assert [(hop.address, hop.interface, hop.distance) for hop in updated.next_hops] == [
        ("192.0.2.1", "eth2", None)
    ]
    raw = await _raw(driver, "ipv4", "198.18.0.0/15")
    assert "description" not in raw
    assert "eth1" not in raw.get("interface", {})
    assert raw["next-hop"]["192.0.2.1"]["interface"] == "eth2"
    assert "distance" not in raw["next-hop"]["192.0.2.1"]

    await service.delete("ipv4", "198.18.0.0/15")
    assert (await service.list("ipv4")).total == 5
    with pytest.raises(StaticRouteNotFoundError):
        await service.get("ipv4", "198.18.0.0/15")
    with pytest.raises(StaticRouteNotFoundError):
        await service.delete("ipv4", "198.18.0.0/15")
    with pytest.raises(StaticRouteNotFoundError):
        await service.update(
            "ipv4", "198.18.0.0/15", StaticRouteUpdate(next_hops=[{"address": "192.0.2.1"}])
        )


async def test_ipv6_create_and_family_validation_on_update() -> None:
    service, _driver = await make_service()

    created = await service.create(
        StaticRouteCreate(
            family="ipv6",
            prefix="2001:DB8:4000::/48",
            next_hops=[{"address": "2001:db8:ffff::2", "distance": 5}],
        )
    )
    assert created.prefix == "2001:db8:4000::/48"
    assert created.next_hops[0].address == "2001:db8:ffff::2"

    # The update body carries no family, so the service enforces it.
    with pytest.raises(StaticRouteValidationError) as mismatch:
        await service.update(
            "ipv6",
            "2001:db8:4000::/48",
            StaticRouteUpdate(next_hops=[{"address": "192.0.2.1"}]),
        )
    assert mismatch.value.field == "next_hops.0.address"
    assert "IPv4" in str(mismatch.value)

    # A prefix from the other family is a validation error, not a lookup miss.
    with pytest.raises(StaticRouteValidationError):
        await service.update(
            "ipv4",
            "2001:db8:4000::/48",
            StaticRouteUpdate(next_hops=[{"address": "192.0.2.1"}]),
        )


async def test_type_transitions_clean_up_obsolete_nodes() -> None:
    service, driver = await make_service()

    created = await service.create(
        StaticRouteCreate(
            family="ipv4",
            prefix="198.19.0.0/16",
            description="transitions",
            next_hops=[
                {"address": "192.0.2.1", "interface": "eth0", "distance": 10},
                {"interface": "eth1", "distance": 20},
            ],
        )
    )
    assert created.next_hops

    # unicast -> blackhole: next-hop and interface tag nodes disappear.
    blackhole = await service.update(
        "ipv4", "198.19.0.0/16", StaticRouteUpdate(blackhole=True, distance=200, tag=7)
    )
    assert blackhole.blackhole is True
    assert (blackhole.distance, blackhole.tag) == (200, 7)
    assert blackhole.next_hops == []
    raw = await _raw(driver, "ipv4", "198.19.0.0/16")
    assert raw == {"blackhole": {"distance": "200", "tag": "7"}}

    # blackhole -> reject replaces the type node and keeps no stale distance.
    rejected = await service.update(
        "ipv4", "198.19.0.0/16", StaticRouteUpdate(reject=True, distance=250, tag=None)
    )
    assert (rejected.blackhole, rejected.reject) == (False, True)
    assert (rejected.distance, rejected.tag) == (250, None)
    raw = await _raw(driver, "ipv4", "198.19.0.0/16")
    assert raw == {"reject": {"distance": "250"}}
    assert "blackhole" not in raw
    assert "tag" not in raw["reject"]

    # reject -> unicast removes the discard node and creates next hops.
    unicast = await service.update(
        "ipv4",
        "198.19.0.0/16",
        StaticRouteUpdate(
            description="back to unicast",
            next_hops=[{"address": "192.0.2.9", "interface": "eth9", "distance": 30}],
        ),
    )
    assert (unicast.blackhole, unicast.reject) == (False, False)
    assert (unicast.distance, unicast.tag) == (None, None)
    assert unicast.description == "back to unicast"
    raw = await _raw(driver, "ipv4", "198.19.0.0/16")
    assert raw == {
        "description": "back to unicast",
        "next-hop": {"192.0.2.9": {"interface": "eth9", "distance": "30"}},
    }
    assert "blackhole" not in raw
    assert "reject" not in raw
    assert "distance" not in raw
    assert "tag" not in raw

    # A stray route-level distance/tag (not allowed by the VyOS schema) is
    # cleaned up by the next unicast update.
    await driver.apply(
        [
            ConfigOp("set", [*_route_base("ipv4", "198.19.0.0/16"), "distance", "99"]),
            ConfigOp("set", [*_route_base("ipv4", "198.19.0.0/16"), "tag", "5"]),
        ]
    )
    assert (await _raw(driver, "ipv4", "198.19.0.0/16"))["distance"] == "99"
    cleaned = await service.update(
        "ipv4",
        "198.19.0.0/16",
        StaticRouteUpdate(
            next_hops=[{"address": "192.0.2.9", "interface": "eth9", "distance": 30}]
        ),
    )
    assert cleaned.prefix == "198.19.0.0/16"
    raw = await _raw(driver, "ipv4", "198.19.0.0/16")
    assert "distance" not in raw
    assert "tag" not in raw

    # unicast -> unicast with an interface-only hop only.
    interface_only = await service.update(
        "ipv4",
        "198.19.0.0/16",
        StaticRouteUpdate(next_hops=[{"interface": "eth3"}]),
    )
    assert interface_only.next_hops[0].interface == "eth3"
    raw = await _raw(driver, "ipv4", "198.19.0.0/16")
    # The mock keeps the emptied ``next-hop`` container; VyOS commits prune it.
    assert raw.get("next-hop", {}) == {}
    assert raw["interface"] == {"eth3": {}}


async def test_update_preserves_unknown_leaves_on_retained_next_hops() -> None:
    service, driver = await make_service()
    await service.create(
        StaticRouteCreate(
            family="ipv4",
            prefix="198.20.0.0/16",
            next_hops=[{"address": "192.0.2.1", "interface": "eth0", "distance": 10}],
        )
    )
    base = _route_base("ipv4", "198.20.0.0/16")
    await driver.apply(
        [
            ConfigOp("set", [*base, "vendor-flag"]),
            ConfigOp("set", [*base, "next-hop", "192.0.2.1", "bfd", "multi-hop"]),
            ConfigOp("set", [*base, "next-hop", "192.0.2.1", "segments", "2001:db8::1"]),
            ConfigOp("set", [*base, "next-hop", "192.0.2.1", "distance", "10"]),
        ]
    )

    updated = await service.update(
        "ipv4",
        "198.20.0.0/16",
        StaticRouteUpdate(
            description="changed",
            next_hops=[{"address": "192.0.2.1", "interface": "eth0", "distance": 20}],
        ),
    )
    assert updated.description == "changed"
    assert updated.next_hops[0].distance == 20

    raw = await _raw(driver, "ipv4", "198.20.0.0/16")
    assert raw["description"] == "changed"
    assert "vendor-flag" in raw
    hop = raw["next-hop"]["192.0.2.1"]
    assert hop["distance"] == "20"
    assert hop["interface"] == "eth0"
    assert "bfd" in hop
    assert hop["segments"] == {"2001:db8::1": {}}

    # Removing the hop removes its subtree; the retained route keeps vendor-flag.
    removed = await service.update(
        "ipv4",
        "198.20.0.0/16",
        StaticRouteUpdate(next_hops=[{"interface": "eth1"}]),
    )
    assert removed.next_hops[0].interface == "eth1"
    raw = await _raw(driver, "ipv4", "198.20.0.0/16")
    assert raw.get("next-hop", {}) == {}
    assert raw["interface"] == {"eth1": {}}
    assert "vendor-flag" in raw


async def test_raw_prefix_keys_are_resolved_for_reads_writes_and_deletes() -> None:
    service, driver = await make_service()

    # The device keeps an uncompressed key; the API still finds it.
    await driver.apply(
        [
            ConfigOp("set", ["protocols", "static", "route6", "2001:0db8:0000:0000::/32"]),
            ConfigOp(
                "set",
                ["protocols", "static", "route6", "2001:0db8:0000:0000::/32", "description", "raw"],
            ),
            ConfigOp(
                "set",
                [
                    "protocols",
                    "static",
                    "route6",
                    "2001:0db8:0000:0000::/32",
                    "next-hop",
                    "2001:0db8:0000:0000:0000:0000:0000:0001",
                ],
            ),
        ]
    )

    route = await service.get("ipv6", "2001:db8::/32")
    assert route.prefix == "2001:db8::/32"
    assert route.description == "raw"

    # Duplicate detection also canonicalises the requested prefix.
    with pytest.raises(StaticRouteExistsError):
        await service.create(
            StaticRouteCreate(
                family="ipv6",
                prefix="2001:db8:0:0::/32",
                next_hops=[{"address": "2001:db8::1"}],
            )
        )

    updated = await service.update(
        "ipv6",
        "2001:db8:0:0::/32",
        StaticRouteUpdate(
            description="canonical request",
            next_hops=[{"address": "2001:db8::1", "distance": 5}],
        ),
    )
    assert updated.description == "canonical request"
    # The raw device key was preserved, not replaced.
    raw = await _raw(driver, "ipv6", "2001:0db8:0000:0000::/32")
    assert raw["description"] == "canonical request"
    # The raw address key is retained and only its distance is touched.
    assert raw["next-hop"] == {"2001:0db8:0000:0000:0000:0000:0000:0001": {"distance": "5"}}

    # IPv4-mapped IPv6 prefixes canonicalise to the dotted-quad form.
    await driver.apply(
        [
            ConfigOp("set", ["protocols", "static", "route6", "::ffff:c000:200/120"]),
            ConfigOp(
                "set",
                ["protocols", "static", "route6", "::ffff:c000:200/120", "blackhole"],
            ),
        ]
    )
    mapped = await service.get("ipv6", "::ffff:192.0.2.0/120")
    assert mapped.prefix == "::ffff:192.0.2.0/120"
    assert mapped.blackhole is True

    await service.delete("ipv6", "2001:0DB8::/32")
    with pytest.raises(StaticRouteNotFoundError):
        await service.get("ipv6", "2001:db8::/32")


async def test_unrepresentable_routes_are_skipped() -> None:
    service, driver = await make_service()
    ipv4 = ["protocols", "static", "route"]
    ipv6 = ["protocols", "static", "route6"]
    await driver.apply(
        [
            # Both discard types at once.
            ConfigOp("set", [*ipv4, "10.99.0.0/16", "blackhole"]),
            ConfigOp("set", [*ipv4, "10.99.0.0/16", "reject"]),
            # A unicast route with no usable next hop.
            ConfigOp("set", [*ipv4, "10.98.0.0/16"]),
            ConfigOp("set", [*ipv4, "10.98.0.0/16", "next-hop", "not-an-address"]),
            ConfigOp("set", [*ipv4, "10.97.0.0/16"]),
            # Wrong family key inside the IPv4 tree.
            ConfigOp("set", [*ipv4, "2001:db8:9999::/48", "blackhole"]),
            # Out-of-range distance is not representable.
            ConfigOp("set", [*ipv4, "10.96.0.0/16", "blackhole", "distance", "999"]),
            # A valid IPv6 route to prove only the bad ones were skipped.
            ConfigOp("set", [*ipv6, "2001:db8:9999::/48", "interface", "eth5"]),
        ]
    )

    listing = await service.list()
    keys = {(item.family, item.prefix) for item in listing.items}
    assert ("ipv4", "10.99.0.0/16") not in keys
    assert ("ipv4", "10.98.0.0/16") not in keys
    assert ("ipv4", "10.97.0.0/16") not in keys
    assert ("ipv4", "2001:db8:9999::/48") not in keys
    assert ("ipv4", "10.96.0.0/16") not in keys
    assert ("ipv6", "2001:db8:9999::/48") in keys
    assert listing.total == 10

    with pytest.raises(StaticRouteNotFoundError):
        await service.get("ipv4", "10.99.0.0/16")


async def test_write_planning_helpers() -> None:
    payload = StaticRouteCreate(
        family="ipv4",
        prefix="198.21.0.0/16",
        description="planned",
        next_hops=[
            {"address": "192.0.2.1", "interface": "eth0", "distance": 10},
            {"interface": "eth1", "enabled": False},
        ],
    )
    create_ops = build_create_ops("ipv4", "198.21.0.0/16", payload)
    assert create_ops[0] == ConfigOp("set", ["protocols", "static", "route", "198.21.0.0/16"])
    paths = [op.path for op in create_ops]
    assert ["protocols", "static", "route", "198.21.0.0/16", "description", "planned"] in paths
    assert [
        "protocols",
        "static",
        "route",
        "198.21.0.0/16",
        "next-hop",
        "192.0.2.1",
        "interface",
        "eth0",
    ] in paths
    assert [
        "protocols",
        "static",
        "route",
        "198.21.0.0/16",
        "next-hop",
        "192.0.2.1",
        "distance",
        "10",
    ] in paths
    assert ["protocols", "static", "route", "198.21.0.0/16", "interface", "eth1"] in paths
    assert [
        "protocols",
        "static",
        "route",
        "198.21.0.0/16",
        "interface",
        "eth1",
        "disable",
    ] in paths

    # No-op updates plan nothing; blackhole is one set and no next hops.
    existing = {
        "description": "planned",
        "next-hop": {"192.0.2.1": {"interface": "eth0", "distance": "10"}},
        "interface": {"eth1": {"disable": {}}},
    }
    assert build_update_ops("ipv4", "198.21.0.0/16", payload, existing) == []

    discard = StaticRouteUpdate(blackhole=True, distance=255, tag=1)
    transition = build_update_ops("ipv4", "198.21.0.0/16", discard, existing)
    assert (
        ConfigOp("set", ["protocols", "static", "route", "198.21.0.0/16", "blackhole"])
        in transition
    )
    assert (
        ConfigOp("delete", ["protocols", "static", "route", "198.21.0.0/16", "next-hop"])
        in transition
    )
    assert (
        ConfigOp("delete", ["protocols", "static", "route", "198.21.0.0/16", "interface"])
        in transition
    )
    assert (
        ConfigOp("delete", ["protocols", "static", "route", "198.21.0.0/16", "description"])
        in transition
    )

    assert build_delete_ops("ipv6", "2001:db8::/32") == [
        ConfigOp("delete", ["protocols", "static", "route6", "2001:db8::/32"])
    ]


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
    service = StaticRouteService(driver, Router(id=target.id, name="mock-static-routes"))

    driver.apply_calls = 0
    await service.create(
        StaticRouteCreate(
            family="ipv4",
            prefix="198.22.0.0/16",
            description="atomic",
            next_hops=[
                {"address": "192.0.2.1", "interface": "eth0", "distance": 10},
                {"interface": "eth1"},
            ],
        )
    )
    assert driver.apply_calls == 1

    driver.apply_calls = 0
    await service.update(
        "ipv4",
        "198.22.0.0/16",
        StaticRouteUpdate(
            description="atomic",
            next_hops=[
                {"address": "192.0.2.1", "interface": "eth0", "distance": 10},
                {"interface": "eth1"},
            ],
        ),
    )
    assert driver.apply_calls == 0

    driver.apply_calls = 0
    await service.update(
        "ipv4",
        "198.22.0.0/16",
        StaticRouteUpdate(blackhole=True, distance=100),
    )
    assert driver.apply_calls == 1

    driver.apply_calls = 0
    await service.update(
        "ipv4",
        "198.22.0.0/16",
        StaticRouteUpdate(next_hops=[{"address": "192.0.2.2"}]),
    )
    assert driver.apply_calls == 1

    driver.apply_calls = 0
    await service.delete("ipv4", "198.22.0.0/16")
    assert driver.apply_calls == 1


async def test_empty_static_tree_is_treated_as_no_routes() -> None:
    service, driver = await make_service()
    await driver.apply([ConfigOp("delete", ["protocols", "static"])])

    assert (await service.list()).items == []
    with pytest.raises(StaticRouteNotFoundError):
        await service.get("ipv4", "0.0.0.0/0")

    created = await service.create(
        StaticRouteCreate(family="ipv4", prefix="10.0.0.0/8", blackhole=True)
    )
    assert created.blackhole is True
    assert (await service.list()).total == 1
