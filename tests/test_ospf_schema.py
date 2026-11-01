"""Validation tests for the OSPF schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from vyos_mgmt.schemas.ospf import (
    OspfAreaCreate,
    OspfAreaRead,
    OspfAreaUpdate,
    OspfConfigRead,
    OspfGlobal,
    OspfInterfaceCreate,
    OspfInterfaceUpdate,
    OspfNeighborStatus,
    OspfRedistributeCreate,
    OspfRedistributeUpdate,
    OspfRouterRef,
    OspfStatus,
    canonicalize_area_id,
    validate_network_type_for_version,
    validate_redistribute_source_for_version,
)


def test_area_id_canonicalisation() -> None:
    cases = {
        "0": "0.0.0.0",
        "1": "0.0.0.1",
        "65536": "0.1.0.0",
        "4294967295": "255.255.255.255",
        "0.0.0.0": "0.0.0.0",
        "0.0.0.1": "0.0.0.1",
        "255.255.255.255": "255.255.255.255",
        " 10.1.2.3 ": "10.1.2.3",
    }
    for raw, expected in cases.items():
        assert canonicalize_area_id(raw) == expected

    for bad in ("", "-1", "4294967296", "1.2.3", "1.2.3.4.5", "area-1", True):
        with pytest.raises(ValueError):
            canonicalize_area_id(bad)  # type: ignore[arg-type]


def test_area_schemas_validate_type_and_no_summary() -> None:
    created = OspfAreaCreate(area_id="1", area_type="stub", no_summary=True)
    assert created.area_id == "0.0.0.1"
    assert created.area_type == "stub"
    assert created.no_summary is True

    assert OspfAreaCreate(area_id="0").area_type == "normal"
    assert OspfAreaCreate(area_id="0", area_type="nssa").area_type == "nssa"

    for area_type in ("normal", "stub", "nssa"):
        assert OspfAreaUpdate(area_type=area_type).area_type == area_type  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        OspfAreaCreate(area_id="0", area_type="normal", no_summary=True)
    with pytest.raises(ValidationError):
        OspfAreaUpdate(area_type="normal", no_summary=True)
    with pytest.raises(ValidationError):
        OspfAreaUpdate(area_type="backbone")  # type: ignore[arg-type]

    read = OspfAreaRead(area_id="1", area_type="stub", no_summary=True, interface_count=2)
    assert read.area_id == "0.0.0.1"
    with pytest.raises(ValidationError):
        OspfAreaRead(area_id="0", area_type="normal", no_summary=True)


def test_global_validation_and_coherence() -> None:
    global_config = OspfGlobal(
        router_id="10.255.0.1",
        log_adjacency_changes="detail",
        auto_cost_reference_bandwidth=1000,
        default_information_originate=True,
        default_information_always=True,
        distance_global=110,
    )
    assert global_config.router_id == "10.255.0.1"
    assert global_config.log_adjacency_changes == "detail"

    assert OspfGlobal().log_adjacency_changes == "none"
    assert OspfGlobal(router_id=" 10.0.0.1 ").router_id == "10.0.0.1"

    with pytest.raises(ValidationError):
        OspfGlobal(default_information_always=True)
    with pytest.raises(ValidationError):
        OspfGlobal(router_id="not-an-ip")
    with pytest.raises(ValidationError):
        OspfGlobal(router_id="2001:db8::1")
    with pytest.raises(ValidationError):
        OspfGlobal(log_adjacency_changes="verbose")  # type: ignore[arg-type]
    for value in (0, 4_294_968):
        with pytest.raises(ValidationError):
            OspfGlobal(auto_cost_reference_bandwidth=value)
    for value in (0, 256):
        with pytest.raises(ValidationError):
            OspfGlobal(distance_global=value)


def test_interface_validation_and_ranges() -> None:
    created = OspfInterfaceCreate(
        name="eth0.100",
        area_id="1",
        network_type="point-to-point",
        cost=10,
        hello_interval=10,
        dead_interval=40,
        priority=0,
        passive=True,
        bfd=True,
        mtu_ignore=True,
        retransmit_interval=5,
        transmit_delay=1,
    )
    assert created.area_id == "0.0.0.1"
    assert created.name == "eth0.100"

    for name in ("eth0", "a", "A" * 64, "eth0.100", "bond0_1", "vti-1"):
        assert OspfInterfaceCreate(name=name, area_id="0").name == name
    for name in ("", "1eth0", "-eth0", "eth 0", "eth/0", "A" * 65):
        with pytest.raises(ValidationError):
            OspfInterfaceCreate(name=name, area_id="0")

    for field, bad in (
        ("cost", 0),
        ("cost", 65_536),
        ("hello_interval", 0),
        ("dead_interval", 65_536),
        ("priority", -1),
        ("priority", 256),
        ("retransmit_interval", 0),
        ("transmit_delay", 65_536),
    ):
        with pytest.raises(ValidationError):
            OspfInterfaceCreate(name="eth0", area_id="0", **{field: bad})

    # The payload accepts the union of both versions; the service narrows it.
    assert (
        OspfInterfaceCreate(name="eth0", area_id="0", network_type="non-broadcast").network_type
        == "non-broadcast"
    )

    update = OspfInterfaceUpdate(area_id="2")
    assert update.area_id == "0.0.0.2"
    with pytest.raises(ValidationError):
        OspfInterfaceUpdate(area_id="not-an-area")


def test_version_specific_network_types_and_sources() -> None:
    for allowed in ("broadcast", "point-to-point"):
        assert validate_network_type_for_version(allowed, "v2") == allowed
        assert validate_network_type_for_version(allowed, "v3") == allowed
    for v2_only in ("non-broadcast", "point-to-multipoint"):
        assert validate_network_type_for_version(v2_only, "v2") == v2_only
        with pytest.raises(ValueError):
            validate_network_type_for_version(v2_only, "v3")

    assert validate_redistribute_source_for_version("rip", "v2") == "rip"
    with pytest.raises(ValueError):
        validate_redistribute_source_for_version("rip", "v3")
    assert validate_redistribute_source_for_version("ripng", "v3") == "ripng"
    with pytest.raises(ValueError):
        validate_redistribute_source_for_version("ripng", "v2")
    with pytest.raises(ValueError):
        validate_redistribute_source_for_version("ospf", "v2")

    for source in ("babel", "bgp", "connected", "isis", "kernel", "static"):
        assert validate_redistribute_source_for_version(source, "v2") == source
        assert validate_redistribute_source_for_version(source, "v3") == source


def test_redistribute_validation() -> None:
    created = OspfRedistributeCreate(
        source="connected", metric=20, metric_type=2, route_map="OSPF-OUT"
    )
    assert created.source == "connected"
    assert created.metric == 20
    assert created.metric_type == 2

    assert OspfRedistributeCreate(source="CONNECTED").source == "connected"
    assert OspfRedistributeCreate(source="connected", metric=16_777_214).metric == 16_777_214

    for metric in (0, 16_777_215):
        with pytest.raises(ValidationError):
            OspfRedistributeCreate(source="connected", metric=metric)
    for metric_type in (0, 3):
        with pytest.raises(ValidationError):
            OspfRedistributeCreate(source="connected", metric_type=metric_type)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        OspfRedistributeCreate(source="ospf")  # type: ignore[arg-type]
    for name in ("-bad", "bad name", "A" * 65):
        with pytest.raises(ValidationError):
            OspfRedistributeCreate(source="connected", route_map=name)

    update = OspfRedistributeUpdate(metric=30, metric_type=1, route_map="OSPF-OUT")
    assert update.metric == 30
    assert OspfRedistributeUpdate().metric is None


def test_config_read_uses_global_alias_and_status_defaults() -> None:
    config = OspfConfigRead(
        router=OspfRouterRef(id="00000000-0000-0000-0000-000000000001", name="edge"),
        version="v2",
        configured=True,
        global_config=OspfGlobal(router_id="10.0.0.1"),
        supported_network_types=["broadcast"],
        supported_redistribute_sources=["connected"],
    )
    body = config.model_dump(by_alias=True)
    assert "global" in body
    assert "global_config" not in body
    assert body["global"]["router_id"] == "10.0.0.1"
    assert body["areas"] == []

    status = OspfStatus(configured=False, version="v3")
    assert status.neighbors == []
    assert status.total_neighbors == 0
    assert status.error is None
    assert status.collected_at.tzinfo is not None

    neighbor = OspfNeighborStatus(
        neighbor_id="10.0.0.2", priority=1, state="Full/DR", established=True
    )
    assert neighbor.established is True
