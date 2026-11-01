"""Schemas for the policy prefix-list feature.

VyOS stores IPv4 prefix lists under ``policy prefix-list`` and IPv6 prefix
lists under ``policy prefix-list6``.  The API identifies an object by the
``family`` + ``name`` pair because both trees may contain the same name.

A prefix-list rule is a prefix plus optional ``ge``/``le`` bounds:

* ``ge`` is the minimum prefix length to match (``>=`` the prefix length),
* ``le`` is the maximum prefix length to match (``>=`` the prefix length),
* when both are present ``ge <= le``,
* ``null`` for both means an exact-length match.

The rule body does not carry a family; it is inferred from the prefix and the
service additionally checks that the prefix matches the list's family.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator

from vyos_mgmt.schemas.common import ApiModel

PrefixListFamily = Literal["ipv4", "ipv6"]
PrefixListAction = Literal["permit", "deny"]

PREFIX_LIST_FAMILIES: tuple[PrefixListFamily, ...] = ("ipv4", "ipv6")
PREFIX_LIST_MAX_LENGTH: dict[PrefixListFamily, int] = {"ipv4": 32, "ipv6": 128}
# VyOS allows [-_a-zA-Z0-9.]+; the API uses the same safe subset as the other
# policy objects (must start alphanumeric, max 128 chars).
PREFIX_LIST_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
PREFIX_LIST_NAME_RE = re.compile(PREFIX_LIST_NAME_PATTERN)
RULE_NUMBER_MAX = 65_535


def validate_prefix_list_name(value: str) -> str:
    """Validate a prefix-list name (IPv4 and IPv6 names are independent)."""

    value = value.strip()
    if not PREFIX_LIST_NAME_RE.match(value):
        raise ValueError(
            "Prefix-list names must start with a letter or digit and contain only "
            "letters, digits, dot, underscore or hyphen (max 128 chars)"
        )
    return value


def canonical_prefix(value: str) -> str:
    """Return the canonical CIDR string; host bits must already be zero."""

    try:
        network = ipaddress.ip_network(value.strip(), strict=True)
    except ValueError as exc:
        raise ValueError(
            "Prefix must be a valid network in CIDR notation (host bits must be zero)"
        ) from exc
    return str(network)


def prefix_version(value: str) -> int:
    return ipaddress.ip_network(value, strict=True).version


def _clean_description(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class PrefixListRuleBase(ApiModel):
    """Managed fields shared by prefix-list rule reads and writes."""

    action: PrefixListAction
    prefix: str
    ge: int | None = None
    le: int | None = None
    description: str | None = Field(default=None, max_length=255)

    @field_validator("prefix", mode="before")
    @classmethod
    def _prefix(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Prefix must be a string in CIDR notation")
        return canonical_prefix(value)

    @field_validator("ge", "le", mode="before")
    @classmethod
    def _not_boolean(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("Must be an integer prefix length, not a boolean")
        return value

    @field_validator("ge", "le", mode="after")
    @classmethod
    def _bounds(cls, value: int | None, info: ValidationInfo) -> int | None:
        if value is None:
            return None
        prefix = info.data.get("prefix")
        if not isinstance(prefix, str):  # pragma: no cover - prefix is required
            return value
        network = ipaddress.ip_network(prefix, strict=True)
        maximum = network.max_prefixlen
        if not 0 <= value <= maximum:
            raise ValueError(f"Must be between 0 and {maximum} for IPv{network.version}")
        if value < network.prefixlen:
            raise ValueError(
                f"Must be greater than or equal to the prefix length ({network.prefixlen})"
            )
        if info.field_name == "le":
            ge = info.data.get("ge")
            if isinstance(ge, int) and ge > value:
                raise ValueError("le must be greater than or equal to ge")
        return value

    @field_validator("description", mode="after")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return _clean_description(value)


class PrefixListRuleRead(PrefixListRuleBase):
    number: int = Field(ge=1, le=RULE_NUMBER_MAX)


class PrefixListRuleCreate(PrefixListRuleBase):
    number: int = Field(ge=1, le=RULE_NUMBER_MAX)


class PrefixListRuleUpdate(PrefixListRuleBase):
    """Full replacement body for ``PUT .../rules/{number}``.

    The path number is authoritative.  ``number`` is accepted and ignored so a
    client can send back an object it received from ``GET``.
    """

    number: int | None = Field(default=None, ge=1, le=RULE_NUMBER_MAX)


class PrefixListCreate(ApiModel):
    name: str
    family: PrefixListFamily
    description: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return validate_prefix_list_name(value)

    @field_validator("description", mode="after")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return _clean_description(value)


class PrefixListUpdate(ApiModel):
    """Description-only update; rules have dedicated endpoints."""

    description: str | None = Field(default=None, max_length=255)

    @field_validator("description", mode="after")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        return _clean_description(value)


class PrefixListRead(ApiModel):
    name: str
    family: PrefixListFamily
    description: str | None = None
    rules: list[PrefixListRuleRead] = Field(default_factory=list)
    in_use: bool = False
    used_by: list[str] = Field(default_factory=list)


class PrefixListList(ApiModel):
    items: list[PrefixListRead] = Field(default_factory=list)
    total: int = 0
