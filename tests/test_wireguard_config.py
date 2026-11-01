"""Unit tests for WireGuard config parsing and atomic write planning."""

from __future__ import annotations

from typing import Any

from vyos_mgmt.schemas.wireguard import (
    WireGuardInterfaceCreate,
    WireGuardInterfaceUpdate,
    WireGuardPeerCreate,
    WireGuardPeerUpdate,
)
from vyos_mgmt.services.wireguard_service import (
    WIREGUARD_ROOT,
    build_interface_create_ops,
    build_interface_delete_ops,
    build_interface_update_ops,
    build_peer_create_ops,
    build_peer_delete_ops,
    build_peer_update_ops,
    build_private_key_update_ops,
    parse_interface,
    parse_interface_detail,
    parse_interfaces,
    parse_peer,
)

PRIVATE_KEY = "iJJyEARGK52Ls1GYRCcFvPuTj7WyWYDo//BknoDU0XY="
PUBLIC_KEY = "EKY0dxRrSD98QHjfHOK13mZ5PJ7hnddRZt5woB3szyw="
OTHER_PUBLIC_KEY = "XMrlPykaxhdAAiSjhtPlvi30NVkvLQliQuKP7AI7CyI="
THIRD_PUBLIC_KEY = "4Krkv8h6NkAYMMaBWI957yYDJDMvj9URTHstdlOcDU0="
PRESHARED_KEY = "OHH2EwZfMNK+1L6BXbYw3bKCtMrfjpR4mCAEeBlFnRs="

RAW: dict[str, Any] = {
    "wg0": {
        "address": {
            "10.100.0.1/24": {},
            "2001:DB8:100::1/64": {},
            "dhcp": {},
        },
        "description": {"Tokyo branch tunnel": {}},
        "port": "51820",
        "mtu": "1420",
        "private-key": PRIVATE_KEY,
        "peer": {
            "z-branch": {
                "description": "Branch router",
                "public-key": PUBLIC_KEY,
                "allowed-ips": {"192.168.50.0/24": {}, "2001:db8:50::/64": {}},
                "host-name": "vpn.example.com",
                "port": "51820",
                "persistent-keepalive": "25",
                "preshared-key": PRESHARED_KEY,
            },
            "a-road-warrior": {
                "public-key": OTHER_PUBLIC_KEY,
                "allowed-ips": ["10.200.0.5/32"],
                "address": "198.51.100.10",
                "disable": {},
            },
            "invalid-peer": {"allowed-ips": {"10.0.0.0/8": {}}},
        },
    }
}


def _set_paths(ops) -> list[list[str]]:
    return [item.path for item in ops if item.op == "set"]


def _delete_paths(ops) -> list[list[str]]:
    return [item.path for item in ops if item.op == "delete"]


def test_parse_interface_derives_public_key_and_hides_private_key() -> None:
    interface = parse_interface("wg0", RAW["wg0"])
    assert interface.name == "wg0"
    assert interface.description == "Tokyo branch tunnel"
    assert interface.addresses == ["10.100.0.1/24", "2001:db8:100::1/64"]
    assert interface.port == 51820
    assert interface.mtu == 1420
    assert interface.enabled is True
    assert interface.public_key is not None
    assert interface.public_key != PRIVATE_KEY
    assert interface.peer_count == 3

    dumped = interface.model_dump()
    assert "private-key" not in dumped
    assert "private_key" not in dumped
    assert PRIVATE_KEY not in str(dumped)


def test_parse_detail_sorts_peers_and_skips_invalid_public_keys() -> None:
    detail = parse_interface_detail("wg0", RAW["wg0"])
    assert [peer.name for peer in detail.peers] == ["a-road-warrior", "z-branch"]
    assert "invalid-peer" not in [peer.name for peer in detail.peers]

    road_warrior = detail.peers[0]
    assert road_warrior.endpoint == "198.51.100.10"
    assert road_warrior.endpoint_port is None
    assert road_warrior.allowed_ips == ["10.200.0.5/32"]
    assert road_warrior.enabled is False
    assert road_warrior.has_preshared_key is False

    branch = detail.peers[1]
    assert branch.endpoint == "vpn.example.com"
    assert branch.endpoint_port == 51820
    assert branch.persistent_keepalive == 25
    assert branch.allowed_ips == ["192.168.50.0/24", "2001:db8:50::/64"]
    assert branch.has_preshared_key is True
    assert branch.enabled is True

    dumped = detail.model_dump()
    assert PRESHARED_KEY not in str(dumped)
    assert PRIVATE_KEY not in str(dumped)


