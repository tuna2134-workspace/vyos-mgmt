"""Schemas for the OSPF feature (OSPFv2 for IPv4 and OSPFv3 for IPv6).

Both versions share one API module selected by a ``v2``/``v3`` path segment.
The wire format is close to the VyOS configuration tree, but the API exposes
canonical values:

* area IDs are always dotted decimal, regardless of the input notation;
* unsupported device directives are ignored on read and preserved on write;
* values that the device may leave unset are represented as ``None`` so the
  caller can tell "device default" from an explicit configuration.

All range and enum checks live here; version-specific checks (network types and
redistribution sources) are exposed as helpers because the payload itself does
not carry a version.
"""

from __future__ import annotations

import ipaddress
import re
import uuid
from datetime import UTC, datetime
from typing import Literal, cast

from pydantic import Field, field_validator, model_validator

from vyos_mgmt.schemas.common import ApiModel
from vyos_mgmt.schemas.route_map import validate_route_map_name

OspfVersion = Literal["v2", "v3"]
OspfLogAdjacencyChanges = Literal["none", "normal", "detail"]
OspfAreaType = Literal["normal", "stub", "nssa"]
OspfMetricType = Literal[1, 2]

OSPF_VERSIONS: tuple[OspfVersion, ...] = ("v2", "v3")

#: Network types accepted by the VyOS OSPFv2 interface definition.
OSPFV2_NETWORK_TYPES: tuple[str, ...] = (
    "broadcast",
    "non-broadcast",
    "point-to-multipoint",
    "point-to-point",
)
#: Network types accepted by the VyOS OSPFv3 interface definition.
OSPFV3_NETWORK_TYPES: tuple[str, ...] = ("broadcast", "point-to-point")

SUPPORTED_NETWORK_TYPES: dict[OspfVersion, tuple[str, ...]] = {
    "v2": OSPFV2_NETWORK_TYPES,
    "v3": OSPFV3_NETWORK_TYPES,
}

OSPFV2_REDISTRIBUTE_SOURCES: tuple[str, ...] = (
    "babel",
    "bgp",
    "connected",
    "isis",
    "kernel",
    "rip",
    "static",
)
OSPFV3_REDISTRIBUTE_SOURCES: tuple[str, ...] = (
    "babel",
    "bgp",
    "connected",
    "isis",
    "kernel",
    "ripng",
    "static",
)

SUPPORTED_REDISTRIBUTE_SOURCES: dict[OspfVersion, tuple[str, ...]] = {
    "v2": OSPFV2_REDISTRIBUTE_SOURCES,
    "v3": OSPFV3_REDISTRIBUTE_SOURCES,
}

#: Union used by the payload schemas; the service narrows it by version.
OspfNetworkType = Literal[
    "broadcast",
    "non-broadcast",
    "point-to-multipoint",
    "point-to-point",
]
OspfRedistributeSource = Literal[
    "babel",
    "bgp",
    "connected",
    "isis",
    "kernel",
    "rip",
    "ripng",
    "static",
]

# VyOS area IDs are 32-bit values; decimal or dotted decimal notation is valid.
AREA_ID_MAX = 4_294_967_295
AUTO_COST_REFERENCE_BANDWIDTH_MAX = 4_294_967
REDISTRIBUTE_METRIC_MAX = 16_777_214
INTERFACE_TIMER_MAX = 65_535
INTERFACE_COST_MAX = 65_535
INTERFACE_PRIORITY_MAX = 255

_AREA_DECIMAL_RE = re.compile(r"^\d+$")
_INTERFACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")


def canonicalize_area_id(value: str | int) -> str:
    """Return an OSPF area ID in canonical dotted-decimal notation.

    Accepts a decimal number (``0``, ``4294967295``) or dotted decimal
    (``0.0.0.1``).  The returned value is what the API always exposes; the
    service resolves existing decimal device keys back to this form.
    """

    if isinstance(value, bool):
        raise ValueError("Area ID must be a decimal number or an IPv4 address")
    text = str(value).strip()
    if not text:
        raise ValueError("Area ID must be a decimal number or an IPv4 address")

    if _AREA_DECIMAL_RE.match(text):
        number = int(text)
    else:
        try:
            address = ipaddress.IPv4Address(text)
        except ValueError as exc:
            raise ValueError(
                "Area ID must be a decimal number (0-4294967295) or an IPv4 address"
            ) from exc
        number = int(address)

    if not 0 <= number <= AREA_ID_MAX:
        raise ValueError("Area ID must be between 0 and 4294967295")
    return str(ipaddress.IPv4Address(number))


def area_sort_key(area_id: str) -> int:
    """Numeric sort key for a canonical area ID."""

    return int(ipaddress.IPv4Address(area_id))


def validate_interface_name(value: str) -> str:
    """Validate the safe VyOS interface-name shape."""

    value = value.strip()
    if not _INTERFACE_RE.match(value):
        raise ValueError(
            "Interface names must start with a letter and contain only letters, "
            "digits, dot, underscore or hyphen (max 64 chars)"
        )
    return value


