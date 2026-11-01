"""pyvyos-backed driver: real VyOS devices reached over the HTTPS API."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Sequence
from typing import Any

import requests
from pyvyos import VyDevice

from vyos_mgmt.db.models import RouterDriver
from vyos_mgmt.schemas.bgp import BgpStatus
from vyos_mgmt.schemas.router import SystemInfo
from vyos_mgmt.services.vyos.base import (
    ConfigOp,
    DeviceTarget,
    VyosCommandError,
    VyosConnectionError,
    VyosPathNotFound,
)
from vyos_mgmt.services.vyos.bgp_parser import parse_bgp_summary, parse_version

_PATH_MISSING_MARKERS = (
    "not found",
    "does not exist",
    "no such",
    "not configured",
)


def _bracket_host(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


class PyvyosDriver:
    def __init__(self, target: DeviceTarget) -> None:
        self._target = target
        self._device = VyDevice(
            hostname=_bracket_host(target.host),
            apikey=target.api_key,
            protocol=target.protocol,
            port=target.port,
            verify=target.verify_tls,
            timeout=target.timeout,
        )

    async def _call(self, func, *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except requests.RequestException as exc:
            raise VyosConnectionError(
                f"Could not reach {self._target.host}:{self._target.port} "
                f"({type(exc).__name__}: {exc})"
            ) from exc
        except OSError as exc:
            raise VyosConnectionError(f"Network error: {exc}") from exc
        except (ValueError, RuntimeError) as exc:
            raise VyosCommandError(f"Invalid VyOS API response: {exc}") from exc

    @staticmethod
    def _unwrap(response) -> Any:
        if response.error:
            message = str(response.error)
            if any(marker in message.lower() for marker in _PATH_MISSING_MARKERS):
                raise VyosPathNotFound(message, status=response.status)
            raise VyosCommandError(message, status=response.status)
        return response.result

    async def get_config(self, path: Sequence[str]) -> Any:
        response = await self._call(self._device.retrieve_show_config, list(path))
        result = self._unwrap(response)
        return {} if result is None else result

    async def show(self, path: Sequence[str]) -> str:
        response = await self._call(self._device.show, list(path))
        result = self._unwrap(response)
        if isinstance(result, str):
            return result
        return json.dumps(result, indent=2)

    async def apply(self, ops: Sequence[ConfigOp]) -> None:
        if not ops:
            return
        response = await self._call(
            self._device.configure_multiple_op,
            [op.as_payload() for op in ops],
        )
        self._unwrap(response)

    async def get_bgp_status(self) -> BgpStatus:
        try:
            output = await self.show(["bgp", "summary"])
        except VyosPathNotFound as exc:
            return BgpStatus(configured=False, error=str(exc))
        except VyosCommandError as exc:
            message = str(exc).lower()
            if any(marker in message for marker in ("not configured", "not running")):
                return BgpStatus(configured=False, error=str(exc))
            raise
        status = parse_bgp_summary(output)
        return status

    async def get_system_info(self) -> SystemInfo:
        started = time.perf_counter()
        version_text = await self.show(["version"])
        version, uptime = parse_version(version_text)

        hostname: str | None = None
        try:
            raw_hostname = await self.get_config(["system", "host-name"])
            if isinstance(raw_hostname, str):
                hostname = raw_hostname
            elif isinstance(raw_hostname, dict):
                value = raw_hostname.get("host-name")
                if isinstance(value, str):
                    hostname = value
        except VyosPathNotFound:
            hostname = None

        elapsed = (time.perf_counter() - started) * 1000
        return SystemInfo(
            hostname=hostname,
            version=version,
            uptime=uptime,
            driver=RouterDriver.PYVYOS,
            reachable=True,
            latency_ms=round(elapsed, 2),
        )

    async def close(self) -> None:
        return None
