"""Mock-driver tests for the WireGuard configuration and operational output."""

from __future__ import annotations

import base64
import uuid

import pytest

from vyos_mgmt.services.vyos.base import ConfigOp, DeviceTarget, VyosCommandError, VyosPathNotFound
from vyos_mgmt.services.vyos.mock_driver import (
    WIREGUARD_SEED_PRESHARED_KEY,
    WIREGUARD_SEED_PRIVATE_KEY,
    MockDriver,
)


def make_target() -> DeviceTarget:
    return DeviceTarget(
        id=uuid.uuid4(),
        name="mock-wireguard",
        host="127.0.0.1",
        port=443,
        protocol="https",
        api_key="",
        verify_tls=False,
        driver="mock",
        timeout=1,
    )


def _assert_valid_key(value: str) -> None:
    assert len(base64.b64decode(value, validate=True)) == 32


async def test_seeded_wireguard_configuration() -> None:
    driver = MockDriver(make_target())
    wireguard = await driver.get_config(["interfaces", "wireguard"])
    assert set(wireguard) == {"wg0"}
    wg0 = wireguard["wg0"]
    assert wg0["description"] == "Tokyo branch tunnel"
    assert wg0["port"] == "51820"
    assert wg0["mtu"] == "1420"
    assert set(wg0["address"]) == {"10.100.0.1/24", "2001:db8:100::1/64"}
    assert wg0["private-key"] == WIREGUARD_SEED_PRIVATE_KEY
    _assert_valid_key(wg0["private-key"])

    peers = wg0["peer"]
    assert set(peers) == {"branch-office", "road-warrior"}
    branch = peers["branch-office"]
    assert branch["address"] == "198.51.100.10"
    assert branch["port"] == "51820"
    assert branch["persistent-keepalive"] == "25"
    assert branch["preshared-key"] == WIREGUARD_SEED_PRESHARED_KEY
    assert set(branch["allowed-ips"]) == {"192.168.50.0/24", "192.168.60.0/24"}
    _assert_valid_key(branch["public-key"])
    _assert_valid_key(branch["preshared-key"])

    road_warrior = peers["road-warrior"]
    assert "address" not in road_warrior
    assert set(road_warrior["allowed-ips"]) == {"10.200.0.5/32"}
    _assert_valid_key(road_warrior["public-key"])


async def test_wireguard_leaf_and_multi_value_semantics() -> None:
    driver = MockDriver(make_target())
    base = ["interfaces", "wireguard"]
    await driver.apply(
        [
            ConfigOp("set", [*base, "wg1"]),
            ConfigOp("set", [*base, "wg1", "private-key", WIREGUARD_SEED_PRIVATE_KEY]),
            ConfigOp("set", [*base, "wg1", "port", "51900"]),
            ConfigOp("set", [*base, "wg1", "mtu", "1400"]),
            ConfigOp("set", [*base, "wg1", "description", "New tunnel"]),
            # Interface address is multi-value: one child key per CIDR.
            ConfigOp("set", [*base, "wg1", "address", "10.9.0.1/24"]),
            ConfigOp("set", [*base, "wg1", "address", "2001:db8:9::1/64"]),
            ConfigOp("set", [*base, "wg1", "peer", "peer-one"]),
            ConfigOp(
                "set",
                [*base, "wg1", "peer", "peer-one", "public-key", WIREGUARD_SEED_PRIVATE_KEY],
            ),
            # Peer address is a scalar endpoint.
            ConfigOp(
                "set",
                [*base, "wg1", "peer", "peer-one", "address", "203.0.113.9"],
            ),
            ConfigOp(
                "set",
                [*base, "wg1", "peer", "peer-one", "host-name", "vpn.example.com"],
            ),
            # Allowed IPs are multi-value.
            ConfigOp(
                "set",
                [*base, "wg1", "peer", "peer-one", "allowed-ips", "10.9.0.2/32"],
            ),
            ConfigOp(
                "set",
                [*base, "wg1", "peer", "peer-one", "allowed-ips", "2001:db8:9::2/128"],
            ),
            ConfigOp(
                "set",
                [*base, "wg1", "peer", "peer-one", "persistent-keepalive", "25"],
            ),
            ConfigOp("set", [*base, "wg1", "peer", "peer-one", "disable"]),
        ]
    )

    wg1 = await driver.get_config([*base, "wg1"])
    assert wg1["address"] == {"10.9.0.1/24": {}, "2001:db8:9::1/64": {}}
    assert wg1["port"] == "51900"
    assert wg1["mtu"] == "1400"
    assert wg1["description"] == "New tunnel"
    assert wg1["private-key"] == WIREGUARD_SEED_PRIVATE_KEY
    peer = wg1["peer"]["peer-one"]
    assert peer["address"] == "203.0.113.9"
    assert peer["host-name"] == "vpn.example.com"
    assert peer["allowed-ips"] == {"10.9.0.2/32": {}, "2001:db8:9::2/128": {}}
    assert peer["persistent-keepalive"] == "25"
    assert peer["disable"] == {}

    # Per-value deletion leaves the other values intact.
    await driver.apply(
        [
            ConfigOp("delete", [*base, "wg1", "address", "10.9.0.1/24"]),
            ConfigOp("delete", [*base, "wg1", "peer", "peer-one", "allowed-ips", "10.9.0.2/32"]),
            ConfigOp("delete", [*base, "wg1", "peer", "peer-one", "address"]),
        ]
    )
    wg1 = await driver.get_config([*base, "wg1"])
    assert set(wg1["address"]) == {"2001:db8:9::1/64"}
    assert set(wg1["peer"]["peer-one"]["allowed-ips"]) == {"2001:db8:9::2/128"}
    assert "address" not in wg1["peer"]["peer-one"]


