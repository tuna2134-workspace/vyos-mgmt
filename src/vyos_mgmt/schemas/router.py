from __future__ import annotations

import ipaddress
import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from vyos_mgmt.db.models import RouterDriver
from vyos_mgmt.schemas.common import ApiModel

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$"
)


def validate_host(value: str) -> str:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    if not value or any(ch.isspace() for ch in value):
        raise ValueError("Host must not be empty or contain whitespace")
    if "://" in value or "/" in value or "@" in value:
        raise ValueError("Host must be a plain hostname or IP address, not a URL")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if not _HOSTNAME_RE.match(value):
        raise ValueError("Host is not a valid hostname or IP address")
    return value


def validate_router_name(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 100:
        raise ValueError("Name must be between 1 and 100 characters")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("Name must not contain control characters")
    return value


class RouterCreate(ApiModel):
    name: str
    host: str
    port: int = Field(default=443, ge=1, le=65535)
    protocol: Literal["https", "http"] = "https"
    api_key: str | None = Field(default=None, max_length=512)
    verify_tls: bool = True
    driver: RouterDriver = RouterDriver.PYVYOS
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return validate_router_name(value)

    @field_validator("host")
    @classmethod
    def _host(cls, value: str) -> str:
        return validate_host(value)

    @field_validator("api_key")
    @classmethod
    def _api_key(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("API key must not be blank")
        return value

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            return value or None
        return value


class RouterUpdate(ApiModel):
    name: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    protocol: Literal["https", "http"] | None = None
    api_key: str | None = Field(default=None, max_length=512)
    verify_tls: bool | None = None
    driver: RouterDriver | None = None
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return validate_router_name(value) if value is not None else None

    @field_validator("host")
    @classmethod
    def _host(cls, value: str | None) -> str | None:
        return validate_host(value) if value is not None else None

    @field_validator("api_key")
    @classmethod
    def _api_key(cls, value: str | None) -> str | None:
        if value == "":
            return None
        if value is not None and not value.strip():
            raise ValueError("API key must not be blank")
        return value

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            return value or None
        return value


class RouterRead(ApiModel):
    id: uuid.UUID
    name: str
    host: str
    port: int
    protocol: str
    verify_tls: bool
    driver: RouterDriver
    description: str | None
    api_key_configured: bool = False
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class RouterList(ApiModel):
    items: list[RouterRead]
    total: int


class SystemInfo(ApiModel):
    hostname: str | None = None
    version: str | None = None
    uptime: str | None = None
    driver: RouterDriver
    reachable: bool
    latency_ms: float
    error: str | None = None
