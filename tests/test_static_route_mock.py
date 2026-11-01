"""Unit tests for the mock driver's static-route tree semantics."""

from __future__ import annotations

import uuid

from vyos_mgmt.services.vyos.base import ConfigOp, DeviceTarget
from vyos_mgmt.services.vyos.mock_driver import MockDriver


def make_target() -> DeviceTarget:
    return DeviceTarget(
        id=uuid.uuid4(),
        name="mock-static",
        host="127.0.0.1",
        port=443,
        protocol="https",
        api_key="",
        verify_tls=False,
        driver="mock",
        timeout=1,
    )


async def test_seeded_static_routes_are_realistic() -> None:
    driver = MockDriver(make_target())
    static = await driver.get_config(["protocols", "static"])

    assert set(static) == {"route", "route6"}
    ipv4 = static["route"]
    assert set(ipv4) == {
        "0.0.0.0/0",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.50.0/24",
        "203.0.113.0/24",
    }
    # Default route via a gateway.
    assert ipv4["0.0.0.0/0"]["next-hop"] == {"192.0.2.254": {}}
    # Interface-only route: ``interface`` under a route is a tag node.
    assert ipv4["192.168.50.0/24"]["interface"] == {"eth1": {}}
    # Blackhole/reject carry distance and tag inside the type node.
    assert ipv4["10.0.0.0/8"]["blackhole"] == {"distance": "255", "tag": "100"}
    assert ipv4["172.16.0.0/12"]["reject"] == {"distance": "250", "tag": "200"}
    # An address next hop with interface, distance and a disabled sibling.
    next_hops = ipv4["203.0.113.0/24"]["next-hop"]
    assert next_hops["192.0.2.1"] == {"interface": "eth0", "distance": "10"}
    assert next_hops["198.51.100.1"] == {"disable": {}}

    ipv6 = static["route6"]
    assert ipv6["::/0"]["next-hop"] == {"2001:db8:ffff::1": {}}
    assert ipv6["2001:db8:200::/48"]["reject"] == {"distance": "250", "tag": "300"}
    assert ipv6["2001:db8:300::/48"]["interface"] == {"eth1": {}}


async def test_static_route_set_and_delete_semantics() -> None:
    driver = MockDriver(make_target())
    base = ["protocols", "static", "route", "198.18.0.0/15"]

    await driver.apply(
        [
            ConfigOp("set", base),
            ConfigOp("set", [*base, "description", "Lab block"]),
            # Address next hop: ``next-hop`` is a tag node, ``interface`` a leaf.
            ConfigOp("set", [*base, "next-hop", "192.0.2.1"]),
            ConfigOp("set", [*base, "next-hop", "192.0.2.1", "interface", "eth0"]),
            ConfigOp("set", [*base, "next-hop", "192.0.2.1", "distance", "10"]),
            ConfigOp("set", [*base, "next-hop", "192.0.2.2", "disable"]),
            # Interface-only next hop: ``interface`` is a tag node here.
            ConfigOp("set", [*base, "interface", "eth1"]),
            ConfigOp("set", [*base, "interface", "eth1", "distance", "20"]),
        ]
    )

    route = await driver.get_config(base)
    assert route == {
        "description": "Lab block",
        "next-hop": {
            "192.0.2.1": {"interface": "eth0", "distance": "10"},
            "192.0.2.2": {"disable": {}},
        },
        "interface": {"eth1": {"distance": "20"}},
    }

    # An address next hop's interface is a scalar leaf, not a tag node.
    assert route["next-hop"]["192.0.2.1"]["interface"] == "eth0"

    await driver.apply(
        [
            ConfigOp("delete", [*base, "next-hop", "192.0.2.2"]),
            ConfigOp("delete", [*base, "interface", "eth1"]),
        ]
    )
    route = await driver.get_config(base)
    assert set(route["next-hop"]) == {"192.0.2.1"}
    assert route["interface"] == {}


async def test_static_route_discard_nodes() -> None:
    driver = MockDriver(make_target())
    base = ["protocols", "static", "route6", "2001:db8:4000::/48"]

    await driver.apply(
        [
            ConfigOp("set", base),
            ConfigOp("set", [*base, "blackhole"]),
            ConfigOp("set", [*base, "blackhole", "distance", "200"]),
            ConfigOp("set", [*base, "blackhole", "tag", "700"]),
        ]
    )
    route = await driver.get_config(base)
    assert route == {"blackhole": {"distance": "200", "tag": "700"}}

    await driver.apply(
        [
            ConfigOp("delete", [*base, "blackhole"]),
            ConfigOp("set", [*base, "reject"]),
            ConfigOp("set", [*base, "reject", "distance", "250"]),
        ]
    )
    route = await driver.get_config(base)
    assert route == {"reject": {"distance": "250"}}


async def test_ospf_distance_remains_a_tag_node() -> None:
    """Adding the static-route ``distance`` leaf must not break OSPF."""

    driver = MockDriver(make_target())
    await driver.apply(
        [
            ConfigOp("set", ["protocols", "ospf", "distance", "global", "120"]),
            ConfigOp(
                "set",
                ["protocols", "static", "route", "10.0.0.0/8", "blackhole", "distance", "120"],
            ),
        ]
    )
    ospf = await driver.get_config(["protocols", "ospf"])
    assert ospf["distance"] == {"global": "120"}

    static = await driver.get_config(["protocols", "static", "route", "10.0.0.0/8"])
    assert static["blackhole"]["distance"] == "120"


async def test_deleting_static_tree() -> None:
    driver = MockDriver(make_target())
    await driver.apply([ConfigOp("delete", ["protocols", "static"])])
    assert "static" not in await driver.get_config(["protocols"])