def test_parse_interface_tolerates_address_and_scalar_variants() -> None:
    for address in (
        "10.0.0.1/24",
        ["10.0.0.1/24"],
        {"10.0.0.1/24": {}},
    ):
        parsed = parse_interface("wg1", {"address": address})
        assert parsed.addresses == ["10.0.0.1/24"]

    invalid = parse_interface("wg1", {"address": "dhcp", "private-key": "bad"})
    assert invalid.addresses == []
    assert invalid.public_key is None
    assert invalid.enabled is True
    assert invalid.port is None
    assert invalid.mtu is None


def test_parse_interfaces_filters_invalid_names_and_sorts() -> None:
    raw = {
        "wg10": {},
        "wg2": {},
        "eth0": {},
        "wg": {},
        "wg0": {},
    }
    parsed = parse_interfaces(raw)
    assert [item.name for item in parsed] == ["wg0", "wg10", "wg2"]


def test_parse_peer_returns_none_without_valid_public_key() -> None:
    assert parse_peer("peer", {}) is None
    assert parse_peer("peer", {"public-key": "not-base64"}) is None
    assert parse_peer("peer", {"public-key": PUBLIC_KEY}) is not None


def test_interface_create_ops_set_private_key_and_multi_value_addresses() -> None:
    payload = WireGuardInterfaceCreate(
        name="wg1",
        description="New tunnel",
        addresses=["10.9.0.1/24", "2001:db8:9::1/64"],
        port=51900,
        mtu=1400,
        enabled=False,
        private_key=PRIVATE_KEY,
    )
    ops = build_interface_create_ops(payload)
    paths = _set_paths(ops)
    assert paths[0] == [*WIREGUARD_ROOT, "wg1"]
    assert [*WIREGUARD_ROOT, "wg1", "private-key", PRIVATE_KEY] in paths
    assert [*WIREGUARD_ROOT, "wg1", "address", "10.9.0.1/24"] in paths
    assert [*WIREGUARD_ROOT, "wg1", "address", "2001:db8:9::1/64"] in paths
    assert [*WIREGUARD_ROOT, "wg1", "port", "51900"] in paths
    assert [*WIREGUARD_ROOT, "wg1", "mtu", "1400"] in paths
    assert [*WIREGUARD_ROOT, "wg1", "disable"] in paths


def test_interface_update_syncs_managed_fields_and_preserves_unknown() -> None:
    existing = {
        "description": "Old",
        "address": {"10.0.0.1/24": {}, "10.0.1.1/24": {}, "dhcp": {}},
        "port": "51820",
        "mtu": "1420",
        "private-key": PRIVATE_KEY,
        "fwmark": "42",
        "peer": {"keep-me": {"public-key": PUBLIC_KEY}},
    }
    payload = WireGuardInterfaceUpdate(
        description="New",
        addresses=["10.0.0.1/24", "10.0.2.1/24"],
        port=51900,
        mtu=None,
        enabled=False,
    )
    ops = build_interface_update_ops("wg0", payload, existing)
    sets = _set_paths(ops)
    deletes = _delete_paths(ops)

    assert [*WIREGUARD_ROOT, "wg0", "description", "New"] in sets
    assert [*WIREGUARD_ROOT, "wg0", "address", "10.0.2.1/24"] in sets
    assert [*WIREGUARD_ROOT, "wg0", "address", "10.0.1.1/24"] in deletes
    assert [*WIREGUARD_ROOT, "wg0", "address", "dhcp"] in deletes
    assert [*WIREGUARD_ROOT, "wg0", "port", "51900"] in sets
    assert [*WIREGUARD_ROOT, "wg0", "mtu"] in deletes
    assert [*WIREGUARD_ROOT, "wg0", "disable"] in sets

    touched = [*sets, *deletes]
    assert not any("private-key" in path for path in touched)
    assert not any("peer" in path for path in touched)
    assert not any("fwmark" in path for path in touched)


def test_interface_update_with_no_changes_plans_nothing() -> None:
    existing = {
        "description": "Same",
        "address": {"10.0.0.1/24": {}},
        "port": "51820",
        "mtu": "1420",
    }
    payload = WireGuardInterfaceUpdate(
        description="Same",
        addresses=["10.0.0.1/24"],
        port=51820,
        mtu=1420,
        enabled=True,
    )
    assert build_interface_update_ops("wg0", payload, existing) == []


def test_delete_and_private_key_rotation_ops() -> None:
    assert build_interface_delete_ops("wg0")[0].path == [*WIREGUARD_ROOT, "wg0"]
    rotation = build_private_key_update_ops("wg0", PRIVATE_KEY)
    assert rotation[0].path == [*WIREGUARD_ROOT, "wg0", "private-key", PRIVATE_KEY]


