"""Service tests for WireGuard against the in-memory VyOS emulator."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import pytest

from vyos_mgmt.db.models import Router
from vyos_mgmt.schemas.wireguard import (
    WireGuardInterfaceCreate,
    WireGuardInterfaceUpdate,
    WireGuardPeerCreate,
    WireGuardPeerUpdate,
    WireGuardPrivateKeyUpdate,
)
from vyos_mgmt.services.vyos.base import ConfigOp, DeviceTarget
from vyos_mgmt.services.vyos.mock_driver import (
    WIREGUARD_SEED_PEER_PUBLIC_KEY,
    WIREGUARD_SEED_PRESHARED_KEY,
    WIREGUARD_SEED_PRIVATE_KEY,
    WIREGUARD_SEED_ROAD_WARRIOR_PUBLIC_KEY,
    MockDriver,
)
from vyos_mgmt.services.wireguard_service import (
    WireGuardAllowedIpsConflictError,
    WireGuardInterfaceExistsError,
    WireGuardInterfaceNotFoundError,
    WireGuardPeerExistsError,
    WireGuardPeerNotFoundError,
    WireGuardPublicKeyConflictError,
    WireGuardService,
    generate_keypair,
    generate_preshared_key,
)

PRIVATE_KEY = "iJJyEARGK52Ls1GYRCcFvPuTj7WyWYDo//BknoDU0XY="
PUBLIC_KEY = "EKY0dxRrSD98QHjfHOK13mZ5PJ7hnddRZt5woB3szyw="
OTHER_PUBLIC_KEY = "XMrlPykaxhdAAiSjhtPlvi30NVkvLQliQuKP7AI7CyI="
THIRD_PUBLIC_KEY = "4Krkv8h6NkAYMMaBWI957yYDJDMvj9URTHstdlOcDU0="
PRESHARED_KEY = "OHH2EwZfMNK+1L6BXbYw3bKCtMrfjpR4mCAEeBlFnRs="


class CountingDriver:
    """Record every ``apply`` batch so atomicity can be asserted."""

    def __init__(self, inner: MockDriver) -> None:
        self.inner = inner
        self.batches: list[list[ConfigOp]] = []

    async def get_config(self, path: Sequence[str]) -> Any:
        return await self.inner.get_config(path)

    async def show(self, path: Sequence[str]) -> str:
        return await self.inner.show(path)

    async def apply(self, ops: Sequence[ConfigOp]) -> None:
        self.batches.append(list(ops))
        await self.inner.apply(ops)

    async def close(self) -> None:
        return None


def make_target() -> DeviceTarget:
    return DeviceTarget(
        id=uuid.uuid4(),
        name="mock-wireguard",
        host="127.0.0.1",
        port=443,
        protocol="https",
        api_key="",
        verify_tls=False,
        driver="mock",
        timeout=1,
    )


async def make_service() -> tuple[WireGuardService, CountingDriver]:
    target = make_target()
    driver = CountingDriver(MockDriver(target))
    return WireGuardService(driver, Router(id=target.id, name="mock-wireguard")), driver


def _peer_payload(name: str = "new-peer", **overrides: Any) -> WireGuardPeerCreate:
    payload: dict[str, Any] = {
        "name": name,
        "description": "New peer",
        "public_key": THIRD_PUBLIC_KEY,
        "allowed_ips": ["10.250.0.2/32"],
        "endpoint": "203.0.113.20",
        "endpoint_port": 51820,
        "persistent_keepalive": 25,
        "enabled": True,
    }
    payload.update(overrides)
    return WireGuardPeerCreate.model_validate(payload)


async def test_list_and_get_seeded_interface() -> None:
    service, _driver = await make_service()

    listing = await service.list()
    assert listing.total == 1
    assert [item.name for item in listing.items] == ["wg0"]

    interface = listing.items[0]
    assert interface.description == "Tokyo branch tunnel"
    assert interface.addresses == ["10.100.0.1/24", "2001:db8:100::1/64"]
    assert interface.port == 51820
    assert interface.mtu == 1420
    assert interface.enabled is True
    assert interface.public_key is not None
    assert interface.peer_count == 2

    detail = await service.get("wg0")
    assert [peer.name for peer in detail.peers] == ["branch-office", "road-warrior"]
    assert detail.peers[0].endpoint == "198.51.100.10"
    assert detail.peers[0].endpoint_port == 51820
    assert detail.peers[0].persistent_keepalive == 25
    assert detail.peers[0].has_preshared_key is True
    assert detail.peers[1].endpoint is None
    assert detail.peers[1].allowed_ips == ["10.200.0.5/32"]

    # Neither the seeded private key nor the preshared key appears in any read.
    dumped = detail.model_dump_json()
    assert WIREGUARD_SEED_PRIVATE_KEY not in dumped
    assert WIREGUARD_SEED_PRESHARED_KEY not in dumped

    with pytest.raises(WireGuardInterfaceNotFoundError):
        await service.get("wg1")


async def test_create_interface_is_atomic_and_returns_detail() -> None:
    service, driver = await make_service()
    payload = WireGuardInterfaceCreate(
        name="wg1",
        description="New tunnel",
        addresses=["10.9.0.1/24", "2001:db8:9::1/64"],
        port=51900,
        mtu=1400,
        private_key=PRIVATE_KEY,
    )
    created = await service.create(payload)
    assert created.name == "wg1"
    assert created.description == "New tunnel"
    assert created.addresses == ["10.9.0.1/24", "2001:db8:9::1/64"]
    assert created.port == 51900
    assert created.mtu == 1400
    assert created.enabled is True
    assert created.public_key is not None
    assert created.peers == []
    assert len(driver.batches) == 1

    raw = await driver.get_config(["interfaces", "wireguard", "wg1"])
    assert raw["private-key"] == PRIVATE_KEY
    assert raw["address"] == {"10.9.0.1/24": {}, "2001:db8:9::1/64": {}}

    with pytest.raises(WireGuardInterfaceExistsError):
        await service.create(payload)


async def test_update_interface_syncs_fields_and_preserves_unknown() -> None:
    service, driver = await make_service()
    await driver.apply([ConfigOp("set", ["interfaces", "wireguard", "wg0", "fwmark", "42"])])

    updated = await service.update(
        "wg0",
        WireGuardInterfaceUpdate(
            description="Changed",
            addresses=["10.100.0.1/24"],
            port=None,
            mtu=None,
            enabled=False,
        ),
    )
    assert updated.description == "Changed"
    assert updated.addresses == ["10.100.0.1/24"]
    assert updated.port is None
    assert updated.mtu is None
    assert updated.enabled is False

    raw = await driver.get_config(["interfaces", "wireguard", "wg0"])
    assert "fwmark" in raw  # unknown directive preserved
    assert raw["private-key"] == WIREGUARD_SEED_PRIVATE_KEY
    assert "peer" in raw  # peers untouched
    assert raw["address"] == {"10.100.0.1/24": {}}

    with pytest.raises(WireGuardInterfaceNotFoundError):
        await service.update("wg9", WireGuardInterfaceUpdate())


async def test_interface_update_without_changes_does_not_apply() -> None:
    service, driver = await make_service()
    await service.update(
        "wg0",
        WireGuardInterfaceUpdate(
            description="Tokyo branch tunnel",
            addresses=["10.100.0.1/24", "2001:db8:100::1/64"],
            port=51820,
            mtu=1420,
            enabled=True,
        ),
    )
    assert driver.batches == []


async def test_delete_interface_removes_peers() -> None:
    service, driver = await make_service()
    await service.delete("wg0")
    assert len(driver.batches) == 1
    with pytest.raises(WireGuardInterfaceNotFoundError):
        await service.get("wg0")
    with pytest.raises(WireGuardInterfaceNotFoundError):
        await service.delete("wg0")


async def test_private_key_rotation_changes_public_key_without_leaking_key() -> None:
    service, driver = await make_service()
    before = await service.get("wg0")
    private_key, public_key = generate_keypair()

    rotated = await service.rotate_private_key(
        "wg0", WireGuardPrivateKeyUpdate(private_key=private_key)
    )
    assert rotated.public_key == public_key
    assert rotated.public_key != before.public_key
    assert private_key not in rotated.model_dump_json()
    assert WIREGUARD_SEED_PRIVATE_KEY not in rotated.model_dump_json()
    assert len(driver.batches) == 1

    raw = await driver.get_config(["interfaces", "wireguard", "wg0"])
    assert raw["private-key"] == private_key

    with pytest.raises(WireGuardInterfaceNotFoundError):
        await service.rotate_private_key("wg9", WireGuardPrivateKeyUpdate(private_key=private_key))


async def test_peer_create_update_and_delete() -> None:
    service, driver = await make_service()
    payload = _peer_payload(preshared_key=PRESHARED_KEY)
    created = await service.create_peer("wg0", payload)
    assert len(driver.batches) == 1
    peer = next(item for item in created.peers if item.name == "new-peer")
    assert peer.public_key == THIRD_PUBLIC_KEY
    assert peer.allowed_ips == ["10.250.0.2/32"]
    assert peer.endpoint == "203.0.113.20"
    assert peer.endpoint_port == 51820
    assert peer.persistent_keepalive == 25
    assert peer.has_preshared_key is True
    assert peer.description == "New peer"
    assert PRESHARED_KEY not in created.model_dump_json()

    raw = await driver.get_config(["interfaces", "wireguard", "wg0", "peer", "new-peer"])
    assert raw["address"] == "203.0.113.20"
    assert raw["allowed-ips"] == {"10.250.0.2/32": {}}
    assert raw["preshared-key"] == PRESHARED_KEY

    updated = await service.update_peer(
        "wg0",
        "new-peer",
        WireGuardPeerUpdate(
            description="Changed",
            public_key=OTHER_PUBLIC_KEY,
            allowed_ips=["10.250.0.2/32", "2001:db8:250::/64"],
            endpoint="vpn.example.com",
            endpoint_port=51900,
            persistent_keepalive=None,
            enabled=False,
        ),
    )
    peer = next(item for item in updated.peers if item.name == "new-peer")
    assert peer.public_key == OTHER_PUBLIC_KEY
    assert peer.allowed_ips == ["10.250.0.2/32", "2001:db8:250::/64"]
    assert peer.endpoint == "vpn.example.com"
    assert peer.endpoint_port == 51900
    assert peer.persistent_keepalive is None
    assert peer.enabled is False
    assert peer.has_preshared_key is True  # omitted => preserved

    raw = await driver.get_config(["interfaces", "wireguard", "wg0", "peer", "new-peer"])
    assert raw["host-name"] == "vpn.example.com"
    assert "address" not in raw
    assert raw["preshared-key"] == PRESHARED_KEY

    await service.delete_peer("wg0", "new-peer")
    with pytest.raises(WireGuardPeerNotFoundError):
        await service.delete_peer("wg0", "new-peer")
    with pytest.raises(WireGuardPeerNotFoundError):
        await service.update_peer(
            "wg0",
            "new-peer",
            WireGuardPeerUpdate(public_key=PUBLIC_KEY, allowed_ips=["10.0.0.0/8"]),
        )
    with pytest.raises(WireGuardInterfaceNotFoundError):
        await service.create_peer("wg9", payload)


async def test_peer_preshared_key_replace_and_remove() -> None:
    service, driver = await make_service()
    replaced = generate_preshared_key()
    await service.update_peer(
        "wg0",
        "branch-office",
        WireGuardPeerUpdate(
            public_key=WIREGUARD_SEED_PEER_PUBLIC_KEY,
            allowed_ips=["192.168.50.0/24", "192.168.60.0/24"],
            endpoint="198.51.100.10",
            endpoint_port=51820,
            persistent_keepalive=25,
            preshared_key=replaced,
        ),
    )
    raw = await driver.get_config(["interfaces", "wireguard", "wg0", "peer", "branch-office"])
    assert raw["preshared-key"] == replaced

    await service.update_peer(
        "wg0",
        "branch-office",
        WireGuardPeerUpdate(
            public_key=WIREGUARD_SEED_PEER_PUBLIC_KEY,
            allowed_ips=["192.168.50.0/24", "192.168.60.0/24"],
            endpoint="198.51.100.10",
            endpoint_port=51820,
            persistent_keepalive=25,
            preshared_key=None,
        ),
    )
    raw = await driver.get_config(["interfaces", "wireguard", "wg0", "peer", "branch-office"])
    assert "preshared-key" not in raw
    detail = await service.get("wg0")
    branch = next(item for item in detail.peers if item.name == "branch-office")
    assert branch.has_preshared_key is False


async def test_peer_conflicts_and_update_excludes_self() -> None:
    service, _driver = await make_service()

    with pytest.raises(WireGuardPeerExistsError):
        await service.create_peer(
            "wg0",
            _peer_payload(name="branch-office", allowed_ips=["10.251.0.1/32"]),
        )

    with pytest.raises(WireGuardPublicKeyConflictError) as public_key_error:
        await service.create_peer(
            "wg0",
            _peer_payload(
                name="duplicate-key",
                public_key=WIREGUARD_SEED_PEER_PUBLIC_KEY,
                allowed_ips=["10.251.0.2/32"],
            ),
        )
    assert public_key_error.value.peer == "branch-office"

    with pytest.raises(WireGuardAllowedIpsConflictError) as allowed_error:
        await service.create_peer(
            "wg0",
            _peer_payload(
                name="duplicate-prefix",
                allowed_ips=["10.251.0.3/32", "192.168.50.0/24"],
            ),
        )
    assert allowed_error.value.allowed_ips == ["192.168.50.0/24"]
    assert allowed_error.value.peers == ["branch-office"]
    assert allowed_error.value.conflicts == [
        {"allowed_ip": "192.168.50.0/24", "peer": "branch-office"}
    ]

    # A peer never conflicts with itself on update.
    updated = await service.update_peer(
        "wg0",
        "branch-office",
        WireGuardPeerUpdate(
            description="Updated branch",
            public_key=WIREGUARD_SEED_PEER_PUBLIC_KEY,
            allowed_ips=["192.168.50.0/24", "192.168.60.0/24"],
            endpoint="198.51.100.10",
            endpoint_port=51820,
            persistent_keepalive=25,
            enabled=True,
        ),
    )
    assert next(item for item in updated.peers if item.name == "branch-office").description == (
        "Updated branch"
    )

    # But it does conflict with a different peer.
    with pytest.raises(WireGuardPublicKeyConflictError):
        await service.update_peer(
            "wg0",
            "road-warrior",
            WireGuardPeerUpdate(
                public_key=WIREGUARD_SEED_PEER_PUBLIC_KEY,
                allowed_ips=["10.200.0.5/32"],
            ),
        )
    with pytest.raises(WireGuardAllowedIpsConflictError):
        await service.update_peer(
            "wg0",
            "road-warrior",
            WireGuardPeerUpdate(
                public_key=WIREGUARD_SEED_ROAD_WARRIOR_PUBLIC_KEY,
                allowed_ips=["192.168.60.0/24"],
            ),
        )


async def test_peer_update_preserves_unknown_directives() -> None:
    service, driver = await make_service()
    await driver.apply(
        [
            ConfigOp(
                "set",
                [
                    "interfaces",
                    "wireguard",
                    "wg0",
                    "peer",
                    "road-warrior",
                    "vrf",
                    "mgmt",
                ],
            )
        ]
    )
    await service.update_peer(
        "wg0",
        "road-warrior",
        WireGuardPeerUpdate(
            description="Updated",
            public_key=WIREGUARD_SEED_ROAD_WARRIOR_PUBLIC_KEY,
            allowed_ips=["10.200.0.5/32"],
        ),
    )
    raw = await driver.get_config(["interfaces", "wireguard", "wg0", "peer", "road-warrior"])
    assert "vrf" in raw
    assert raw["description"] == "Updated"
