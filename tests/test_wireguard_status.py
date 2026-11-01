"""WireGuard operational status parsing and service tests."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import pytest

from vyos_mgmt.db.models import Router
from vyos_mgmt.services.vyos.base import (
    ConfigOp,
    DeviceTarget,
    VyosCommandError,
    VyosConnectionError,
)
from vyos_mgmt.services.vyos.mock_driver import (
    WIREGUARD_SEED_PRIVATE_KEY,
    MockDriver,
)
from vyos_mgmt.services.wireguard_service import (
    WireGuardInterfaceNotFoundError,
    WireGuardService,
    derive_public_key,
    parse_wireguard_summary,
)

PUBLIC_KEY = "EKY0dxRrSD98QHjfHOK13mZ5PJ7hnddRZt5woB3szyw="
PEER_ONE = "XMrlPykaxhdAAiSjhtPlvi30NVkvLQliQuKP7AI7CyI="
PEER_TWO = "4Krkv8h6NkAYMMaBWI957yYDJDMvj9URTHstdlOcDU0="

SUMMARY = """interface: wg0
  public key: EKY0dxRrSD98QHjfHOK13mZ5PJ7hnddRZt5woB3szyw=
  private key: (hidden)
  listening port: 51820

peer: XMrlPykaxhdAAiSjhtPlvi30NVkvLQliQuKP7AI7CyI=
  endpoint: 198.51.100.10:51820
  allowed ips: 192.168.50.0/24, 2001:db8:50::/64
  latest handshake: 23 hours, 45 minutes, 26 seconds ago
  transfer: 1.26 MiB received, 6.47 MiB sent

peer: 4Krkv8h6NkAYMMaBWI957yYDJDMvj9URTHstdlOcDU0=
  endpoint: [2001:db8::20]:51900
  allowed ips: 10.200.0.5/32
  latest handshake: Never
  transfer: 0 B received, 0 B sent
"""


def make_target() -> DeviceTarget:
    return DeviceTarget(
        id=uuid.uuid4(),
        name="mock-wireguard-status",
        host="127.0.0.1",
        port=443,
        protocol="https",
        api_key="",
        verify_tls=False,
        driver="mock",
        timeout=1,
    )


async def make_service() -> tuple[WireGuardService, MockDriver]:
    target = make_target()
    driver = MockDriver(target)
    return WireGuardService(driver, Router(id=target.id, name="mock-wireguard-status")), driver


class ShowOverrideDriver:
    """Delegate config/apply to the mock driver but override ``show``."""

    def __init__(
        self,
        inner: MockDriver,
        *,
        output: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.inner = inner
        self.output = output
        self.error = error

    async def get_config(self, path: Sequence[str]) -> Any:
        return await self.inner.get_config(path)

    async def show(self, path: Sequence[str]) -> str:
        if self.error is not None:
            raise self.error
        return self.output or ""

    async def apply(self, ops: Sequence[ConfigOp]) -> None:
        await self.inner.apply(ops)

    async def close(self) -> None:
        return None


def test_parse_summary_multiple_peers_and_variants() -> None:
    public_key, listening_port, peers = parse_wireguard_summary(SUMMARY)
    assert public_key == PUBLIC_KEY
    assert listening_port == 51820
    assert [peer.public_key for peer in peers] == [PEER_ONE, PEER_TWO]

    first = peers[0]
    assert first.endpoint == "198.51.100.10:51820"
    assert first.allowed_ips == ["192.168.50.0/24", "2001:db8:50::/64"]
    assert first.latest_handshake == "23 hours, 45 minutes, 26 seconds ago"
    assert first.transfer_received == "1.26 MiB"
    assert first.transfer_sent == "6.47 MiB"

    second = peers[1]
    assert second.endpoint == "[2001:db8::20]:51900"
    assert second.allowed_ips == ["10.200.0.5/32"]
    assert second.latest_handshake == "Never"
    assert second.transfer_received == "0 B"
    assert second.transfer_sent == "0 B"


def test_parse_summary_skips_invalid_peer_keys_and_missing_fields() -> None:
    output = """interface: wg0
  public key: not-a-key
  listening port: not-a-port

peer: not-a-key
  allowed ips: not-a-prefix
  transfer: unexpected

peer: XMrlPykaxhdAAiSjhtPlvi30NVkvLQliQuKP7AI7CyI=
  allowed ips: 10.0.0.0/8
