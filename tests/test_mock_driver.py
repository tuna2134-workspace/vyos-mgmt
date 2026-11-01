"""Unit tests for the in-memory VyOS emulator."""

from __future__ import annotations

import uuid

import pytest

from vyos_mgmt.db.models import RouterDriver
from vyos_mgmt.services.vyos.base import ConfigOp, DeviceTarget, VyosCommandError
from vyos_mgmt.services.vyos.mock_driver import MockDriver


def make_target() -> DeviceTarget:
    return DeviceTarget(
        id=uuid.uuid4(),
        name="mock-edge",
        host="127.0.0.1",
        port=443,
        protocol="https",
        api_key="",
        verify_tls=False,
        driver="mock",
        timeout=1,
    )


async def test_seeded_configuration() -> None:
    driver = MockDriver(make_target())
    bgp = await driver.get_config(["protocols", "bgp"])
    assert bgp["system-as"] == "64512"
    assert bgp["parameters"]["router-id"] == "10.255.0.1"
    assert await driver.get_config(["system", "host-name"]) == "mock-edge"


async def test_set_and_delete_leaf_values() -> None:
    driver = MockDriver(make_target())
    await driver.apply(
        [
            ConfigOp("set", ["protocols", "bgp", "neighbor", "192.0.2.9", "remote-as", "65100"]),
            ConfigOp(
                "set",
                ["protocols", "bgp", "neighbor", "192.0.2.9", "description", "New peer"],
            ),
            ConfigOp(
                "set",
                ["protocols", "bgp", "neighbor", "192.0.2.9", "timers", "keepalive", "30"],
            ),
            ConfigOp(
                "set",
                ["protocols", "bgp", "neighbor", "192.0.2.9", "timers", "holdtime", "90"],
            ),
            ConfigOp("set", ["protocols", "bgp", "neighbor", "192.0.2.9", "passive"]),
        ]
    )
    neighbor = await driver.get_config(["protocols", "bgp", "neighbor", "192.0.2.9"])
    assert neighbor["remote-as"] == "65100"
    assert neighbor["description"] == "New peer"
    assert neighbor["timers"] == {"keepalive": "30", "holdtime": "90"}
    assert neighbor["passive"] == {}

    await driver.apply(
        [
            ConfigOp(
                "delete",
                ["protocols", "bgp", "neighbor", "192.0.2.9", "description"],
            ),
            ConfigOp("delete", ["protocols", "bgp", "neighbor", "192.0.2.9", "timers"]),
        ]
    )
    neighbor = await driver.get_config(["protocols", "bgp", "neighbor", "192.0.2.9"])
    assert "description" not in neighbor
    assert "timers" not in neighbor
    assert neighbor["remote-as"] == "65100"


async def test_apply_is_atomic() -> None:
    driver = MockDriver(make_target())
    before = await driver.get_config(["protocols", "bgp"])
    with pytest.raises(VyosCommandError):
        await driver.apply(
            [
                ConfigOp(
                    "set",
                    ["protocols", "bgp", "neighbor", "192.0.2.9", "remote-as", "65100"],
                ),
                ConfigOp("set", ["invalid"]),
            ]
        )
    assert await driver.get_config(["protocols", "bgp"]) == before


async def test_bgp_status_and_system_info() -> None:
    driver = MockDriver(make_target())
    status = await driver.get_bgp_status()
    assert status.configured is True
    assert status.router_id == "10.255.0.1"
    assert status.local_as == 64512
    assert status.total_peers == 3
    assert status.established_peers == 2

    info = await driver.get_system_info()
    assert info.hostname == "mock-edge"
    assert info.driver is RouterDriver.MOCK
    assert info.reachable is True
    assert info.version is not None
    assert info.uptime == "14d 03h 12m"


async def test_shutdown_neighbor_is_not_established() -> None:
    driver = MockDriver(make_target())
    await driver.apply([ConfigOp("set", ["protocols", "bgp", "neighbor", "192.0.2.1", "shutdown"])])
    status = await driver.get_bgp_status()
    peer = next(item for item in status.peers if item.address == "192.0.2.1")
    assert peer.established is False
    assert peer.state == "Idle (Admin)"
    assert status.established_peers == 1


async def test_unsupported_show_command() -> None:
    driver = MockDriver(make_target())
    with pytest.raises(VyosCommandError):
        await driver.show(["interfaces"])


