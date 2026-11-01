"""Schemas for the route-map feature.

Route maps are a VyOS ``policy route-map`` object: a named list of numbered
rules, each with match conditions and attribute-changing set actions.  The API
keeps the wire format close to the device tree but validates every value so an
invalid request can never reach a device commit.

Names are validated for *shape* only: the referenced prefix-list, AS-path and
community-list objects are managed on the router and may not exist yet.  The
route-map name itself is limited to 64 characters (the documented VyOS limit),
while referenced policy object names allow 128 characters because some VyOS
versions support longer policy object names.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from vyos_mgmt.schemas.common import ApiModel

RouteMapAction = Literal["permit", "deny"]
RouteMapOnMatch = Literal["next", "goto"]
RouteMapOrigin = Literal["igp", "egp", "incomplete"]
RouteMapRpki = Literal["invalid", "notfound", "valid"]
RouteMapProtocol = Literal[
    "babel",
    "bgp",
    "connected",
    "isis",
    "kernel",
    "ospf",
    "ospfv3",
    "rip",
    "ripng",
    "static",
    "table",
    "vnc",
]
RouteMapMetricType = Literal["type-1", "type-2"]
CommunityAction = Literal["add", "replace", "delete", "none"]

ASN_MAX = 4_294_967_295
RULE_NUMBER_MAX = 65_535

ROUTE_MAP_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
ROUTE_MAP_NAME_RE = re.compile(ROUTE_MAP_NAME_PATTERN)
# Policy object names (prefix-list, community-list, ...) can be a little longer
# on modern VyOS, but stay within a safe, bounded character set.
POLICY_OBJECT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_INTERFACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
_COMMUNITY_RE = re.compile(r"^(?P<as>\d{1,5}):(?P<value>\d{1,5})$")
_METRIC_RE = re.compile(r"^[+-]?(?:rtt|\d+)$", re.IGNORECASE)

WELL_KNOWN_COMMUNITIES = frozenset(
    {
        "accept-own",
        "accept-own-nexthop",
        "blackhole",
        "graceful-shutdown",
        "llgr-stale",
        "local-as",
        "no-advertise",
        "no-export",
        "no-llgr",
        "no-peer",
        "route-filter-translated-v4",
        "route-filter-translated-v6",
        "route-filter-v4",
        "route-filter-v6",
    }
)


def validate_route_map_name(value: str) -> str:
    """Validate a route-map name (also used for ``call`` targets)."""

    value = value.strip()
    if not ROUTE_MAP_NAME_RE.match(value):
        raise ValueError(
            "Route-map names must start with a letter or digit and contain only "
            "letters, digits, dot, underscore or hyphen (max 64 chars)"
        )
    return value


def _validate_object_name(value: str, label: str) -> str:
    value = value.strip()
    if not POLICY_OBJECT_NAME_RE.match(value):
        raise ValueError(
            f"{label} must start with a letter or digit and contain only letters, "
            "digits, dot, underscore or hyphen (max 128 chars)"
        )
    return value


def validate_community_value(value: str) -> str:
    """Normalise a BGP community value or well-known community name."""

    text = value.strip().lower()
    if text in WELL_KNOWN_COMMUNITIES:
        return text
    match = _COMMUNITY_RE.match(text)
    if match is None:
        raise ValueError(
            "Community must be AS:VALUE with both parts 0-65535 or a well-known "
            f"name ({', '.join(sorted(WELL_KNOWN_COMMUNITIES))})"
        )
    autonomous_system = int(match.group("as"))
    community_value = int(match.group("value"))
    if autonomous_system > 65_535 or community_value > 65_535:
        raise ValueError("Both parts of a community must be between 0 and 65535")
    return f"{autonomous_system}:{community_value}"


def validate_metric(value: str | int | None) -> str | None:
    """Validate a ``set metric`` expression and return its canonical string.

    Accepted forms: ``0-4294967295``, ``+N``, ``-N``, ``rtt``, ``+rtt`` and
    ``-rtt``.  Integers are accepted for convenience and serialised as strings
    so the API shape is stable.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Metric must be a number or an rtt expression")
    if isinstance(value, int):
        if not 0 <= value <= ASN_MAX:
            raise ValueError("Metric must be between 0 and 4294967295")
        return str(value)
    if not isinstance(value, str):
        raise ValueError("Metric must be a number or an rtt expression")

    text = value.strip()
    if not text:
        return None
    if _METRIC_RE.match(text) is None:
        raise ValueError("Metric must be 0-4294967295, +N, -N, rtt, +rtt or -rtt")
    if text.lstrip("+-").lower() == "rtt":
        return text.lower()
    sign = text[0] if text[0] in "+-" else ""
    digits = text[1:] if sign else text
    number = int(digits)
    if not 0 <= number <= ASN_MAX:
        raise ValueError("Metric must be between 0 and 4294967295")
    return f"{sign}{number}"


