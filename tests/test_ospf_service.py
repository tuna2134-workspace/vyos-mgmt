"""Service tests for OSPF against the in-memory VyOS emulator."""

from __future__ import annotations

import uuid

import pytest

from vyos_mgmt.db.models import Router
from vyos_mgmt.schemas.ospf import (
    OspfAreaCreate,
    OspfAreaUpdate,
    OspfGlobal,
    OspfInterfaceCreate,
    OspfInterfaceUpdate,
    OspfRedistributeCreate,
    OspfRedistributeUpdate,
)
from vyos_mgmt.services.ospf_service import (
    OspfAreaExistsError,
    OspfAreaInUseError,
    OspfAreaNotFoundError,
    OspfAreaReferenceError,
    OspfInterfaceExistsError,
    OspfInterfaceNotFoundError,
    OspfRedistributeExistsError,
    OspfRedistributeNotFoundError,
    OspfRouteMapNotFoundError,
    OspfService,
    OspfValidationError,
)
from vyos_mgmt.services.vyos.base import (
    ConfigOp,
    DeviceTarget,
    VyosCommandError,
    VyosConnectionError,
    VyosPathNotFound,
)
from vyos_mgmt.services.vyos.mock_driver import MockDriver


def make_target() -> DeviceTarget:
    return DeviceTarget(
        id=uuid.uuid4(),
        name="mock-ospf",
        host="127.0.0.1",
        port=443,
        protocol="https",
        api_key="",
        verify_tls=False,
        driver="mock",
        timeout=1,
    )


async def make_service() -> tuple[OspfService, MockDriver]:
    target = make_target()
    driver = MockDriver(target)
    return OspfService(driver, Router(id=target.id, name="mock-ospf")), driver


def _recording_driver(driver: MockDriver) -> list[list[ConfigOp]]:
    calls: list[list[ConfigOp]] = []
    original = driver.apply

    async def wrapper(ops):  # type: ignore[no-untyped-def]
        calls.append(list(ops))
        await original(ops)

    driver.apply = wrapper  # type: ignore[method-assign]
    return calls


async def test_read_seeded_configuration() -> None:
    service, _driver = await make_service()

    v2 = await service.get_config("v2")
    assert v2.configured is True
    assert v2.router.name == "mock-ospf"
    assert v2.global_config.router_id == "10.255.0.1"
    assert v2.global_config.log_adjacency_changes == "detail"
    assert v2.global_config.default_information_originate is True
    assert v2.global_config.default_information_always is False
    assert [area.area_id for area in v2.areas] == ["0.0.0.0", "0.0.0.1"]
    assert v2.areas[1].area_type == "stub"
    assert v2.areas[1].no_summary is True
    assert v2.areas[1].interface_count == 1
    assert [interface.name for interface in v2.interfaces] == ["eth0", "eth1"]
    assert v2.interfaces[0].area_id == "0.0.0.0"
    assert v2.interfaces[1].passive is True
    assert [item.source for item in v2.redistributions] == ["connected"]
    assert v2.redistributions[0].route_map == "OSPF-OUT"

    v3 = await service.get_config("v3")
    assert v3.configured is True
    assert v3.global_config.default_information_always is True
    assert [area.area_id for area in v3.areas] == ["0.0.0.0", "0.0.0.2"]
    assert v3.areas[1].area_type == "nssa"
    assert v3.supported_network_types == ["broadcast", "point-to-point"]
    assert "ripng" in v3.supported_redistribute_sources


async def test_global_update_and_unknown_field_preservation() -> None:
    service, driver = await make_service()
    await driver.apply(
        [ConfigOp("set", ["protocols", "ospf", "default-information", "metric", "10"])]
    )
    calls = _recording_driver(driver)

    updated = await service.update_global(
        "v2",
        OspfGlobal(
            router_id="10.255.0.9",
            log_adjacency_changes="normal",
            auto_cost_reference_bandwidth=2000,
            default_information_originate=False,
            distance_global=120,
        ),
    )
    assert len(calls) == 1
    assert updated.global_config.router_id == "10.255.0.9"
    assert updated.global_config.log_adjacency_changes == "normal"
    assert updated.global_config.auto_cost_reference_bandwidth == 2000
    assert updated.global_config.default_information_originate is False
    assert updated.global_config.default_information_always is False
    assert updated.global_config.distance_global == 120

    raw = await driver.get_config(["protocols", "ospf", "default-information"])
    # ``metric`` is outside the managed surface and survives the update.
    assert raw == {"metric": "10"}

    # Log transitions exercise the detail child.
    detail = await service.update_global(
        "v2", OspfGlobal(log_adjacency_changes="detail", distance_global=120)
    )
    assert detail.global_config.log_adjacency_changes == "detail"
    none = await service.update_global(
        "v2", OspfGlobal(log_adjacency_changes="none", distance_global=120)
    )
    assert none.global_config.log_adjacency_changes == "none"
    raw = await driver.get_config(["protocols", "ospf"])
    assert "log-adjacency-changes" not in raw