def test_peer_create_ops_map_endpoint_and_multi_value_allowed_ips() -> None:
    payload = WireGuardPeerCreate(
        name="branch",
        description="Branch",
        public_key=PUBLIC_KEY,
        allowed_ips=["192.168.50.0/24", "2001:db8:50::/64"],
        endpoint="198.51.100.10",
        endpoint_port=51820,
        persistent_keepalive=25,
        preshared_key=PRESHARED_KEY,
        enabled=False,
    )
    paths = _set_paths(build_peer_create_ops("wg0", payload))
    base = [*WIREGUARD_ROOT, "wg0", "peer", "branch"]
    assert base in paths
    assert [*base, "public-key", PUBLIC_KEY] in paths
    assert [*base, "allowed-ips", "192.168.50.0/24"] in paths
    assert [*base, "allowed-ips", "2001:db8:50::/64"] in paths
    assert [*base, "address", "198.51.100.10"] in paths
    assert [*base, "host-name"] not in paths
    assert [*base, "port", "51820"] in paths
    assert [*base, "persistent-keepalive", "25"] in paths
    assert [*base, "preshared-key", PRESHARED_KEY] in paths
    assert [*base, "disable"] in paths

    fqdn = WireGuardPeerCreate(
        name="rw",
        public_key=PUBLIC_KEY,
        allowed_ips=["10.200.0.5/32"],
        endpoint="vpn.example.com",
    )
    fqdn_paths = _set_paths(build_peer_create_ops("wg0", fqdn))
    assert [*base[:4], "rw", "host-name", "vpn.example.com"] in fqdn_paths
    assert not any(path[-2:-1] == ["address"] for path in fqdn_paths)


def test_peer_update_switches_endpoint_and_preserves_unknown_fields() -> None:
    existing = {
        "description": "Old",
        "public-key": PUBLIC_KEY,
        "allowed-ips": {"10.0.0.0/8": {}, "192.168.0.0/16": {}},
        "host-name": "old.example.com",
        "persistent-keepalive": "25",
        "preshared-key": PRESHARED_KEY,
        "fwmark": "7",
    }
    payload = WireGuardPeerUpdate(
        public_key=OTHER_PUBLIC_KEY,
        allowed_ips=["10.0.0.0/8"],
        endpoint="198.51.100.20",
        endpoint_port=51900,
        persistent_keepalive=None,
        enabled=False,
    )
    ops = build_peer_update_ops("wg0", "peer", payload, existing)
    sets = _set_paths(ops)
    deletes = _delete_paths(ops)
    base = [*WIREGUARD_ROOT, "wg0", "peer", "peer"]

    assert [*base, "public-key", OTHER_PUBLIC_KEY] in sets
    assert [*base, "allowed-ips", "192.168.0.0/16"] in deletes
    assert [*base, "address", "198.51.100.20"] in sets
    assert [*base, "host-name"] in deletes
    assert [*base, "port", "51900"] in sets
    assert [*base, "persistent-keepalive"] in deletes
    assert [*base, "disable"] in sets
    assert not any("fwmark" in path for path in [*sets, *deletes])
    # Omitted preshared_key preserves the existing secret.
    assert not any("preshared-key" in path for path in [*sets, *deletes])


def test_peer_update_preshared_key_replace_and_remove() -> None:
    existing = {"public-key": PUBLIC_KEY, "allowed-ips": {"10.0.0.0/8": {}}}
    replace = WireGuardPeerUpdate(
        public_key=PUBLIC_KEY,
        allowed_ips=["10.0.0.0/8"],
        preshared_key=PRESHARED_KEY,
    )
    replace_paths = _set_paths(build_peer_update_ops("wg0", "peer", replace, existing))
    assert [
        *WIREGUARD_ROOT,
        "wg0",
        "peer",
        "peer",
        "preshared-key",
        PRESHARED_KEY,
    ] in replace_paths

    remove = WireGuardPeerUpdate(
        public_key=PUBLIC_KEY,
        allowed_ips=["10.0.0.0/8"],
        preshared_key=None,
    )
    remove_ops = build_peer_update_ops(
        "wg0", "peer", remove, {**existing, "preshared-key": PRESHARED_KEY}
    )
    assert [*WIREGUARD_ROOT, "wg0", "peer", "peer", "preshared-key"] in _delete_paths(remove_ops)


def test_peer_delete_ops() -> None:
    assert build_peer_delete_ops("wg0", "peer")[0].path == [
        *WIREGUARD_ROOT,
        "wg0",
        "peer",
        "peer",
    ]
