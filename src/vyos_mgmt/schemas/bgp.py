"""Schemas for the BGP feature.

The wire format is deliberately close to the VyOS configuration tree so that
mapping code stays obvious, but the API exposes friendly, validated fields and
never returns secrets (only ``password_configured``).
"""

from __future__ import annotations

import ipaddress
import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from vyos_mgmt.schemas.common import ApiModel
from vyos_mgmt.schemas.route_map import validate_route_map_name

AddressFamily = Literal["ipv4-unicast", "ipv6-unicast"]
SUPPORTED_ADDRESS_FAMILIES: tuple[AddressFamily, ...] = ("ipv4-unicast", "ipv6-unicast")

_IFACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
_PEER_GROUP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ASN_MAX = 4_294_967_295


def validate_router_id(value: str) -> str:
    try:
        return str(ipaddress.IPv4Address(value))
    except ValueError as exc:
        raise ValueError("Router ID must be a valid IPv4 address") from exc


def validate_peer(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Neighbor address is required")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if _IFACE_RE.match(value):
        return value
    raise ValueError("Neighbor must be an IP address or an interface name")


def validate_interface(value: str) -> str:
    value = value.strip()
    if not _IFACE_RE.match(value):
        raise ValueError("Invalid interface name")
    return value


def validate_prefix_for_af(prefix: str, af: str) -> str:
    try:
        network = ipaddress.ip_network(prefix.strip(), strict=True)
    except ValueError as exc:
        raise ValueError(
            "Prefix must be a valid network in CIDR notation (host bits must be zero)"
        ) from exc
    expected_version = 4 if af == "ipv4-unicast" else 6
    if network.version != expected_version:
        raise ValueError(f"{af} requires an IPv{expected_version} prefix")
    return str(network)


def validate_password(value: str) -> str:
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("BGP password must not contain control characters")
    return value


class BgpTimers(ApiModel):
    keepalive: int = Field(ge=1, le=65535)
    holdtime: int = Field(ge=3, le=65535)

    @model_validator(mode="after")
    def _ordering(self) -> BgpTimers:
        if self.holdtime <= self.keepalive:
            raise ValueError("Hold time must be greater than keepalive")
        return self


class AddressFamilySettings(ApiModel):
    route_reflector_client: bool = False
    next_hop_self: bool = False
    soft_reconfiguration_inbound: bool = False
    default_originate: bool = False
    allowas_in: int | None = Field(default=None, ge=1, le=10)
    route_map_import: str | None = None
    route_map_export: str | None = None

    @field_validator("route_map_import", "route_map_export", mode="after")
    @classmethod
    def _route_map(cls, value: str | None) -> str | None:
        return validate_route_map_name(value) if value else None


class BgpGlobalUpdate(ApiModel):
    system_as: int = Field(ge=1, le=_ASN_MAX)
    router_id: str | None = None
    log_neighbor_changes: bool = False

    @field_validator("router_id")
    @classmethod
    def _router_id(cls, value: str | None) -> str | None:
        return validate_router_id(value) if value else None


class BgpGlobalRead(ApiModel):
    configured: bool = False
    system_as: int | None = None
    router_id: str | None = None
    log_neighbor_changes: bool = False


class BgpNeighborCreate(ApiModel):
    address: str
    remote_as: int = Field(ge=1, le=_ASN_MAX)
    description: str | None = Field(default=None, max_length=255)
    peer_group: str | None = None
    update_source: str | None = None
    ebgp_multihop: int | None = Field(default=None, ge=1, le=255)
    password: str | None = Field(default=None, max_length=128, min_length=1)
    passive: bool = False
    shutdown: bool = False
    timers: BgpTimers | None = None
    local_as: int | None = Field(default=None, ge=1, le=_ASN_MAX)
    address_families: dict[AddressFamily, AddressFamilySettings] = Field(
        default_factory=lambda: {"ipv4-unicast": AddressFamilySettings()}
    )

    @field_validator("address")
    @classmethod
    def _address(cls, value: str) -> str:
        return validate_peer(value)

    @field_validator("peer_group")
    @classmethod
    def _peer_group(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not _PEER_GROUP_RE.match(value):
            raise ValueError("Peer group name contains invalid characters")
        return value

    @field_validator("update_source")
    @classmethod
    def _update_source(cls, value: str | None) -> str | None:
        return validate_interface(value) if value else None

    @field_validator("password")
    @classmethod
    def _password(cls, value: str | None) -> str | None:
        return validate_password(value) if value else None

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def _non_empty_af(self) -> BgpNeighborCreate:
        if not self.address_families:
            self.address_families = {"ipv4-unicast": AddressFamilySettings()}
        return self


class BgpNeighborUpdate(ApiModel):
    remote_as: int | None = Field(default=None, ge=1, le=_ASN_MAX)
    description: str | None = Field(default=None, max_length=255)
    peer_group: str | None = None
    update_source: str | None = None
    ebgp_multihop: int | None = Field(default=None, ge=1, le=255)
    password: str | None = Field(default=None, max_length=128)
    passive: bool | None = None
    shutdown: bool | None = None
    timers: BgpTimers | None = None
    local_as: int | None = Field(default=None, ge=1, le=_ASN_MAX)
    address_families: dict[AddressFamily, AddressFamilySettings] | None = None

    @field_validator("peer_group")
    @classmethod
    def _peer_group(cls, value: str | None) -> str | None:
        if not value:
            return None
        if not _PEER_GROUP_RE.match(value):
            raise ValueError("Peer group name contains invalid characters")
        return value

    @field_validator("update_source")
    @classmethod
    def _update_source(cls, value: str | None) -> str | None:
        return validate_interface(value) if value else None

    @field_validator("password")
    @classmethod
    def _password(cls, value: str | None) -> str | None:
        return validate_password(value) if value else None

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class BgpNeighborRead(ApiModel):
    address: str
    remote_as: int | None
    description: str | None = None
    peer_group: str | None = None
    update_source: str | None = None
    ebgp_multihop: int | None = None
    password_configured: bool = False
    passive: bool = False
    shutdown: bool = False
    timers: BgpTimers | None = None
    local_as: int | None = None
    address_families: dict[str, AddressFamilySettings] = Field(default_factory=dict)


class BgpPeerGroupCreate(ApiModel):
    name: str
    remote_as: int = Field(ge=1, le=_ASN_MAX)
    description: str | None = Field(default=None, max_length=255)
    update_source: str | None = None
    ebgp_multihop: int | None = Field(default=None, ge=1, le=255)
    password: str | None = Field(default=None, max_length=128, min_length=1)
    address_families: dict[AddressFamily, AddressFamilySettings] = Field(
        default_factory=lambda: {"ipv4-unicast": AddressFamilySettings()}
    )

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not _PEER_GROUP_RE.match(value):
            raise ValueError(
                "Peer group name must start with a letter or digit and contain only "
                "letters, digits, dot, underscore or hyphen (max 64 chars)"
            )
        return value

    @field_validator("update_source")
    @classmethod
    def _update_source(cls, value: str | None) -> str | None:
        return validate_interface(value) if value else None

    @field_validator("password")
    @classmethod
    def _password(cls, value: str | None) -> str | None:
        return validate_password(value) if value else None


class BgpPeerGroupUpdate(ApiModel):
    remote_as: int | None = Field(default=None, ge=1, le=_ASN_MAX)
    description: str | None = Field(default=None, max_length=255)
    update_source: str | None = None
    ebgp_multihop: int | None = Field(default=None, ge=1, le=255)
    password: str | None = Field(default=None, max_length=128)
    address_families: dict[AddressFamily, AddressFamilySettings] | None = None

    @field_validator("update_source")
    @classmethod
    def _update_source(cls, value: str | None) -> str | None:
        return validate_interface(value) if value else None

    @field_validator("password")
    @classmethod
    def _password(cls, value: str | None) -> str | None:
        return validate_password(value) if value else None


class BgpPeerGroupRead(ApiModel):
    name: str
    remote_as: int | None
    description: str | None = None
    update_source: str | None = None
    ebgp_multihop: int | None = None
    password_configured: bool = False
    address_families: dict[str, AddressFamilySettings] = Field(default_factory=dict)


class BgpNetworkCreate(ApiModel):
    af: AddressFamily
    prefix: str

    @model_validator(mode="after")
    def _prefix(self) -> BgpNetworkCreate:
        self.prefix = validate_prefix_for_af(self.prefix, self.af)
        return self


class BgpNetworkRead(ApiModel):
    af: str
    prefix: str


class BgpRouterRef(ApiModel):
    id: uuid.UUID
    name: str


class BgpConfigRead(ApiModel):
    router: BgpRouterRef
    configured: bool
    global_config: BgpGlobalRead = Field(alias="global", serialization_alias="global")
    neighbors: list[BgpNeighborRead] = Field(default_factory=list)
    peer_groups: list[BgpPeerGroupRead] = Field(default_factory=list)
    networks: list[BgpNetworkRead] = Field(default_factory=list)
    supported_address_families: list[str] = Field(
        default_factory=lambda: list(SUPPORTED_ADDRESS_FAMILIES)
    )


class BgpPeerStatus(ApiModel):
    address: str
    remote_as: int | None = None
    state: str = "Unknown"
    established: bool = False
    uptime: str | None = None
    prefixes_received: int | None = None
    prefixes_sent: int | None = None
    msg_received: int | None = None
    msg_sent: int | None = None
    description: str | None = None
    address_family: str | None = None


class BgpStatus(ApiModel):
    configured: bool
    router_id: str | None = None
    local_as: int | None = None
    peers: list[BgpPeerStatus] = Field(default_factory=list)
    total_peers: int = 0
    established_peers: int = 0
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None