async def test_reset_clears_trees() -> None:
    target = make_target()
    driver = MockDriver(target)
    await driver.apply(
        [
            ConfigOp("delete", ["protocols", "bgp"]),
            ConfigOp("delete", ["protocols", "ospf"]),
            ConfigOp("delete", ["protocols", "ospfv3"]),
            ConfigOp("delete", ["protocols", "static"]),
        ]
    )
    assert (await driver.get_config(["protocols"])) == {}
    MockDriver.reset()
    fresh = MockDriver(target)
    assert (await fresh.get_config(["protocols", "bgp"]))["system-as"] == "64512"


async def test_seeded_route_maps_and_bgp_binding() -> None:
    driver = MockDriver(make_target())

    route_maps = await driver.get_config(["policy", "route-map"])
    assert set(route_maps) == {"BGP-IN", "BGP-OUT", "LOCAL-PREF", "OSPF-OUT"}
    assert route_maps["BGP-IN"]["description"] == "Inbound filtering for transit"
    assert route_maps["BGP-IN"]["rule"]["10"]["action"] == "permit"
    assert route_maps["BGP-IN"]["rule"]["10"]["on-match"] == {"next": {}}
    assert route_maps["BGP-IN"]["rule"]["10"]["match"]["ip"]["address"]["prefix-list"] == (
        "TRANSIT-IN"
    )
    assert route_maps["BGP-IN"]["rule"]["10"]["set"]["community"]["add"] == {"64512:100": {}}
    assert route_maps["LOCAL-PREF"]["rule"]["10"]["call"] == "BGP-OUT"

    bgp = await driver.get_config(["protocols", "bgp"])
    route_map = bgp["neighbor"]["192.0.2.1"]["address-family"]["ipv4-unicast"]["route-map"]
    assert route_map == {"import": "BGP-IN", "export": "BGP-OUT"}


async def test_seeded_prefix_lists_and_leaf_semantics() -> None:
    driver = MockDriver(make_target())

    policy = await driver.get_config(["policy"])
    assert set(policy["prefix-list"]) == {"TRANSIT-IN", "TRANSIT-BOGONS"}
    assert policy["prefix-list"]["TRANSIT-IN"]["rule"]["10"]["prefix"] == "203.0.113.0/24"
    assert policy["prefix-list"]["TRANSIT-IN"]["rule"]["10"]["ge"] == "24"
    assert policy["prefix-list6"]["TRANSIT-V6"]["rule"]["10"]["le"] == "64"

    base = ["policy", "prefix-list"]
    await driver.apply(
        [
            ConfigOp("set", [*base, "NEW-LIST"]),
            ConfigOp("set", [*base, "NEW-LIST", "description", "New list"]),
            ConfigOp("set", [*base, "NEW-LIST", "rule", "10"]),
            ConfigOp("set", [*base, "NEW-LIST", "rule", "10", "action", "permit"]),
            ConfigOp("set", [*base, "NEW-LIST", "rule", "10", "prefix", "203.0.113.0/24"]),
            ConfigOp("set", [*base, "NEW-LIST", "rule", "10", "ge", "24"]),
            ConfigOp("set", [*base, "NEW-LIST", "rule", "10", "le", "32"]),
        ]
    )
    policy = await driver.get_config(["policy"])
    # The list name is a container, not a replacement for the prefix-list tree.
    assert "TRANSIT-IN" in policy["prefix-list"]
    assert policy["prefix-list"]["NEW-LIST"]["rule"]["10"] == {
        "action": "permit",
        "prefix": "203.0.113.0/24",
        "ge": "24",
        "le": "32",
    }

    await driver.apply(
        [
            ConfigOp("delete", [*base, "NEW-LIST", "rule", "10", "le"]),
            ConfigOp("delete", [*base, "NEW-LIST"]),
        ]
    )
    policy = await driver.get_config(["policy"])
    assert set(policy["prefix-list"]) == {"TRANSIT-IN", "TRANSIT-BOGONS"}


