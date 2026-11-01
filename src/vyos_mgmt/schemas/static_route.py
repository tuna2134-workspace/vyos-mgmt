"""Schemas for the IPv4/IPv6 static-route feature.

VyOS keeps the two address families in separate trees:

* ``protocols static route <ipv4net>`` (IPv4)
* ``protocols static route6 <ipv6net>`` (IPv6)

A route is either a **unicast** route with one or more next hops, or a
**blackhole** / **reject** route.  The API models both shapes with one read
model: ``blackhole`` / ``reject`` are booleans and ``next_hops`` is empty for
the discard variants, while ``distance`` / ``tag`` are only meaningful (and
only allowed) on blackhole/reject routes.

Next hops
---------

* ``address`` is a single host address of the route's family (no prefix), or
  ``null`` for an interface-only next hop (VyOS ``interface <if>``).
* ``interface`` is a VyOS interface name, or ``null``.
* At least one of the two is required; both together map to
  ``next-hop <address> interface <if>``.
* ``distance`` is 1-255 or ``null`` for the device default.
* ``enabled: false`` maps to the valueless VyOS ``disable`` node.

Duplicate ``(address, interface)`` pairs inside one route are rejected.

The family is part of the route identity.  ``StaticRouteCreate`` and
``StaticRouteRead`` carry it, so this module can verify that the prefix and
every next-hop address belong to that family.  ``StaticRouteUpdate`` accepts
``family`` / ``prefix`` only so a client can send back an object it received
from ``GET``; the path parameters stay authoritative and the service drops the
body values.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Literal, Self

from pydantic import Field, ValidationInfo, field_validator, model_validator

from vyos_mgmt.schemas.common import ApiModel

StaticRouteFamily = Literal["ipv4", "ipv6"]

STATIC_ROUTE_FAMILIES: tuple[StaticRouteFamily, ...] = ("ipv4", "ipv6")
DISTANCE_MIN = 1
DISTANCE_MAX = 255
TAG_MIN = 1
TAG_MAX = 4_294_967_295
DESCRIPTION_MAX_LENGTH = 255

#: Mirrors the VyOS ``interface-name`` constraint (``constraint/interface-name
#: .xml.i``) closely enough to reject typos while accepting every interface the
#: device can own.  Host names and FQDNs are deliberately not interface names.
INTERFACE_NAME_PATTERN = (
    r"^(?:"
    r"(?:bond|br|dum|en|ersp|eth|gnv|ifb|ipoe|lan|l2tp|l2tpeth|macsec|peth|ppp|pppoe|"
    r"pptp|sstp|sstpc|tun|veth|vpptap|vpptun|vti|vtun|vxlan|wg|wlan|wwan)"
    r"[0-9]+(?:\.[0-9]+)?"
    r"|pod-[-_A-Za-z0-9]{1,11}"
    r"|lo"
    r")$"
)
INTERFACE_NAME_RE = re.compile(INTERFACE_NAME_PATTERN)


# ---------------------------------------------------------------------------
# Value validators (shared with the service)
# ---------------------------------------------------------------------------


def family_version(family: StaticRouteFamily) -> int:
    """Return the IP version (4/6) for an API family label."""

    return 4 if family == "ipv4" else 6


def canonical_route_prefix(value: str, family: StaticRouteFamily | None = None) -> str:
    """Canonicalise a route prefix and optionally check its family.

    ``ip_network(..., strict=True)`` rejects host bits, so ``10.1.2.3/8`` is an
    error rather than being silently rewritten to ``10.0.0.0/8``.
    """

    if not isinstance(value, str):
        raise ValueError("Prefix must be a string in CIDR notation (for example 10.0.0.0/8)")
    text = value.strip()
    if "/" not in text:
        # ``ip_network`` would silently treat a bare address as a host route.
        raise ValueError("Prefix must use CIDR notation (for example 10.0.0.0/8)")
    try:
        network = ipaddress.ip_network(text, strict=True)
    except ValueError as exc:
        raise ValueError(
            "Prefix must be a valid IPv4/IPv6 network in CIDR notation with host bits set to zero"
        ) from exc
    if family is not None and network.version != family_version(family):
        raise ValueError(
            f"Prefix {network} is IPv{network.version} but the route family is {family}"
        )
    return str(network)


def canonical_host_address(value: str) -> str:
    """Canonicalise a next-hop host address (IPv6 is compressed)."""

    if not isinstance(value, str):
        raise ValueError("Next-hop address must be an IPv4 or IPv6 host address")
    text = value.strip()
    try:
        return str(ipaddress.ip_address(text))
    except ValueError as exc:
        raise ValueError(
            "Next-hop address must be a single IPv4 or IPv6 host address without a prefix length"
        ) from exc


def validate_interface_name(value: str) -> str:
    """Validate a VyOS interface name (``eth0``, ``br0``, ``eth0.100``, ...)."""

    if not isinstance(value, str):
        raise ValueError("Interface name must be a string")
    text = value.strip()
    if not INTERFACE_NAME_RE.match(text):
        raise ValueError(
            "Interface name must be a VyOS interface such as eth0, br0, eth0.100, wg0, tun0 or lo"
        )
    return text


def route_type(blackhole: bool, reject: bool) -> str:
    """Return the route kind as used in audit details."""

    if blackhole:
        return "blackhole"
    if reject:
        return "reject"
    return "unicast"


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


def _blank_to_none(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Must be a string or null")
    return value.strip() or None


# ---------------------------------------------------------------------------
# Next hop
# ---------------------------------------------------------------------------


class StaticNextHop(ApiModel):
    """One unicast next hop, addressed, interface-only or both.

    The family is a property of the containing route, so this model only
    enforces address syntax; ``StaticRouteCreate`` / ``StaticRouteRead`` check
    that the address matches the route family.
    """

    address: str | None = None
    interface: str | None = None
    distance: int | None = Field(default=None, ge=DISTANCE_MIN, le=DISTANCE_MAX)
    enabled: bool = True

    @field_validator("address", mode="before")
    @classmethod
    def _address(cls, value: object) -> str | None:
        text = _blank_to_none(value)
        return canonical_host_address(text) if text is not None else None

    @field_validator("interface", mode="before")
    @classmethod
    def _interface(cls, value: object) -> str | None:
        text = _blank_to_none(value)
        return validate_interface_name(text) if text is not None else None

    @field_validator("distance", mode="before")
    @classmethod
    def _not_boolean(cls, value: object) -> object:
        return _reject_boolean(value)

    @model_validator(mode="after")
    def _requires_a_target(self) -> Self:
        if self.address is None and self.interface is None:
            raise ValueError("A next hop requires an address, an interface, or both")
        return self


# ---------------------------------------------------------------------------
# Route models
# ---------------------------------------------------------------------------


class _StaticRouteBase(ApiModel):
    """Managed fields shared by the read and write models.

    ``family`` / ``prefix`` are optional here so that ``StaticRouteUpdate`` can
    tolerate a round-tripped read body; the concrete read/create models make
    them required without changing the field order (Pydantic keeps the position
    of a redeclared inherited field).  That ordering matters: the ``prefix`` and
    ``next_hops`` validators need the already-validated ``family``.
    """

    family: StaticRouteFamily | None = None
    prefix: str | None = None
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    blackhole: bool = False
    reject: bool = False
    distance: int | None = Field(default=None, ge=DISTANCE_MIN, le=DISTANCE_MAX)
    tag: int | None = Field(default=None, ge=TAG_MIN, le=TAG_MAX)
    next_hops: list[StaticNextHop] = Field(default_factory=list)

    @field_validator("prefix", mode="before")
    @classmethod
    def _prefix(cls, value: object, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Prefix must be a string in CIDR notation")
        family = info.data.get("family")
        return canonical_route_prefix(value, family if family in STATIC_ROUTE_FAMILIES else None)

    @field_validator("description", mode="after")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return _clean_description(value)

    @field_validator("distance", "tag", mode="before")
    @classmethod
    def _not_boolean(cls, value: object) -> object:
        return _reject_boolean(value)

    @field_validator("next_hops", mode="after")
    @classmethod
    def _next_hops(cls, value: list[StaticNextHop], info: ValidationInfo) -> list[StaticNextHop]:
        seen: set[tuple[str | None, str | None]] = set()
        for hop in value:
            key = (hop.address, hop.interface)
            if key in seen:
                address = hop.address or "-"
                interface = hop.interface or "-"
                raise ValueError(
                    f"Duplicate next hop (address, interface) pair: ({address}, {interface})"
                )
            seen.add(key)

        family = info.data.get("family")
        if family in STATIC_ROUTE_FAMILIES:
            expected = family_version(family)
            for hop in value:
                if hop.address is None:
                    continue
                version = ipaddress.ip_address(hop.address).version
                if version != expected:
                    raise ValueError(
                        f"Next-hop address {hop.address} is IPv{version} but the "
                        f"route family is {family}"
                    )
        return value

    @model_validator(mode="after")
    def _route_shape(self) -> Self:
        if self.blackhole and self.reject:
            raise ValueError("A static route cannot be both blackhole and reject")
        if self.blackhole or self.reject:
            if self.next_hops:
                raise ValueError("A blackhole or reject route must not have next hops")
            return self
        if self.distance is not None or self.tag is not None:
            raise ValueError("distance and tag are only valid on blackhole or reject routes")
        if not self.next_hops:
            raise ValueError("A unicast static route requires at least one next hop")
        return self


class StaticRouteRead(_StaticRouteBase):
    """One static route as exposed by the API."""

    family: StaticRouteFamily
    prefix: str


class StaticRouteCreate(_StaticRouteBase):
    """Create body for ``POST /static-routes``."""

    family: StaticRouteFamily
    prefix: str


class StaticRouteUpdate(_StaticRouteBase):
    """Full replacement body for ``PUT /static-routes/{family}/{prefix}``.

    ``family`` and ``prefix`` are immutable; when present they are validated for
    shape but the path parameters win.  Omitted managed fields reset to their
    defaults (``description``/``distance``/``tag`` cleared, ``enabled`` true).
    """


class StaticRouteList(ApiModel):
    """``GET /static-routes`` response."""

    items: list[StaticRouteRead] = Field(default_factory=list)
    total: int = 0


__all__ = [
    "DESCRIPTION_MAX_LENGTH",
    "DISTANCE_MAX",
    "DISTANCE_MIN",
    "INTERFACE_NAME_PATTERN",
    "STATIC_ROUTE_FAMILIES",
    "TAG_MAX",
    "TAG_MIN",
    "StaticNextHop",
    "StaticRouteCreate",
    "StaticRouteFamily",
    "StaticRouteList",
    "StaticRouteRead",
    "StaticRouteUpdate",
    "canonical_host_address",
    "canonical_route_prefix",
    "family_version",
    "route_type",
    "validate_interface_name",
]