def _validate_ipv4(value: str) -> str:
    try:
        return str(ipaddress.IPv4Address(value))
    except ValueError as exc:
        raise ValueError("Must be a valid IPv4 address") from exc


def _validate_ipv6(value: str) -> str:
    try:
        return str(ipaddress.IPv6Address(value))
    except ValueError as exc:
        raise ValueError("Must be a valid IPv6 address") from exc


def _clean_description(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class RouteMapMatch(ApiModel):
    """Match conditions supported by the managed route-map rule."""

    ipv4_prefix_list: str | None = None
    ipv6_prefix_list: str | None = None
    as_path: str | None = None
    community_list: str | None = None
    community_exact_match: bool = False
    large_community_list: str | None = None
    extcommunity: str | None = None
    metric: int | None = Field(default=None, ge=1, le=RULE_NUMBER_MAX)
    local_preference: int | None = Field(default=None, ge=0, le=ASN_MAX)
    origin: RouteMapOrigin | None = None
    tag: int | None = Field(default=None, ge=1, le=RULE_NUMBER_MAX)
    protocol: RouteMapProtocol | None = None
    rpki: RouteMapRpki | None = None
    ip_nexthop: str | None = None
    ipv6_nexthop: str | None = None
    interface: str | None = None

    @field_validator(
        "ipv4_prefix_list",
        "ipv6_prefix_list",
        "as_path",
        "community_list",
        "large_community_list",
        "extcommunity",
        mode="after",
    )
    @classmethod
    def _policy_object_names(cls, value: str | None) -> str | None:
        if not value:
            return None
        return _validate_object_name(value, "Policy object name")

    @field_validator("ip_nexthop", mode="after")
    @classmethod
    def _ip_nexthop(cls, value: str | None) -> str | None:
        return _validate_ipv4(value) if value else None

    @field_validator("ipv6_nexthop", mode="after")
    @classmethod
    def _ipv6_nexthop(cls, value: str | None) -> str | None:
        return _validate_ipv6(value) if value else None

    @field_validator("interface", mode="after")
    @classmethod
    def _interface(cls, value: str | None) -> str | None:
        if not value:
            return None
        value = value.strip()
        if not _INTERFACE_RE.match(value):
            raise ValueError("Invalid interface name")
        return value

    @model_validator(mode="after")
    def _community_coherence(self) -> RouteMapMatch:
        if self.community_exact_match and not self.community_list:
            raise ValueError("community_exact_match requires community_list")
        return self


class RouteMapSet(ApiModel):
    """Attribute changes applied by a matching rule."""

    local_preference: int | None = Field(default=None, ge=0, le=ASN_MAX)
    metric: str | int | None = None
    origin: RouteMapOrigin | None = None
    weight: int | None = Field(default=None, ge=0, le=ASN_MAX)
    metric_type: RouteMapMetricType | None = None
    tag: int | None = Field(default=None, ge=1, le=RULE_NUMBER_MAX)
    as_path_prepend: list[int] = Field(default_factory=list, max_length=20)
    community_action: CommunityAction | None = None
    community_values: list[str] = Field(default_factory=list)
    community_delete: str | None = None
    ip_next_hop: str | None = None
    originator_id: str | None = None

    @field_validator("metric", mode="before")
    @classmethod
    def _metric(cls, value: str | int | None) -> str | None:
        return validate_metric(value)

    @field_validator("as_path_prepend", mode="after")
    @classmethod
    def _as_path_prepend(cls, values: list[int]) -> list[int]:
        cleaned: list[int] = []
        for value in values:
            if not 1 <= value <= ASN_MAX:
                raise ValueError("AS numbers must be between 1 and 4294967295")
            cleaned.append(value)
        return cleaned

    @field_validator("community_values", mode="after")
    @classmethod
    def _community_values(cls, values: list[str]) -> list[str]:
        return [validate_community_value(value) for value in values]

    @field_validator("community_delete", mode="after")
    @classmethod
    def _community_delete(cls, value: str | None) -> str | None:
        if not value:
            return None
        return _validate_object_name(value, "Community-list name")

    @field_validator("ip_next_hop", mode="after")
    @classmethod
    def _ip_next_hop(cls, value: str | None) -> str | None:
        if not value:
            return None
        text = value.strip()
        if text in {"unchanged", "peer-address"}:
            return text
        return _validate_ipv4(text)

    @field_validator("originator_id", mode="after")
    @classmethod
    def _originator_id(cls, value: str | None) -> str | None:
        return _validate_ipv4(value) if value else None

    @model_validator(mode="after")
    def _community_coherence(self) -> RouteMapSet:
        action = self.community_action
        if action in {"add", "replace"}:
            if not self.community_values:
                raise ValueError("community_values is required for add/replace")
            if self.community_delete is not None:
                raise ValueError("community_delete is only valid with action 'delete'")
        elif action == "delete":
            if self.community_values:
                raise ValueError("community_values is only valid with add/replace")
            if self.community_delete is None:
                raise ValueError("community_delete is required for action 'delete'")
        elif self.community_values or self.community_delete is not None:
            raise ValueError(
                "community_values/community_delete require community_action "
                "'add', 'replace' or 'delete'"
            )
        return self


class RouteMapRuleBase(ApiModel):
    """Fields shared by rule reads and writes."""

    action: RouteMapAction
    description: str | None = Field(default=None, max_length=255)
    match: RouteMapMatch = Field(default_factory=RouteMapMatch)
    set: RouteMapSet = Field(default_factory=RouteMapSet)
    on_match: RouteMapOnMatch | None = None
    goto_rule: int | None = Field(default=None, ge=1, le=RULE_NUMBER_MAX)
    call: str | None = None
    continue_rule: int | None = Field(default=None, ge=1, le=RULE_NUMBER_MAX)

    @field_validator("description", mode="after")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return _clean_description(value)

    @field_validator("call", mode="after")
    @classmethod
    def _call(cls, value: str | None) -> str | None:
        return validate_route_map_name(value) if value else None

    @model_validator(mode="after")
    def _on_match_coherence(self) -> RouteMapRuleBase:
        if self.on_match == "goto":
            if self.goto_rule is None:
                raise ValueError("goto_rule is required when on_match is 'goto'")
            number = getattr(self, "number", None)
            if number is not None and self.goto_rule == number:
                raise ValueError("goto_rule must differ from the rule number")
        elif self.goto_rule is not None:
            raise ValueError("goto_rule requires on_match='goto'")
        return self


class RouteMapRuleRead(RouteMapRuleBase):
    number: int = Field(ge=1, le=RULE_NUMBER_MAX)


class RouteMapRuleCreate(RouteMapRuleBase):
    number: int = Field(ge=1, le=RULE_NUMBER_MAX)


class RouteMapRuleUpdate(RouteMapRuleBase):
    """Full replacement body for ``PUT .../rules/{number}``.

    The path number is authoritative.  ``number`` is accepted so clients can
    send back an object they received from ``GET``; it is ignored by the route
    handler.  Goto/rule-number consistency is additionally checked against the
    path number by the service.
    """

    number: int | None = Field(default=None, ge=1, le=RULE_NUMBER_MAX)


class RouteMapCreate(ApiModel):
    name: str
    description: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return validate_route_map_name(value)

    @field_validator("description", mode="after")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return _clean_description(value)


class RouteMapUpdate(ApiModel):
    """Description-only update; rules have dedicated endpoints."""

    description: str | None = Field(default=None, max_length=255)

    @field_validator("description", mode="after")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return _clean_description(value)


class RouteMapRead(ApiModel):
    name: str
    description: str | None = None
    rules: list[RouteMapRuleRead] = Field(default_factory=list)
    in_use: bool = False
    used_by: list[str] = Field(default_factory=list)


class RouteMapList(ApiModel):
    items: list[RouteMapRead] = Field(default_factory=list)
    total: int = 0