async def test_wireguard_summary_is_generated_from_config() -> None:
    driver = MockDriver(make_target())
    output = await driver.show(["interfaces", "wireguard", "wg0", "summary"])
    assert "interface: wg0" in output
    assert "private key: (hidden)" in output
    assert "listening port: 51820" in output
    assert "peer: " in output
    assert "endpoint: 198.51.100.10:51820" in output
    assert "allowed ips: 192.168.50.0/24, 192.168.60.0/24" in output
    assert "latest handshake:" in output
    assert "received," in output and "sent" in output
    assert WIREGUARD_SEED_PRIVATE_KEY not in output
    assert WIREGUARD_SEED_PRESHARED_KEY not in output

    # A newly configured peer appears immediately.
    await driver.apply(
        [
            ConfigOp("set", ["interfaces", "wireguard", "wg0", "peer", "new-peer"]),
            ConfigOp(
                "set",
                [
                    "interfaces",
                    "wireguard",
                    "wg0",
                    "peer",
                    "new-peer",
                    "public-key",
                    WIREGUARD_SEED_PRIVATE_KEY,
                ],
            ),
            ConfigOp(
                "set",
                [
                    "interfaces",
                    "wireguard",
                    "wg0",
                    "peer",
                    "new-peer",
                    "allowed-ips",
                    "10.0.0.0/8",
                ],
            ),
        ]
    )
    updated = await driver.show(["interfaces", "wireguard", "wg0", "summary"])
    assert "peer: " + WIREGUARD_SEED_PRIVATE_KEY in updated
    assert "allowed ips: 10.0.0.0/8" in updated


async def test_wireguard_summary_errors_for_missing_or_disabled_interface() -> None:
    driver = MockDriver(make_target())
    with pytest.raises(VyosPathNotFound):
        await driver.show(["interfaces", "wireguard", "wg9", "summary"])

    await driver.apply([ConfigOp("set", ["interfaces", "wireguard", "wg0", "disable"])])
    with pytest.raises(VyosCommandError) as exc_info:
        await driver.show(["interfaces", "wireguard", "wg0", "summary"])
    assert "disabled" in str(exc_info.value)


async def test_delete_interface_removes_wireguard_tree() -> None:
    driver = MockDriver(make_target())
    await driver.apply([ConfigOp("delete", ["interfaces", "wireguard", "wg0"])])
    assert await driver.get_config(["interfaces", "wireguard"]) == {}
    with pytest.raises(VyosPathNotFound):
        await driver.get_config(["interfaces", "wireguard", "wg0"])
