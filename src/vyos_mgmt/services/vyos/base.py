"""Driver abstraction between the management API and VyOS devices.

Only the operations needed by today's features are part of the protocol; the
generic ``get_config``/``show`` methods let future feature modules talk to the
device without changing the driver interface.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from vyos_mgmt.schemas.bgp import BgpStatus
from vyos_mgmt.schemas.router import SystemInfo

OpName = Literal["set", "delete"]


@dataclass(frozen=True, slots=True)
class DeviceTarget:
    """Everything a driver needs, decoupled from the ORM model."""

    id: uuid.UUID
    name: str
    host: str
    port: int
    protocol: str
    api_key: str
    verify_tls: bool
    driver: str
    timeout: int = 10


@dataclass(frozen=True, slots=True)
class ConfigOp:
    op: OpName
    path: list[str]

    def as_payload(self) -> dict[str, Any]:
        return {"op": self.op, "path": self.path}


class VyosError(Exception):
    """Base class for device interaction failures."""


class VyosConnectionError(VyosError):
    """The device could not be reached (DNS, TCP, TLS or timeout)."""


class VyosCommandError(VyosError):
    """The device responded, but rejected the command."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class VyosPathNotFound(VyosCommandError):
    """A configuration subtree does not exist (often simply "not configured")."""


class VyosConfigurationError(VyosError):
    """The stored router definition is not usable (for example a missing key)."""


class VyosDriver(Protocol):
    async def get_config(self, path: Sequence[str]) -> Any: ...

    async def show(self, path: Sequence[str]) -> str: ...

    async def apply(self, ops: Sequence[ConfigOp]) -> None: ...

    async def get_bgp_status(self) -> BgpStatus: ...

    async def get_system_info(self) -> SystemInfo: ...

    async def close(self) -> None: ...
