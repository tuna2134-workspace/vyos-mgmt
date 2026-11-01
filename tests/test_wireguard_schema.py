"""Unit tests for WireGuard schemas and value validators."""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from vyos_mgmt.schemas.wireguard import (
    WireGuardInterfaceCreate,
    WireGuardInterfaceDetail,
    WireGuardInterfaceRead,
    WireGuardInterfaceUpdate,
    WireGuardKeypair,
    WireGuardPeerCreate,
    WireGuardPeerRead,
    WireGuardPeerUpdate,
    WireGuardPresharedKey,
    WireGuardPrivateKeyUpdate,
    WireGuardStatus,
    WireGuardStatusPeer,
    canonical_allowed_ip,
    canonical_interface_address,
    canonical_wireguard_key,
    validate_endpoint,
    validate_wireguard_interface_name,
    validate_wireguard_peer_name,
)

PRIVATE_KEY = "iJJyEARGK52Ls1GYRCcFvPuTj7WyWYDo//BknoDU0XY="
PUBLIC_KEY = "EKY0dxRrSD98QHjfHOK13mZ5PJ7hnddRZt5woB3szyw="
OTHER_PUBLIC_KEY = "XMrlPykaxhdAAiSjhtPlvi30NVkvLQliQuKP7AI7CyI="
PRESHARED_KEY = "OHH2EwZfMNK+1L6BXbYw3bKCtMrfjpR4mCAEeBlFnRs="

INTERFACE_BODY = {
    "name": "wg0",
    "description": "Tokyo branch tunnel",
    "addresses": ["10.100.0.1/24"],
    "port": 51820,
    "mtu": 1420,
    "enabled": True,
    "private_key": PRIVATE_KEY,
}
PEER_BODY = {
    "name": "branch-office",
    "description": "Branch router",
    "public_key": PUBLIC_KEY,
    "allowed_ips": ["192.168.50.0/24"],
    "endpoint": "198.51.100.10",
    "endpoint_port": 51820,
    "persistent_keepalive": 25,
    "preshared_key": PRESHARED_KEY,
    "enabled": True,
}


def test_interface_create_canonicalises_values() -> None:
    payload = WireGuardInterfaceCreate.model_validate(
        {
            **INTERFACE_BODY,
            "description": "  Tokyo branch tunnel  ",
            "addresses": ["10.100.0.1/24", "2001:DB8:100::1/64", "10.100.0.1/24"],
        }
    )
    assert payload.name == "wg0"
    assert payload.description == "Tokyo branch tunnel"
    assert payload.addresses == ["10.100.0.1/24", "2001:db8:100::1/64"]
    assert payload.private_key == PRIVATE_KEY
    assert payload.port == 51820
    assert payload.mtu == 1420
    assert payload.enabled is True

    # Optional metadata defaults to the device default.
    minimal = WireGuardInterfaceCreate(name="wg9", private_key=PRIVATE_KEY)
    assert minimal.description is None
    assert minimal.addresses == []
    assert minimal.port is None
    assert minimal.mtu is None
    assert minimal.enabled is True


def test_interface_update_has_no_key_or_name_fields() -> None:
    fields = set(WireGuardInterfaceUpdate.model_fields)
    assert fields == {"description", "addresses", "port", "mtu", "enabled"}
    assert "private_key" not in fields
    assert "name" not in fields


@pytest.mark.parametrize("name", ["wg", "wg0a", "WG0", "wg-1", "wg 0", "wireguard0", ""])
def test_interface_name_rejects_invalid_values(name: str) -> None:
    with pytest.raises(ValueError):
        validate_wireguard_interface_name(name)


def test_interface_name_is_trimmed() -> None:
    assert validate_wireguard_interface_name("  wg01  ") == "wg01"


@pytest.mark.parametrize("name", ["wg0", "wg1", "wg999"])
def test_interface_name_accepts_wg_number(name: str) -> None:
    assert validate_wireguard_interface_name(name) == name


