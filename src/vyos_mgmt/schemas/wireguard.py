"""Schemas for the VPN / WireGuard feature.

VyOS stores WireGuard interfaces under ``interfaces wireguard <wgN>``.  Each
interface has a write-only ``private-key`` and a tag-node tree of peers keyed by
peer alias.  This module defines the API wire format only; the service owns the
translation to and from the device tree.

Security notes
--------------

* ``private_key`` (interface) and ``preshared_key`` (peer) are **write-only**:
  they only appear on input schemas and the one-time key-generation responses.
  Read models expose ``public_key`` (safe) and ``has_preshared_key`` instead.
* Keys are Base64-encoded 32-byte values.  Inputs are canonicalised so that
  equivalent encodings of the same bytes compare equal.
* Interface names must match ``wg[0-9]+`` and peer aliases may not contain
  whitespace, mirroring the VyOS constraints.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
from datetime import UTC, datetime

from pydantic import Field, field_validator

from vyos_mgmt.schemas.common import ApiModel

WIREGUARD_INTERFACE_PATTERN = r"^wg[0-9]+$"
WIREGUARD_INTERFACE_RE = re.compile(WIREGUARD_INTERFACE_PATTERN)
WIREGUARD_PEER_PATTERN = r"^[^\s]{1,100}$"
WIREGUARD_PEER_RE = re.compile(WIREGUARD_PEER_PATTERN)

WIREGUARD_KEY_BYTES = 32
DESCRIPTION_MAX_LENGTH = 255
PORT_MIN = 1
PORT_MAX = 65_535
MTU_MIN = 68
MTU_MAX = 16_000

#: FQDN shape accepted for peer endpoints.  A single label is intentionally
#: rejected because VyOS' ``fqdn`` validator requires a dotted name; literal
#: IPv4/IPv6 addresses are handled separately by :func:`validate_endpoint`.
_FQDN_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.[A-Za-z]{2,63}\.?$"
)


# ---------------------------------------------------------------------------
# Value validators (shared with the service)
# ---------------------------------------------------------------------------


def validate_wireguard_interface_name(value: str) -> str:
    """Validate a WireGuard interface name (``wg[0-9]+``)."""

    if not isinstance(value, str):
        raise ValueError("WireGuard interface name must be a string")
    value = value.strip()
    if not WIREGUARD_INTERFACE_RE.match(value):
        raise ValueError("WireGuard interface name must match wg[0-9]+ (for example wg0)")
    return value


def validate_wireguard_peer_name(value: str) -> str:
    """Validate a peer alias (1-100 characters, no whitespace)."""

    if not isinstance(value, str):
        raise ValueError("Peer alias must be a string")
    value = value.strip()
    if not WIREGUARD_PEER_RE.match(value):
        raise ValueError("Peer alias must be 1-100 characters and must not contain whitespace")
    return value


def decode_wireguard_key(value: str) -> bytes:
    """Decode a Base64 WireGuard key, enforcing exactly 32 decoded bytes."""

    if not isinstance(value, str):
        raise ValueError("WireGuard keys must be Base64-encoded strings")
    text = value.strip()
    if not text:
        raise ValueError("WireGuard keys must not be empty")
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("WireGuard keys must be valid Base64") from exc
    if len(raw) != WIREGUARD_KEY_BYTES:
        raise ValueError("WireGuard keys must decode to exactly 32 bytes")
    return raw


def canonical_wireguard_key(value: str) -> str:
    """Return the canonical Base64 representation of a 32-byte key."""

    return base64.b64encode(decode_wireguard_key(value)).decode("ascii")


def canonical_interface_address(value: str) -> str:
    """Canonicalise an interface CIDR (host bits are allowed)."""

    if not isinstance(value, str):
        raise ValueError("Addresses must be IPv4 or IPv6 interface CIDRs")
    text = value.strip()
    if "/" not in text:
        raise ValueError("Addresses must use CIDR notation (for example 10.0.0.1/24)")
    try:
        interface = ipaddress.ip_interface(text)
    except ValueError as exc:
        raise ValueError(
            "Addresses must be IPv4 or IPv6 interface CIDRs (for example 10.0.0.1/24)"
        ) from exc
    return str(interface)


def canonical_allowed_ip(value: str) -> str:
    """Canonicalise a peer allowed-IP prefix (host bits must be zero)."""

    if not isinstance(value, str):
        raise ValueError("Allowed IPs must be IPv4 or IPv6 prefixes")
    text = value.strip()
    if "/" not in text:
        raise ValueError("Allowed IPs must use CIDR notation (for example 192.168.50.0/24)")
    try:
        network = ipaddress.ip_network(text, strict=True)
    except ValueError as exc:
        raise ValueError(
            "Allowed IPs must be canonical IPv4 or IPv6 prefixes with host bits set to zero"
        ) from exc
    return str(network)


def validate_endpoint(value: str) -> str:
    """Validate a peer endpoint as a literal IP address or an FQDN.

    The port is carried separately (``endpoint_port``); an embedded port is
    therefore rejected rather than silently parsed.
    """

    if not isinstance(value, str):
        raise ValueError("Endpoint must be an IP address or FQDN")
    text = value.strip()
    if not text:
        raise ValueError("Endpoint must be an IP address or FQDN")
    if any(character.isspace() for character in text):
        raise ValueError("Endpoint must not contain whitespace")
    bracketed = text[1:-1] if text.startswith("[") and text.endswith("]") else text
    try:
        return str(ipaddress.ip_address(bracketed))
    except ValueError:
        pass
    if not _FQDN_RE.match(text):
        raise ValueError("Endpoint must be an IPv4/IPv6 address or a fully qualified hostname")
    return text


def _clean_description(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Description must be a string")
    text = value.strip()
    return text or None


def _reject_boolean(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("Must be an integer, not a boolean")
    return value


# ---------------------------------------------------------------------------
# Interface read models
# ---------------------------------------------------------------------------


class WireGuardInterfaceRead(ApiModel):
    """One WireGuard interface as exposed by the API.

    ``public_key`` is derived from the configured private key and is safe to
    display.  ``mtu`` is ``None`` when the device default (1420) applies.
    """

    name: str
    description: str | None = None
    addresses: list[str] = Field(default_factory=list)
    port: int | None = Field(default=None, ge=PORT_MIN, le=PORT_MAX)
    mtu: int | None = Field(default=None, ge=MTU_MIN, le=MTU_MAX)
    enabled: bool = True
    public_key: str | None = None
    peer_count: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return validate_wireguard_interface_name(value)

    @field_validator("public_key")
    @classmethod
    def _public_key(cls, value: str | None) -> str | None:
        return canonical_wireguard_key(value) if value else None

    @field_validator("addresses")
    @classmethod
    def _addresses(cls, value: list[str]) -> list[str]:
        return _canonical_addresses(value)

    @field_validator("description", mode="after")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return _clean_description(value)


class WireGuardPeerRead(ApiModel):
    """One WireGuard peer as exposed by the API (never the preshared key)."""

    name: str
    description: str | None = None
    public_key: str
    allowed_ips: list[str] = Field(default_factory=list)
    endpoint: str | None = None
    endpoint_port: int | None = Field(default=None, ge=PORT_MIN, le=PORT_MAX)
    persistent_keepalive: int | None = Field(default=None, ge=PORT_MIN, le=PORT_MAX)
    has_preshared_key: bool = False
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return validate_wireguard_peer_name(value)

    @field_validator("public_key")
    @classmethod
    def _public_key(cls, value: str) -> str:
        return canonical_wireguard_key(value)

    @field_validator("allowed_ips")
    @classmethod
    def _allowed_ips(cls, value: list[str]) -> list[str]:
        return _canonical_prefixes(value, require_values=False)

    @field_validator("endpoint")
    @classmethod
    def _endpoint(cls, value: str | None) -> str | None:
        return validate_endpoint(value) if value else None

    @field_validator("description", mode="after")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return _clean_description(value)


class WireGuardInterfaceDetail(WireGuardInterfaceRead):
    """Interface metadata plus its peers, sorted by peer name."""

    peers: list[WireGuardPeerRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Interface write models
# ---------------------------------------------------------------------------


class WireGuardInterfaceCreate(ApiModel):
    """Create body for ``POST /wireguard``.

    ``private_key`` is required and write-only; it never appears in a response.
    """

    name: str
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    addresses: list[str] = Field(default_factory=list)
    port: int | None = Field(default=None, ge=PORT_MIN, le=PORT_MAX)
    mtu: int | None = Field(default=None, ge=MTU_MIN, le=MTU_MAX)
    enabled: bool = True
    private_key: str

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return validate_wireguard_interface_name(value)

    @field_validator("description", mode="after")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return _clean_description(value)

    @field_validator("addresses")
    @classmethod
    def _addresses(cls, value: list[str]) -> list[str]:
        return _canonical_addresses(value)

    @field_validator("port", "mtu", mode="before")
    @classmethod
    def _not_boolean(cls, value: object) -> object:
        return _reject_boolean(value)

    @field_validator("private_key")
    @classmethod
    def _private_key(cls, value: str) -> str:
        return canonical_wireguard_key(value)


class WireGuardInterfaceUpdate(ApiModel):
    """Full replacement of the managed interface metadata fields.

    The private key and peers are managed by their own endpoints and are never
    touched by this body.  Omitted optional values reset to the device default.
    """

    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    addresses: list[str] = Field(default_factory=list)
    port: int | None = Field(default=None, ge=PORT_MIN, le=PORT_MAX)
    mtu: int | None = Field(default=None, ge=MTU_MIN, le=MTU_MAX)
    enabled: bool = True

    @field_validator("description", mode="after")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return _clean_description(value)

    @field_validator("addresses")
    @classmethod
    def _addresses(cls, value: list[str]) -> list[str]:
        return _canonical_addresses(value)

    @field_validator("port", "mtu", mode="before")
    @classmethod
    def _not_boolean(cls, value: object) -> object:
        return _reject_boolean(value)


class WireGuardPrivateKeyUpdate(ApiModel):
    """Rotate the interface private key (write-only)."""

    private_key: str

    @field_validator("private_key")
    @classmethod
    def _private_key(cls, value: str) -> str:
        return canonical_wireguard_key(value)


# ---------------------------------------------------------------------------
# Peer write models
# ---------------------------------------------------------------------------


class WireGuardPeerCreate(ApiModel):
    """Create body for ``POST /wireguard/{name}/peers``."""

    name: str
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    public_key: str
    allowed_ips: list[str] = Field(min_length=1)
    endpoint: str | None = None
    endpoint_port: int | None = Field(default=None, ge=PORT_MIN, le=PORT_MAX)
    persistent_keepalive: int | None = Field(default=None, ge=PORT_MIN, le=PORT_MAX)
    preshared_key: str | None = None
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return validate_wireguard_peer_name(value)

    @field_validator("description", mode="after")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return _clean_description(value)

    @field_validator("public_key")
    @classmethod
    def _public_key(cls, value: str) -> str:
        return canonical_wireguard_key(value)

    @field_validator("preshared_key")
    @classmethod
    def _preshared_key(cls, value: str | None) -> str | None:
        return canonical_wireguard_key(value) if value else None

    @field_validator("allowed_ips")
    @classmethod
    def _allowed_ips(cls, value: list[str]) -> list[str]:
        return _canonical_prefixes(value, require_values=True)

    @field_validator("endpoint")
    @classmethod
    def _endpoint(cls, value: str | None) -> str | None:
        return validate_endpoint(value) if value else None

    @field_validator("endpoint_port", "persistent_keepalive", mode="before")
    @classmethod
    def _not_boolean(cls, value: object) -> object:
        return _reject_boolean(value)


class WireGuardPeerUpdate(ApiModel):
    """Full replacement of the managed peer fields; the alias is immutable.

    ``preshared_key`` is special because the current value can never be read
    back: omit the field to keep the existing key, send ``null`` to remove it,
    or send a new Base64 key to replace it.
    """

    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    public_key: str
    allowed_ips: list[str] = Field(min_length=1)
    endpoint: str | None = None
    endpoint_port: int | None = Field(default=None, ge=PORT_MIN, le=PORT_MAX)
    persistent_keepalive: int | None = Field(default=None, ge=PORT_MIN, le=PORT_MAX)
    preshared_key: str | None = None
    enabled: bool = True

    @field_validator("description", mode="after")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return _clean_description(value)

    @field_validator("public_key")
    @classmethod
    def _public_key(cls, value: str) -> str:
        return canonical_wireguard_key(value)

    @field_validator("preshared_key")
    @classmethod
    def _preshared_key(cls, value: str | None) -> str | None:
        return canonical_wireguard_key(value) if value else None

    @field_validator("allowed_ips")
    @classmethod
    def _allowed_ips(cls, value: list[str]) -> list[str]:
        return _canonical_prefixes(value, require_values=True)

    @field_validator("endpoint")
    @classmethod
    def _endpoint(cls, value: str | None) -> str | None:
        return validate_endpoint(value) if value else None

    @field_validator("endpoint_port", "persistent_keepalive", mode="before")
    @classmethod
    def _not_boolean(cls, value: object) -> object:
        return _reject_boolean(value)


# ---------------------------------------------------------------------------
# Key generation / list / status
# ---------------------------------------------------------------------------


class WireGuardKeypair(ApiModel):
    """One-time keypair returned by ``POST /wireguard/keypair``."""

    private_key: str
    public_key: str

    @field_validator("private_key", "public_key")
    @classmethod
    def _key(cls, value: str) -> str:
        return canonical_wireguard_key(value)


class WireGuardPresharedKey(ApiModel):
    """One-time preshared key returned by ``POST /wireguard/preshared-key``."""

    preshared_key: str

    @field_validator("preshared_key")
    @classmethod
    def _preshared_key(cls, value: str) -> str:
        return canonical_wireguard_key(value)


class WireGuardStatusPeer(ApiModel):
    """One peer block parsed from ``show interfaces wireguard <name> summary``."""

    public_key: str
    endpoint: str | None = None
    allowed_ips: list[str] = Field(default_factory=list)
    latest_handshake: str | None = None
    transfer_received: str | None = None
    transfer_sent: str | None = None

    @field_validator("public_key")
    @classmethod
    def _public_key(cls, value: str) -> str:
        return canonical_wireguard_key(value)

    @field_validator("allowed_ips")
    @classmethod
    def _allowed_ips(cls, value: list[str]) -> list[str]:
        return _canonical_prefixes(value, require_values=False)


class WireGuardStatus(ApiModel):
    """Operational status for one configured WireGuard interface."""

    configured: bool
    name: str
    public_key: str | None = None
    listening_port: int | None = Field(default=None, ge=PORT_MIN, le=PORT_MAX)
    peers: list[WireGuardStatusPeer] = Field(default_factory=list)
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return validate_wireguard_interface_name(value)

    @field_validator("public_key")
    @classmethod
    def _public_key(cls, value: str | None) -> str | None:
        return canonical_wireguard_key(value) if value else None


class WireGuardList(ApiModel):
    """``GET /wireguard`` response."""

    items: list[WireGuardInterfaceRead] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Shared list validators
# ---------------------------------------------------------------------------


def _canonical_addresses(values: list[str]) -> list[str]:
    canonical: list[str] = []
    for value in values:
        address = canonical_interface_address(value)
        if address not in canonical:
            canonical.append(address)
    return canonical


def _canonical_prefixes(values: list[str], *, require_values: bool) -> list[str]:
    canonical: list[str] = []
    for value in values:
        prefix = canonical_allowed_ip(value)
        if prefix not in canonical:
            canonical.append(prefix)
    if require_values and not canonical:
        raise ValueError("At least one allowed IP prefix is required")
    return canonical


__all__ = [
    "DESCRIPTION_MAX_LENGTH",
    "MTU_MAX",
    "MTU_MIN",
    "PORT_MAX",
    "PORT_MIN",
    "WIREGUARD_INTERFACE_PATTERN",
    "WIREGUARD_KEY_BYTES",
    "WIREGUARD_PEER_PATTERN",
    "WireGuardInterfaceCreate",
    "WireGuardInterfaceDetail",
    "WireGuardInterfaceRead",
    "WireGuardInterfaceUpdate",
    "WireGuardKeypair",
    "WireGuardList",
    "WireGuardPeerCreate",
    "WireGuardPeerRead",
    "WireGuardPeerUpdate",
    "WireGuardPresharedKey",
    "WireGuardPrivateKeyUpdate",
    "WireGuardStatus",
    "WireGuardStatusPeer",
    "canonical_allowed_ip",
    "canonical_interface_address",
    "canonical_wireguard_key",
    "decode_wireguard_key",
    "validate_endpoint",
    "validate_wireguard_interface_name",
    "validate_wireguard_peer_name",
]