def validate_network_type_for_version(value: str, version: OspfVersion) -> str:
    """Validate a network type against the selected OSPF version."""

    allowed = SUPPORTED_NETWORK_TYPES[version]
    if value not in allowed:
        raise ValueError(f"OSPFv{version[1]} network type must be one of {', '.join(allowed)}")
    return value


def validate_redistribute_source_for_version(value: str, version: OspfVersion) -> str:
    """Validate a redistribution source against the selected OSPF version."""

    allowed = SUPPORTED_REDISTRIBUTE_SOURCES[version]
    candidate = value.strip().lower()
    if candidate not in allowed:
        raise ValueError(
            f"OSPFv{version[1]} redistribute source must be one of {', '.join(allowed)}"
        )
    return candidate


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _validate_router_id(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.IPv4Address(value.strip()))
    except ValueError as exc:
        raise ValueError("Router ID must be a valid IPv4 address") from exc


class OspfRouterRef(ApiModel):
    """Minimal router reference embedded in configuration responses."""

    id: uuid.UUID
    name: str


class OspfGlobal(ApiModel):
    """Global OSPF settings shared by reads and writes."""

    router_id: str | None = None
    log_adjacency_changes: OspfLogAdjacencyChanges = "none"
    auto_cost_reference_bandwidth: int | None = Field(
        default=None, ge=1, le=AUTO_COST_REFERENCE_BANDWIDTH_MAX
    )
    default_information_originate: bool = False
    default_information_always: bool = False
    distance_global: int | None = Field(default=None, ge=1, le=255)

    @field_validator("router_id", mode="before")
    @classmethod
    def _router_id(cls, value: str | None) -> str | None:
        return _validate_router_id(value)

    @model_validator(mode="after")
    def _default_information_coherence(self) -> OspfGlobal:
        if self.default_information_always and not self.default_information_originate:
            raise ValueError("default_information_always requires default_information_originate")
        return self


class OspfAreaRead(ApiModel):
    """One OSPF area as exposed by the API."""

    area_id: str
    area_type: OspfAreaType = "normal"
    no_summary: bool = False
    interface_count: int = Field(default=0, ge=0)

    @field_validator("area_id", mode="before")
    @classmethod
    def _area_id(cls, value: str | int) -> str:
        return canonicalize_area_id(value)

    @model_validator(mode="after")
    def _no_summary_coherence(self) -> OspfAreaRead:
        if self.no_summary and self.area_type not in {"stub", "nssa"}:
            raise ValueError("no_summary is only valid for stub or nssa areas")
        return self


class OspfAreaCreate(ApiModel):
    """Create body for ``POST /ospf/{version}/areas``."""

    area_id: str
    area_type: OspfAreaType = "normal"
    no_summary: bool = False

    @field_validator("area_id", mode="before")
    @classmethod
    def _area_id(cls, value: str | int) -> str:
        return canonicalize_area_id(value)

    @model_validator(mode="after")
    def _no_summary_coherence(self) -> OspfAreaCreate:
        if self.no_summary and self.area_type not in {"stub", "nssa"}:
            raise ValueError("no_summary is only valid for stub or nssa areas")
        return self


class OspfAreaUpdate(ApiModel):
    """Update body for ``PUT /ospf/{version}/areas/{area_id}``.

    The area ID is immutable and comes from the path; this is a full
    replacement of the managed fields.
    """

    area_type: OspfAreaType = "normal"
    no_summary: bool = False

    @model_validator(mode="after")
    def _no_summary_coherence(self) -> OspfAreaUpdate:
        if self.no_summary and self.area_type not in {"stub", "nssa"}:
            raise ValueError("no_summary is only valid for stub or nssa areas")
        return self


class OspfInterfaceRead(ApiModel):
    """One OSPF-activated interface as exposed by the API."""

    name: str
    area_id: str | None = None
    network_type: OspfNetworkType | None = None
    cost: int | None = Field(default=None, ge=1, le=INTERFACE_COST_MAX)
    hello_interval: int | None = Field(default=None, ge=1, le=INTERFACE_TIMER_MAX)
    dead_interval: int | None = Field(default=None, ge=1, le=INTERFACE_TIMER_MAX)
    priority: int | None = Field(default=None, ge=0, le=INTERFACE_PRIORITY_MAX)
    passive: bool = False
    bfd: bool = False
    mtu_ignore: bool = False
    retransmit_interval: int | None = Field(default=None, ge=1, le=INTERFACE_TIMER_MAX)
    transmit_delay: int | None = Field(default=None, ge=1, le=INTERFACE_TIMER_MAX)

    @field_validator("area_id", mode="before")
    @classmethod
    def _area_id(cls, value: str | int | None) -> str | None:
        return canonicalize_area_id(value) if value is not None else None