async def test_area_crud_canonicalisation_and_unknown_fields() -> None:
    service, driver = await make_service()
    calls = _recording_driver(driver)

    created = await service.create_area(
        "v2", OspfAreaCreate(area_id="10", area_type="stub", no_summary=True)
    )
    assert len(calls) == 1
    area = next(item for item in created.areas if item.area_id == "0.0.0.10")
    assert area.area_type == "stub"
    assert area.no_summary is True

    with pytest.raises(OspfAreaExistsError):
        await service.create_area("v2", OspfAreaCreate(area_id="0.0.0.10"))

    await driver.apply(
        [
            ConfigOp(
                "set",
                ["protocols", "ospf", "area", "0.0.0.0", "range", "203.0.113.0/24"],
            )
        ]
    )
    updated = await service.update_area(
        "v2", "0.0.0.0", OspfAreaUpdate(area_type="stub", no_summary=True)
    )
    area = next(item for item in updated.areas if item.area_id == "0.0.0.0")
    assert area.area_type == "stub"
    assert area.no_summary is True
    raw_area = await driver.get_config(["protocols", "ospf", "area", "0.0.0.0"])
    assert raw_area["range"] == {"203.0.113.0/24": {}}

    with pytest.raises(OspfAreaNotFoundError):
        await service.update_area("v2", "0.0.0.99", OspfAreaUpdate())
    with pytest.raises(OspfAreaNotFoundError):
        await service.delete_area("v2", "0.0.0.99")

    # A decimal device key is resolved to the canonical API area ID.
    await driver.apply([ConfigOp("set", ["protocols", "ospf", "area", "20"])])
    decimal_update = await service.update_area(
        "v2", "0.0.0.20", OspfAreaUpdate(area_type="stub", no_summary=False)
    )
    assert any(item.area_id == "0.0.0.20" for item in decimal_update.areas)
    await service.delete_area("v2", "0.0.0.20")
    with pytest.raises(VyosPathNotFound):
        await driver.get_config(["protocols", "ospf", "area", "20"])

    await service.delete_area("v2", "0.0.0.10")
    with pytest.raises(OspfAreaNotFoundError):
        await service.delete_area("v2", "0.0.0.10")


async def test_area_in_use_and_interface_area_validation() -> None:
    service, _driver = await make_service()

    with pytest.raises(OspfAreaInUseError) as in_use:
        await service.delete_area("v2", "0.0.0.0")
    assert in_use.value.used_by == ["eth0"]

    with pytest.raises(OspfAreaReferenceError):
        await service.create_interface("v2", OspfInterfaceCreate(name="eth9", area_id="0.0.0.99"))

    with pytest.raises(OspfAreaReferenceError):
        await service.update_interface("v2", "eth0", OspfInterfaceUpdate(area_id="0.0.0.99"))


async def test_interface_crud_version_rules_and_unknown_fields() -> None:
    service, driver = await make_service()
    calls = _recording_driver(driver)

    created = await service.create_interface(
        "v3",
        OspfInterfaceCreate(
            name="eth2",
            area_id="0",
            network_type="point-to-point",
            cost=5,
            hello_interval=5,
            dead_interval=20,
            priority=0,
            bfd=True,
            mtu_ignore=True,
        ),
    )
    interface = next(item for item in created.interfaces if item.name == "eth2")
    assert interface.area_id == "0.0.0.0"
    assert interface.network_type == "point-to-point"
    assert len(calls) == 1

    with pytest.raises(OspfInterfaceExistsError):
        await service.create_interface("v3", OspfInterfaceCreate(name="eth2", area_id="0"))
    with pytest.raises(OspfValidationError):
        await service.create_interface(
            "v3",
            OspfInterfaceCreate(name="eth3", area_id="0", network_type="non-broadcast"),
        )

    await driver.apply(
        [ConfigOp("set", ["protocols", "ospf", "interface", "eth0", "bandwidth", "1000"])]
    )
    calls.clear()
    updated = await service.update_interface(
        "v2",
        "eth0",
        OspfInterfaceUpdate(
            area_id="0",
            network_type="broadcast",
            cost=30,
            hello_interval=10,
            dead_interval=40,
            priority=1,
            passive=True,
            bfd=False,
        ),
    )
    assert len(calls) == 1
    interface = next(item for item in updated.interfaces if item.name == "eth0")
    assert interface.network_type == "broadcast"
    assert interface.cost == 30
    assert interface.passive is True
    assert interface.bfd is False
    raw = await driver.get_config(["protocols", "ospf", "interface", "eth0"])
    assert raw["bandwidth"] == "1000"

    with pytest.raises(OspfInterfaceNotFoundError):
        await service.update_interface("v2", "eth9", OspfInterfaceUpdate(area_id="0"))
    with pytest.raises(OspfInterfaceNotFoundError):
        await service.delete_interface("v2", "eth9")

    deleted = await service.delete_interface("v3", "eth2")
    assert all(item.name != "eth2" for item in deleted.interfaces)


