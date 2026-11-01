"""Unit tests for WireGuard key generation and public-key derivation."""

from __future__ import annotations

import base64

import pytest

from vyos_mgmt.services.wireguard_service import (
    WireGuardKeyError,
    clamp_private_key,
    derive_public_key,
    generate_keypair,
    generate_preshared_key,
    generate_private_key,
)

# RFC 7748 section 6.1 X25519 test vector.  X25519 clamps the scalar
# internally, so the public key must match the published vector.
RFC7748_PRIVATE_KEY = "dwdtCnMYpX08FsFyUbJmRd9ML4frwJkqsXf7pR25LCo="
RFC7748_PUBLIC_KEY = "hSDwCYkwp1R0i33ctD73Wg2/Og0mOBr066SpjqqbTmo="


def _decode(key: str) -> bytes:
    return base64.b64decode(key, validate=True)


def test_known_keypair_derivation_matches_rfc7748() -> None:
    assert derive_public_key(RFC7748_PRIVATE_KEY) == RFC7748_PUBLIC_KEY


def test_generated_keypair_is_consistent_and_clamped() -> None:
    for _ in range(25):
        private_key, public_key = generate_keypair()
        raw = _decode(private_key)
        assert len(raw) == 32
        # RFC 7748 clamping: clear the low three bits of the first byte, clear
        # the top bit and set the second-highest bit of the last byte.
        assert raw[0] & 0b0000_0111 == 0
        assert raw[31] & 0b1000_0000 == 0
        assert raw[31] & 0b0100_0000 == 0b0100_0000
        assert len(_decode(public_key)) == 32
        assert derive_public_key(private_key) == public_key
        assert private_key != public_key


def test_generate_private_key_is_random() -> None:
    assert generate_private_key() != generate_private_key()


def test_clamp_private_key_applies_rfc7748_bits() -> None:
    clamped = clamp_private_key(bytes([0xFF]) * 32)
    assert clamped[0] == 0xF8
    assert clamped[31] == 0x7F
    with pytest.raises(WireGuardKeyError):
        clamp_private_key(b"too short")


def test_preshared_key_is_32_random_bytes() -> None:
    first = generate_preshared_key()
    second = generate_preshared_key()
    assert len(_decode(first)) == 32
    assert len(_decode(second)) == 32
    assert first != second


@pytest.mark.parametrize(
    "value",
    ["not-base64", "", base64.b64encode(b"short").decode(), "A" * 44],
)
def test_invalid_private_key_error_does_not_leak_input(value: str) -> None:
    with pytest.raises(WireGuardKeyError) as exc_info:
        derive_public_key(value)
    if value:
        assert value not in str(exc_info.value)
    assert "Base64" in str(exc_info.value)