@pytest.mark.parametrize("name", ["", "has space", "a\tb", "x" * 101])
def test_peer_alias_rejects_invalid_values(name: str) -> None:
    with pytest.raises(ValueError):
        validate_wireguard_peer_name(name)


def test_peer_alias_accepts_visible_characters() -> None:
    assert validate_wireguard_peer_name("branch-office") == "branch-office"
    assert validate_wireguard_peer_name("x" * 100) == "x" * 100


@pytest.mark.parametrize(
    "value",
    [
        "not-base64",
        "",
        base64.b64encode(b"short").decode(),
        base64.b64encode(b"x" * 33).decode(),
        PRIVATE_KEY[:10] + "\n" + PRIVATE_KEY[10:],
    ],
)
def test_key_validation_rejects_bad_values(value: str) -> None:
    with pytest.raises(ValueError):
        canonical_wireguard_key(value)


def test_key_validation_returns_canonical_base64() -> None:
    assert canonical_wireguard_key(f"  {PRIVATE_KEY}  ") == PRIVATE_KEY
    assert canonical_wireguard_key(PRESHARED_KEY) == PRESHARED_KEY


def test_private_key_is_required_on_create_and_rotate() -> None:
    with pytest.raises(ValidationError):
        WireGuardInterfaceCreate(name="wg0")
    with pytest.raises(ValidationError):
        WireGuardPrivateKeyUpdate()


@pytest.mark.parametrize(
    "value",
    ["10.0.0.1", "10.0.0.1/33", "dhcp", "2001:db8::/129", "not-an-address/24"],
)
def test_interface_addresses_reject_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        canonical_interface_address(value)


def test_interface_addresses_accept_host_bits_and_ipv6() -> None:
    assert canonical_interface_address("10.0.0.1/24") == "10.0.0.1/24"
    assert canonical_interface_address("2001:DB8::1/64") == "2001:db8::1/64"


@pytest.mark.parametrize(
    "value",
    ["192.168.50.0", "192.168.50.1/24", "10.0.0.0/33", "dhcp", "2001:db8::/129"],
)
def test_allowed_ips_reject_non_canonical_prefixes(value: str) -> None:
    with pytest.raises(ValueError):
        canonical_allowed_ip(value)


def test_allowed_ips_are_canonical_and_required() -> None:
    assert canonical_allowed_ip("192.168.50.0/24") == "192.168.50.0/24"
    assert canonical_allowed_ip("2001:DB8::/32") == "2001:db8::/32"
    with pytest.raises(ValidationError):
        WireGuardPeerCreate(name="peer", public_key=PUBLIC_KEY, allowed_ips=[])


def test_peer_create_canonicalises_and_accepts_optional_fields() -> None:
    payload = WireGuardPeerCreate.model_validate(
        {
            **PEER_BODY,
            "allowed_ips": ["192.168.50.0/24", "2001:DB8:50::/64", "192.168.50.0/24"],
        }
    )
    assert payload.allowed_ips == ["192.168.50.0/24", "2001:db8:50::/64"]
    assert payload.public_key == PUBLIC_KEY
    assert payload.preshared_key == PRESHARED_KEY

    no_endpoint = WireGuardPeerCreate(
        name="road-warrior", public_key=PUBLIC_KEY, allowed_ips=["10.200.0.5/32"]
    )
    assert no_endpoint.endpoint is None
    assert no_endpoint.endpoint_port is None
    assert no_endpoint.persistent_keepalive is None
    assert no_endpoint.preshared_key is None
    assert no_endpoint.enabled is True