async def test_redistribute_crud_route_map_validation_and_version_rules() -> None:
    service, driver = await make_service()
    calls = _recording_driver(driver)

    created = await service.create_redistribute(
        "v2",
        OspfRedistributeCreate(source="static", metric=30, metric_type=1, route_map="BGP-IN"),
    )
    item = next(entry for entry in created.redistributions if entry.source == "static")
    assert (item.metric, item.metric_type, item.route_map) == (30, 1, "BGP-IN")
    assert len(calls) == 1

    with pytest.raises(OspfRedistributeExistsError):
        await service.create_redistribute("v2", OspfRedistributeCreate(source="static"))
    with pytest.raises(OspfRouteMapNotFoundError):
        await service.create_redistribute(
            "v2",
            OspfRedistributeCreate(source="kernel", route_map="MISSING-MAP"),
        )
    with pytest.raises(OspfValidationError):
        await service.create_redistribute("v2", OspfRedistributeCreate(source="ripng"))

    v3 = await service.create_redistribute("v3", OspfRedistributeCreate(source="ripng"))
    assert any(entry.source == "ripng" for entry in v3.redistributions)

    await driver.apply(
        [
            ConfigOp(
                "set",
                [
                    "protocols",
                    "ospf",
                    "redistribute",
                    "static",
                    "table",
                    "100",
                ],
            )
        ]
    )
    calls.clear()
    updated = await service.update_redistribute(
        "v2",
        "static",
        OspfRedistributeUpdate(metric=None, metric_type=2, route_map=None),
    )
    item = next(entry for entry in updated.redistributions if entry.source == "static")
    assert item.metric is None
    assert item.metric_type == 2
    assert item.route_map is None
    assert len(calls) == 1
    raw = await driver.get_config(["protocols", "ospf", "redistribute", "static"])
    assert raw.get("table") == {"100": {}}

    with pytest.raises(OspfRedistributeNotFoundError):
        await service.update_redistribute("v2", "kernel", OspfRedistributeUpdate())
    with pytest.raises(OspfRedistributeNotFoundError):
        await service.delete_redistribute("v2", "kernel")
    with pytest.raises(OspfRouteMapNotFoundError):
        await service.update_redistribute(
            "v2", "static", OspfRedistributeUpdate(route_map="MISSING-MAP")
        )

    deleted = await service.delete_redistribute("v2", "static")
    assert all(entry.source != "static" for entry in deleted.redistributions)


async def test_delete_process_is_idempotent() -> None:
    service, driver = await make_service()

    await service.delete_process("v2")
    assert (await service.get_config("v2")).configured is False
    await service.delete_process("v2")  # already absent, still 204 from the API

    # The other version is untouched.
    assert (await service.get_config("v3")).configured is True
    assert (await driver.get_config(["protocols", "ospfv3"]))["parameters"] == {
        "router-id": "10.255.0.1"
    }


async def test_status_for_both_versions() -> None:
    service, _driver = await make_service()

    v2 = await service.get_status("v2")
    assert v2.configured is True
    assert v2.version == "v2"
    assert v2.router_id == "10.255.0.1"
    assert v2.total_neighbors == 2
    assert v2.full_neighbors == 2
    assert v2.error is None
    assert [neighbor.state for neighbor in v2.neighbors] == [
        "Full/DR",
        "Full/Backup",
    ]

    v3 = await service.get_status("v3")
    assert v3.configured is True
    assert v3.total_neighbors == 2
    assert v3.full_neighbors == 1
    assert [neighbor.established for neighbor in v3.neighbors] == [True, False]


async def test_status_without_configuration_does_not_call_show() -> None:
    service, driver = await make_service()
    await service.delete_process("v2")

    calls: list[list[str]] = []
    original = driver.show

    async def wrapper(path):  # type: ignore[no-untyped-def]
        calls.append(list(path))
        return await original(path)

    driver.show = wrapper  # type: ignore[method-assign]
    status = await service.get_status("v2")
    assert status.configured is False
    assert status.neighbors == []
    assert status.error is None
    assert calls == []


async def test_status_daemon_not_running_is_reported() -> None:
    service, driver = await make_service()

    async def not_running(_path):  # type: ignore[no-untyped-def]
        return "OSPF is not running\n"

    driver.show = not_running  # type: ignore[method-assign]
    status = await service.get_status("v2")
    assert status.configured is True
    assert status.neighbors == []
    assert status.error is not None
    assert "not running" in status.error

    async def command_error(_path):  # type: ignore[no-untyped-def]
        raise VyosCommandError("OSPF is not running")

    driver.show = command_error  # type: ignore[method-assign]
    status = await service.get_status("v3")
    assert status.configured is True
    assert status.error == "OSPF is not running"


async def test_status_connection_errors_propagate() -> None:
    service, driver = await make_service()

    async def unreachable(_path):  # type: ignore[no-untyped-def]
        raise VyosConnectionError("connection refused")

    driver.show = unreachable  # type: ignore[method-assign]
    with pytest.raises(VyosConnectionError):
        await service.get_status("v2")