async def test_route_map_multi_value_leaf_semantics() -> None:
    driver = MockDriver(make_target())
    rule_base = ["policy", "route-map", "LOCAL-PREF", "rule", "20"]
    await driver.apply(
        [
            ConfigOp("set", [*rule_base, "action", "permit"]),
            ConfigOp("set", [*rule_base, "set", "as-path", "prepend", "64512"]),
            ConfigOp("set", [*rule_base, "set", "as-path", "prepend", "64513"]),
            ConfigOp("set", [*rule_base, "set", "community", "add", "64512:100"]),
            ConfigOp("set", [*rule_base, "set", "community", "add", "no-export"]),
            ConfigOp("set", [*rule_base, "set", "community", "none"]),
            ConfigOp("set", [*rule_base, "on-match", "goto", "30"]),
        ]
    )
    rule = await driver.get_config(rule_base)
    assert rule["action"] == "permit"
    assert rule["set"]["as-path"]["prepend"] == {"64512": {}, "64513": {}}
    assert rule["set"]["community"]["add"] == {"64512:100": {}, "no-export": {}}
    assert rule["set"]["community"]["none"] == {}
    assert rule["on-match"] == {"goto": "30"}

    await driver.apply(
        [
            ConfigOp("delete", [*rule_base, "set", "as-path", "prepend", "64513"]),
            ConfigOp("delete", [*rule_base, "set", "community", "add"]),
            ConfigOp("delete", [*rule_base, "on-match"]),
        ]
    )
    rule = await driver.get_config(rule_base)
    assert rule["set"]["as-path"]["prepend"] == {"64512": {}}
    assert "add" not in rule["set"]["community"]
    assert "on-match" not in rule


async def test_ospf_leaf_and_tag_node_semantics() -> None:
    driver = MockDriver(make_target())

    await driver.apply(
        [
            ConfigOp("set", ["protocols", "ospf", "interface", "eth9", "area", "0.0.0.5"]),
            ConfigOp(
                "set",
                ["protocols", "ospf", "interface", "eth9", "network", "broadcast"],
            ),
            ConfigOp(
                "set",
                ["protocols", "ospf", "area", "0.0.0.5", "area-type", "stub", "no-summary"],
            ),
            ConfigOp(
                "set",
                ["protocols", "ospf", "redistribute", "static", "route-map", "OSPF-OUT"],
            ),
            ConfigOp("set", ["protocols", "ospf", "auto-cost", "reference-bandwidth", "1000"]),
            ConfigOp("set", ["protocols", "ospf", "distance", "global", "110"]),
            ConfigOp("set", ["policy", "route-map", "NEW-MAP"]),
            ConfigOp("set", ["policy", "route-map", "NEW-MAP", "description", "New map"]),
            ConfigOp(
                "set",
                [
                    "protocols",
                    "bgp",
                    "address-family",
                    "ipv4-unicast",
                    "network",
                    "198.51.100.0/24",
                ],
            ),
        ]
    )

    ospf = await driver.get_config(["protocols", "ospf"])
    # The area is a leaf on the interface but a tag node under the protocol.
    assert ospf["interface"]["eth9"]["area"] == "0.0.0.5"
    assert ospf["interface"]["eth9"]["network"] == "broadcast"
    assert ospf["area"]["0.0.0.5"] == {"area-type": {"stub": {"no-summary": {}}}}
    # The route map is a leaf under redistribute but a tag node under policy.
    assert ospf["redistribute"]["static"]["route-map"] == "OSPF-OUT"
    assert ospf["auto-cost"]["reference-bandwidth"] == "1000"
    assert ospf["distance"]["global"] == "110"

    policy = await driver.get_config(["policy"])
    assert policy["route-map"]["NEW-MAP"] == {"description": "New map"}
    bgp_network = await driver.get_config(
        ["protocols", "bgp", "address-family", "ipv4-unicast", "network"]
    )
    assert "198.51.100.0/24" in bgp_network

    # Deleting one interface keeps the other interfaces intact.
    await driver.apply(
        [
            ConfigOp("set", ["protocols", "ospf", "interface", "eth8", "area", "0.0.0.5"]),
            ConfigOp("delete", ["protocols", "ospf", "interface", "eth8"]),
        ]
    )
    interfaces = await driver.get_config(["protocols", "ospf", "interface"])
    assert "eth8" not in interfaces
    assert "eth9" in interfaces
    assert "eth0" in interfaces


async def test_ospf_neighbor_show_output() -> None:
    driver = MockDriver(make_target())

    v2 = await driver.show(["ip", "ospf", "neighbor"])
    assert "Neighbor ID" in v2
    assert "Full/DR" in v2
    assert "eth0" in v2
    v3 = await driver.show(["ipv6", "ospfv3", "neighbor"])
    assert "2-Way/DROther" in v3
    assert "fe80::" in v3

    await driver.apply(
        [
            ConfigOp("delete", ["protocols", "ospf"]),
            ConfigOp("delete", ["protocols", "ospfv3"]),
        ]
    )
    assert "not running" in await driver.show(["ip", "ospf", "neighbor"])
    assert "not running" in await driver.show(["ipv6", "ospfv3", "neighbor"])