class OspfInterfaceCreate(ApiModel):
    """Create body for ``POST /ospf/{version}/interfaces``."""

    name: str
    area_id: str
    network_type: OspfNetworkType | None = None
    cost: int | None = Field(default=None, ge=1, le=INTERFACE_COST_MAX)
    hello_interval: int | None = Field(default=None, ge=1, le=INTERFACE_TIMER_MAX)
    dead_interval: int | None = Field(default=None, ge=1, le=INTERFACE_TIMER_MAX)
    priority: int | None = Field(default=None, ge=0, le=INTERFACE_PRIORITY_MAX)
    passive: bool = False
    bfd: bool = False
    mtu_ignore: bool = False
    retransmit_interval: int | None = Field(default=None, ge=1, le=INTERFACE_TIMER_MAX)
    transmit_delay: int | None = Field(default=None, ge=1, le=INTERFACE_TIMER_MAX)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return validate_interface_name(value)

    @field_validator("area_id", mode="before")
    @classmethod
    def _area_id(cls, value: str | int) -> str:
        return canonicalize_area_id(value)


class OspfInterfaceUpdate(ApiModel):
    """Update body for ``PUT /ospf/{version}/interfaces/{name}``.

    ``name`` is immutable (from the path) and ``area_id`` is required because an
    OSPF interface cannot exist without an area.  Unknown device directives on
    the interface are preserved.
    """

    area_id: str
    network_type: OspfNetworkType | None = None
    cost: int | None = Field(default=None, ge=1, le=INTERFACE_COST_MAX)
    hello_interval: int | None = Field(default=None, ge=1, le=INTERFACE_TIMER_MAX)
    dead_interval: int | None = Field(default=None, ge=1, le=INTERFACE_TIMER_MAX)
    priority: int | None = Field(default=None, ge=0, le=INTERFACE_PRIORITY_MAX)
    passive: bool = False
    bfd: bool = False
    mtu_ignore: bool = False
    retransmit_interval: int | None = Field(default=None, ge=1, le=INTERFACE_TIMER_MAX)
    transmit_delay: int | None = Field(default=None, ge=1, le=INTERFACE_TIMER_MAX)

    @field_validator("area_id", mode="before")
    @classmethod
    def _area_id(cls, value: str | int) -> str:
        return canonicalize_area_id(value)


class OspfRedistributeRead(ApiModel):
    """One redistribution source as exposed by the API."""

    source: str
    metric: int | None = Field(default=None, ge=1, le=REDISTRIBUTE_METRIC_MAX)
    metric_type: OspfMetricType | None = None
    route_map: str | None = None


class OspfRedistributeCreate(ApiModel):
    """Create body for ``POST /ospf/{version}/redistribute``."""

    source: OspfRedistributeSource
    metric: int | None = Field(default=None, ge=1, le=REDISTRIBUTE_METRIC_MAX)
    metric_type: OspfMetricType | None = None
    route_map: str | None = None

    @field_validator("source", mode="before")
    @classmethod
    def _source(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("route_map")
    @classmethod
    def _route_map(cls, value: str | None) -> str | None:
        value = _clean_optional(value)
        return validate_route_map_name(value) if value else None


class OspfRedistributeUpdate(ApiModel):
    """Update body for ``PUT /ospf/{version}/redistribute/{source}``.

    ``source`` is immutable (from the path); metric, metric type and route map
    are a full replacement of the managed fields.
    """

    metric: int | None = Field(default=None, ge=1, le=REDISTRIBUTE_METRIC_MAX)
    metric_type: OspfMetricType | None = None
    route_map: str | None = None

    @field_validator("route_map")
    @classmethod
    def _route_map(cls, value: str | None) -> str | None:
        value = _clean_optional(value)
        return validate_route_map_name(value) if value else None


class OspfConfigRead(ApiModel):
    """Complete OSPF view for one router and version."""

    router: OspfRouterRef
    version: OspfVersion
    configured: bool
    global_config: OspfGlobal = Field(alias="global", serialization_alias="global")
    areas: list[OspfAreaRead] = Field(default_factory=list)
    interfaces: list[OspfInterfaceRead] = Field(default_factory=list)
    redistributions: list[OspfRedistributeRead] = Field(default_factory=list)
    supported_network_types: list[str] = Field(default_factory=list)
    supported_redistribute_sources: list[str] = Field(default_factory=list)


class OspfNeighborStatus(ApiModel):
    """One parsed ``show ... neighbor`` row."""

    neighbor_id: str
    priority: int | None = None
    state: str
    dead_time: str | None = None
    address: str | None = None
    interface: str | None = None
    established: bool = False


class OspfStatus(ApiModel):
    """Operational neighbour status for one OSPF version."""

    configured: bool
    version: OspfVersion
    router_id: str | None = None
    neighbors: list[OspfNeighborStatus] = Field(default_factory=list)
    total_neighbors: int = 0
    full_neighbors: int = 0
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None


def supported_network_types(version: OspfVersion) -> list[str]:
    return list(SUPPORTED_NETWORK_TYPES[version])


def supported_redistribute_sources(version: OspfVersion) -> list[str]:
    return list(SUPPORTED_REDISTRIBUTE_SOURCES[version])


def version_from_text(value: str) -> OspfVersion | None:
    """Narrow an arbitrary string to a supported version, if possible."""

    return cast(OspfVersion, value) if value in OSPF_VERSIONS else None