"""
    public_key, listening_port, peers = parse_wireguard_summary(output)
    assert public_key is None
    assert listening_port is None
    assert [peer.public_key for peer in peers] == [PEER_ONE]
    assert peers[0].latest_handshake is None
    assert peers[0].transfer_received is None
    assert peers[0].transfer_sent is None
    assert peers[0].endpoint is None


def test_parse_summary_without_interface_block() -> None:
    assert parse_wireguard_summary("") == (None, None, [])
    assert parse_wireguard_summary("WireGuard interface wg0 is not running\n") == (
        None,
        None,
        [],
    )


async def test_status_for_seeded_interface() -> None:
    service, _driver = await make_service()
    status = await service.get_status("wg0")

    assert status.configured is True
    assert status.name == "wg0"
    assert status.public_key == derive_public_key(WIREGUARD_SEED_PRIVATE_KEY)
    assert status.listening_port == 51820
    assert status.error is None
    assert status.collected_at.tzinfo is not None
    assert len(status.peers) == 2
    assert status.peers[0].endpoint == "198.51.100.10:51820"
    assert status.peers[0].transfer_received == "1.26 MiB"
    assert status.peers[1].endpoint is None
    assert status.peers[1].allowed_ips == ["10.200.0.5/32"]

    dumped = status.model_dump_json()
    assert WIREGUARD_SEED_PRIVATE_KEY not in dumped


async def test_status_missing_interface_is_not_found() -> None:
    service, _driver = await make_service()
    with pytest.raises(WireGuardInterfaceNotFoundError):
        await service.get_status("wg9")


async def test_disabled_interface_reports_error_with_config_metadata() -> None:
    service, driver = await make_service()
    await driver.apply([ConfigOp("set", ["interfaces", "wireguard", "wg0", "disable"])])

    status = await service.get_status("wg0")
    assert status.configured is True
    assert status.error is not None
    assert "disabled" in status.error
    assert status.peers == []
    assert status.public_key == derive_public_key(WIREGUARD_SEED_PRIVATE_KEY)
    assert status.listening_port == 51820


async def test_not_running_output_reports_error() -> None:
    service, driver = await make_service()
    override = ShowOverrideDriver(
        driver,
        output="WireGuard interface wg0 is configured but the device is not running\n",
    )
    service = WireGuardService(override, Router(id=uuid.uuid4(), name="mock"))

    status = await service.get_status("wg0")
    assert status.configured is True
    assert status.error is not None
    assert "not running" in status.error
    assert status.peers == []
    assert status.public_key == derive_public_key(WIREGUARD_SEED_PRIVATE_KEY)


async def test_command_error_becomes_status_error() -> None:
    service, driver = await make_service()
    override = ShowOverrideDriver(
        driver, error=VyosCommandError("WireGuard interface wg0 is not running")
    )
    service = WireGuardService(override, Router(id=uuid.uuid4(), name="mock"))

    status = await service.get_status("wg0")
    assert status.error == "WireGuard interface wg0 is not running"
    assert status.peers == []


async def test_empty_output_reports_error() -> None:
    service, driver = await make_service()
    override = ShowOverrideDriver(driver, output="")
    service = WireGuardService(override, Router(id=uuid.uuid4(), name="mock"))

    status = await service.get_status("wg0")
    assert status.error is not None
    assert status.peers == []


async def test_connection_error_propagates_for_502_mapping() -> None:
    service, driver = await make_service()
    override = ShowOverrideDriver(driver, error=VyosConnectionError("unreachable"))
    service = WireGuardService(override, Router(id=uuid.uuid4(), name="mock"))

    with pytest.raises(VyosConnectionError):
        await service.get_status("wg0")


async def test_unexpected_command_error_propagates() -> None:
    service, driver = await make_service()
    override = ShowOverrideDriver(driver, error=VyosCommandError("permission denied"))
    service = WireGuardService(override, Router(id=uuid.uuid4(), name="mock"))

    with pytest.raises(VyosCommandError):
        await service.get_status("wg0")


async def test_public_key_comes_from_config_even_if_output_differs() -> None:
    service, driver = await make_service()
    override = ShowOverrideDriver(
        driver,
        output="""interface: wg0
  public key: XMrlPykaxhdAAiSjhtPlvi30NVkvLQliQuKP7AI7CyI=
  listening port: 51820
""",
    )
    service = WireGuardService(override, Router(id=uuid.uuid4(), name="mock"))

    status = await service.get_status("wg0")
    assert status.public_key == derive_public_key(WIREGUARD_SEED_PRIVATE_KEY)
    assert status.public_key != PEER_ONE