def test_peer_update_preshared_key_tristate_is_distinguishable() -> None:
    omitted = WireGuardPeerUpdate(public_key=PUBLIC_KEY, allowed_ips=["10.0.0.0/8"])
    explicit_null = WireGuardPeerUpdate(
        public_key=PUBLIC_KEY, allowed_ips=["10.0.0.0/8"], preshared_key=None
    )
    replaced = WireGuardPeerUpdate(
        public_key=PUBLIC_KEY, allowed_ips=["10.0.0.0/8"], preshared_key=PRESHARED_KEY
    )

    assert "preshared_key" not in omitted.model_fields_set
    assert "preshared_key" in explicit_null.model_fields_set
    assert explicit_null.preshared_key is None
    assert replaced.preshared_key == PRESHARED_KEY


@pytest.mark.parametrize(
    "endpoint",
    ["198.51.100.10", "2001:db8::10", "vpn.example.com", "vpn.example.com.", "[2001:db8::10]"],
)
def test_endpoint_accepts_ip_and_fqdn(endpoint: str) -> None:
    assert validate_endpoint(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    ["", "not a host", "198.51.100.10:51820", "localhost", "-bad.example.com", "vpn..example.com"],
)
def test_endpoint_rejects_invalid_values(endpoint: str) -> None:
    with pytest.raises(ValueError):
        validate_endpoint(endpoint)


@pytest.mark.parametrize(
    "field,value",
    [
        ("port", 0),
        ("port", 65_536),
        ("mtu", 67),
        ("mtu", 16_001),
        ("port", True),
        ("mtu", True),
    ],
)
def test_interface_numeric_ranges(field: str, value: object) -> None:
    body = {**INTERFACE_BODY, field: value}
    with pytest.raises(ValidationError):
        WireGuardInterfaceCreate.model_validate(body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("endpoint_port", 0),
        ("endpoint_port", 65_536),
        ("persistent_keepalive", 0),
        ("persistent_keepalive", 65_536),
        ("endpoint_port", True),
        ("persistent_keepalive", True),
    ],
)
def test_peer_numeric_ranges(field: str, value: object) -> None:
    body = {**PEER_BODY, field: value}
    with pytest.raises(ValidationError):
        WireGuardPeerCreate.model_validate(body)


def test_descriptions_are_trimmed_and_length_limited() -> None:
    payload = WireGuardPeerCreate.model_validate({**PEER_BODY, "description": "   "})
    assert payload.description is None
    with pytest.raises(ValidationError):
        WireGuardPeerCreate.model_validate({**PEER_BODY, "description": "x" * 256})


def test_output_models_never_expose_secret_fields() -> None:
    for model in (
        WireGuardInterfaceRead,
        WireGuardInterfaceDetail,
        WireGuardPeerRead,
        WireGuardStatus,
        WireGuardStatusPeer,
    ):
        assert "private_key" not in model.model_fields
        assert "preshared_key" not in model.model_fields

    interface = WireGuardInterfaceDetail.model_validate(
        {
            "name": "wg0",
            "description": None,
            "addresses": [],
            "port": None,
            "mtu": None,
            "enabled": True,
            "public_key": PUBLIC_KEY,
            "peer_count": 1,
            "peers": [
                {
                    "name": "peer",
                    "description": None,
                    "public_key": OTHER_PUBLIC_KEY,
                    "allowed_ips": ["10.0.0.0/8"],
                    "endpoint": None,
                    "endpoint_port": None,
                    "persistent_keepalive": None,
                    "has_preshared_key": True,
                    "enabled": True,
                }
            ],
        }
    )
    dumped = interface.model_dump(mode="json")
    assert "private_key" not in dumped
    assert "preshared_key" not in dumped
    assert dumped["peers"][0]["has_preshared_key"] is True
    assert PRIVATE_KEY not in str(dumped)
    assert PRESHARED_KEY not in str(dumped)

    # Key-generation responses intentionally carry secrets exactly once.
    assert "private_key" in WireGuardKeypair.model_fields
    assert "preshared_key" in WireGuardPresharedKey.model_fields


def test_status_defaults_and_collected_at() -> None:
    status = WireGuardStatus(configured=False, name="wg0")
    assert status.peers == []
    assert status.error is None
    assert status.collected_at.tzinfo is not None
