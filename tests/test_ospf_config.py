"""Unit tests for OSPF config parsing and write-op planning."""

from __future__ import annotations

import uuid
from typing import Any

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
    OSPF_ROOTS,
    build_area_create_ops,
    build_area_update_ops,
    build_global_update_ops,
    build_interface_create_ops,
    build_interface_update_ops,
    build_redistribute_create_ops,
    build_redistribute_update_ops,
    parse_global,
    parse_interface,
    parse_ospf_config,
    parse_ospf_neighbors,
    parse_redistribution,
)
from vyos_mgmt.services.vyos.base import ConfigOp

RAW_V2: dict[str, Any] = {
    "parameters": {"router-id": "10.255.0.1"},
    "log-adjacency-changes": {"detail": {}},
    "auto-cost": {"reference-bandwidth": "1000"},
    "default-information": {"originate": {}},
    "distance": {"global": "110"},
    "area": {
        "1": {"area-type": {"stub": {"no-summary": {}, "default-cost": "20"}}},
        "0": {},
        "10": {"area-type": {"nssa": {}}},
        "not-an-area": {},
    },
    "interface": {
        "eth1": {
            "area": "1",
            "network": "broadcast",
            "cost": "20",
            "priority": "1",
            "passive": {},
        },
        "eth0": {
            "area": "0",
            "network": "point-to-point",
            "cost": "10",
            "hello-interval": "10",
            "dead-interval": "40",
            "bfd": {},
            "mtu-ignore": {},
        },
        "eth2": {"area": "invalid", "network": "bogus", "cost": "0"},
    },
    "redistribute": {
        "connected": {"metric": "20", "metric-type": "2", "route-map": "OSPF-OUT"},
        "static": {"metric": "99999999", "metric-type": "5", "route-map": "bad name"},
    },
}

RAW_V3: dict[str, Any] = {
    "parameters": {"router-id": "10.255.0.1"},
    "log-adjacency-changes": {},
    "auto-cost": {"reference-bandwidth": "1000"},
    "default-information": {"originate": {"always": {}}},
    "area": {
        "0": {},
        "2": {"area-type": {"nssa": {"no-summary": {}}}},
    },
    "interface": {
        "eth0": {
            "area": "0",
            "network": "point-to-point",
            "cost": "10",
            "bfd": {},
            "mtu-ignore": {},
        }
    },
    "redistribute": {
        "connected": {"metric-type": "2", "route-map": "OSPF-OUT"},
        "ripng": {},
    },
}

NEIGHBORS_V2 = """
Neighbor ID Pri State Dead Time Address Interface RXmtL RqstL DBsmL
10.0.0.2 1 Full/DR 38.365s 10.0.0.2 eth0 0 0 0
10.0.0.3 1 2-Way/DROther 39.102s 10.0.0.3 eth1 0 0 0
"""

NEIGHBORS_V3 = """
Neighbor ID Pri State Dead Time Address Interface RXmtL RqstL DBsmL
10.0.0.2 1 Full/Backup 00:00:38 fe80::1 eth0 0 0 0
10.0.0.4 0 Down 00:00:10 fe80::4 eth1 0 0 0
"""


def _paths(ops: list[ConfigOp]) -> list[tuple[str, list[str]]]:
    return [(op.op, op.path) for op in ops]


def test_parse_v2_configuration() -> None:
    router_id = uuid.uuid4()
    config = parse_ospf_config(router_id, "edge", "v2", RAW_V2)

    assert config.router.id == router_id
    assert config.router.name == "edge"
    assert config.version == "v2"
    assert config.configured is True
    assert config.global_config.router_id == "10.255.0.1"
    assert config.global_config.log_adjacency_changes == "detail"
    assert config.global_config.auto_cost_reference_bandwidth == 1000
    assert config.global_config.default_information_originate is True
    assert config.global_config.default_information_always is False
    assert config.global_config.distance_global == 110

    assert [area.area_id for area in config.areas] == ["0.0.0.0", "0.0.0.1", "0.0.0.10"]
    assert config.areas[1].area_type == "stub"
    assert config.areas[1].no_summary is True
    assert config.areas[1].interface_count == 1
    assert config.areas[2].area_type == "nssa"
    assert config.areas[0].interface_count == 1

    assert [interface.name for interface in config.interfaces] == ["eth0", "eth1", "eth2"]
    eth0 = config.interfaces[0]
    assert eth0.area_id == "0.0.0.0"
    assert eth0.network_type == "point-to-point"
    assert (eth0.cost, eth0.hello_interval, eth0.dead_interval) == (10, 10, 40)
    assert eth0.bfd is True
    assert eth0.mtu_ignore is True
    assert eth0.passive is False
    assert eth0.retransmit_interval is None

    eth1 = config.interfaces[1]
    assert eth1.area_id == "0.0.0.1"
    assert eth1.passive is True
    assert eth1.bfd is False

    eth2 = config.interfaces[2]
    assert eth2.area_id is None
    assert eth2.network_type is None
    assert eth2.cost is None

    assert [item.source for item in config.redistributions] == ["connected", "static"]
    connected = config.redistributions[0]
    assert (connected.metric, connected.metric_type, connected.route_map) == (
        20,
        2,
        "OSPF-OUT",
    )
    static = config.redistributions[1]
    assert static.metric is None
    assert static.metric_type is None
    assert static.route_map is None

    assert config.supported_network_types == [
        "broadcast",
        "non-broadcast",
        "point-to-multipoint",
        "point-to-point",
    ]
    assert config.supported_redistribute_sources == [
        "babel",
        "bgp",
        "connected",
        "isis",
        "kernel",
        "rip",
        "static",
    ]


def test_parse_v3_configuration_and_empty_config() -> None:
    config = parse_ospf_config(uuid.uuid4(), "edge", "v3", RAW_V3)
    assert config.configured is True
    assert config.global_config.log_adjacency_changes == "normal"
    assert config.global_config.default_information_always is True
    assert [area.area_id for area in config.areas] == ["0.0.0.0", "0.0.0.2"]
    assert config.areas[1].area_type == "nssa"
    assert [item.source for item in config.redistributions] == ["connected", "ripng"]
    assert config.supported_network_types == ["broadcast", "point-to-point"]
    assert "ripng" in config.supported_redistribute_sources

    empty = parse_ospf_config(uuid.uuid4(), "edge", "v2", {})
    assert empty.configured is False
    assert empty.areas == []
    assert empty.interfaces == []
    assert empty.redistributions == []
    assert empty.global_config.log_adjacency_changes == "none"


def test_parse_global_tolerates_missing_and_invalid_values() -> None:
    assert parse_global({}).model_dump() == OspfGlobal().model_dump()
    assert parse_global({"log-adjacency-changes": {}}).log_adjacency_changes == "normal"
    assert parse_global({"log-adjacency-changes": "detail"}).log_adjacency_changes == "detail"
    assert parse_global({"log-adjacency-changes": {"detail": {}}}).log_adjacency_changes == "detail"

    malformed = parse_global(
        {
            "parameters": {"router-id": "not-an-ip"},
            "auto-cost": {"reference-bandwidth": "0"},
            "default-information": {"originate": {}},
            "distance": {"global": "300"},
        }
    )
    assert malformed.router_id is None
    assert malformed.auto_cost_reference_bandwidth is None
    assert malformed.distance_global is None
    assert malformed.default_information_always is False

    # A device-side "always" without "originate" is not representable; the
    # parser normalises it instead of failing the whole GET.
    always_only = parse_global({"default-information": {"originate": {"always": {}}}})
    assert always_only.default_information_originate is True
    assert always_only.default_information_always is True
    assert parse_global({"default-information": {"always": {}}}).default_information_always is False


def test_parse_interface_and_redistribution_edge_cases() -> None:
    parsed = parse_interface(
        "eth0",
        {"area": "1", "network": "broadcast", "passive": {"disable": {}}},
    )
    assert parsed is not None
    assert parsed.area_id == "0.0.0.1"
    assert parsed.passive is False
    assert parsed.bfd is False

    parsed = parse_interface("eth0", {"area": "bad", "network": "weird", "cost": "0"})
    assert parsed is not None
    assert parsed.area_id is None
    assert parsed.network_type is None
    assert parsed.cost is None

    redistribution = parse_redistribution(
        "connected", {"metric": "0", "metric-type": "9", "route-map": "bad name"}
    )
    assert redistribution.metric is None
    assert redistribution.metric_type is None
    assert redistribution.route_map is None


def test_parse_neighbor_output() -> None:
    v2 = parse_ospf_neighbors(NEIGHBORS_V2)
    assert [neighbor.neighbor_id for neighbor in v2] == ["10.0.0.2", "10.0.0.3"]
    assert v2[0].priority == 1
    assert v2[0].state == "Full/DR"
    assert v2[0].dead_time == "38.365s"
    assert v2[0].address == "10.0.0.2"
    assert v2[0].interface == "eth0"
    assert v2[0].established is True
    assert v2[1].state == "2-Way/DROther"
    assert v2[1].established is False

    v3 = parse_ospf_neighbors(NEIGHBORS_V3)
    assert [neighbor.state for neighbor in v3] == ["Full/Backup", "Down"]
    assert [neighbor.established for neighbor in v3] == [True, False]
    assert v3[0].address == "fe80::1"

    assert parse_ospf_neighbors("") == []
    assert parse_ospf_neighbors("OSPF is not running\n") == []
    assert parse_ospf_neighbors("garbage line\n") == []


def test_global_update_ops_cover_every_managed_field() -> None:
    existing = {
        "parameters": {"router-id": "1.1.1.1"},
        "log-adjacency-changes": {"detail": {}},
        "auto-cost": {"reference-bandwidth": "100"},
        "default-information": {"originate": {"always": {}}},
        "distance": {"global": "110"},
    }
    payload = OspfGlobal(
        router_id="2.2.2.2",
        log_adjacency_changes="normal",
        auto_cost_reference_bandwidth=1000,
        default_information_originate=True,
        default_information_always=False,
        distance_global=None,
    )
    ops = build_global_update_ops("v2", payload, existing)
    assert _paths(ops) == [
        ("set", [*OSPF_ROOTS["v2"], "parameters", "router-id", "2.2.2.2"]),
        ("delete", [*OSPF_ROOTS["v2"], "log-adjacency-changes", "detail"]),
        ("set", [*OSPF_ROOTS["v2"], "auto-cost", "reference-bandwidth", "1000"]),
        ("delete", [*OSPF_ROOTS["v2"], "default-information", "originate", "always"]),
        ("delete", [*OSPF_ROOTS["v2"], "distance", "global"]),
    ]

    clear = OspfGlobal(
        log_adjacency_changes="none",
        default_information_originate=False,
    )
    clear_ops = build_global_update_ops("v3", clear, existing)
    assert ("delete", [*OSPF_ROOTS["v3"], "log-adjacency-changes"]) in _paths(clear_ops)
    assert (
        "delete",
        [*OSPF_ROOTS["v3"], "default-information", "originate"],
    ) in _paths(clear_ops)
    assert ("set", [*OSPF_ROOTS["v3"], "default-information", "originate"]) not in _paths(clear_ops)

    # No change produces no ops (the service then skips the atomic batch).
    unchanged = OspfGlobal(
        router_id="1.1.1.1",
        log_adjacency_changes="detail",
        auto_cost_reference_bandwidth=100,
        default_information_originate=True,
        default_information_always=True,
        distance_global=110,
    )
    assert build_global_update_ops("v2", unchanged, existing) == []


def test_area_create_and_update_ops() -> None:
    normal = build_area_create_ops("v2", OspfAreaCreate(area_id="1"))
    assert _paths(normal) == [
        ("set", [*OSPF_ROOTS["v2"], "area", "0.0.0.1"]),
    ]

    stub = build_area_create_ops(
        "v3", OspfAreaCreate(area_id="2", area_type="stub", no_summary=True)
    )
    assert _paths(stub) == [
        ("set", [*OSPF_ROOTS["v3"], "area", "0.0.0.2"]),
        ("set", [*OSPF_ROOTS["v3"], "area", "0.0.0.2", "area-type", "stub"]),
        (
            "set",
            [*OSPF_ROOTS["v3"], "area", "0.0.0.2", "area-type", "stub", "no-summary"],
        ),
    ]

    existing = {"area-type": {"stub": {"no-summary": {}, "default-cost": "20"}}}
    changing_summary = build_area_update_ops(
        "v2", "1", OspfAreaUpdate(area_type="stub", no_summary=False), existing
    )
    assert _paths(changing_summary) == [
        ("delete", [*OSPF_ROOTS["v2"], "area", "1", "area-type", "stub", "no-summary"]),
    ]

    to_normal = build_area_update_ops("v2", "1", OspfAreaUpdate(area_type="normal"), existing)
    assert _paths(to_normal) == [
        ("delete", [*OSPF_ROOTS["v2"], "area", "1", "area-type"]),
    ]

    to_nssa = build_area_update_ops(
        "v2", "1", OspfAreaUpdate(area_type="nssa", no_summary=True), existing
    )
    assert _paths(to_nssa) == [
        ("delete", [*OSPF_ROOTS["v2"], "area", "1", "area-type"]),
        ("set", [*OSPF_ROOTS["v2"], "area", "1", "area-type", "nssa"]),
        ("set", [*OSPF_ROOTS["v2"], "area", "1", "area-type", "nssa", "no-summary"]),
    ]


def test_interface_create_and_update_preserve_unknown_fields() -> None:
    payload = OspfInterfaceCreate(
        name="eth0",
        area_id="1",
        network_type="point-to-point",
        cost=10,
        priority=0,
        passive=True,
        bfd=True,
        mtu_ignore=True,
        transmit_delay=1,
    )
    created = build_interface_create_ops("v2", payload)
    base = [*OSPF_ROOTS["v2"], "interface", "eth0"]
    assert _paths(created) == [
        ("set", base),
        ("set", [*base, "area", "0.0.0.1"]),
        ("set", [*base, "network", "point-to-point"]),
        ("set", [*base, "cost", "10"]),
        ("set", [*base, "priority", "0"]),
        ("set", [*base, "passive"]),
        ("set", [*base, "bfd"]),
        ("set", [*base, "mtu-ignore"]),
        ("set", [*base, "transmit-delay", "1"]),
    ]

    existing = {
        "area": "0.0.0.1",
        "network": "broadcast",
        "cost": "10",
        "bandwidth": "1000",
        "bfd": {},
    }
    update = OspfInterfaceUpdate(
        area_id="1",
        network_type=None,
        cost=20,
        passive=True,
        bfd=False,
    )
    updated = build_interface_update_ops("v2", "eth0", update, existing)
    assert _paths(updated) == [
        ("delete", [*base, "network"]),
        ("set", [*base, "cost", "20"]),
        ("set", [*base, "passive"]),
        ("delete", [*base, "bfd"]),
    ]
    # ``bandwidth`` is a valid VyOS interface directive the API does not manage.
    assert all("bandwidth" not in path for _op, path in _paths(updated))

    # OSPFv2 models passive as a node with an optional disable child; enabling it
    # must clear an explicit disable.
    disabled = {"area": "0.0.0.1", "passive": {"disable": {}}}
    reenabled = build_interface_update_ops(
        "v2", "eth0", OspfInterfaceUpdate(area_id="1", passive=True), disabled
    )
    assert _paths(reenabled) == [
        ("delete", [*base, "passive"]),
        ("set", [*base, "passive"]),
    ]


def test_redistribute_create_and_update_ops() -> None:
    created = build_redistribute_create_ops(
        "v2",
        OspfRedistributeCreate(source="connected", metric=20, metric_type=2, route_map="OSPF-OUT"),
    )
    base = [*OSPF_ROOTS["v2"], "redistribute", "connected"]
    assert _paths(created) == [
        ("set", base),
        ("set", [*base, "metric", "20"]),
        ("set", [*base, "metric-type", "2"]),
        ("set", [*base, "route-map", "OSPF-OUT"]),
    ]

    existing = {
        "metric": "10",
        "metric-type": "2",
        "route-map": "OLD-MAP",
        "table": "100",
    }
    updated = build_redistribute_update_ops(
        "v3",
        "connected",
        OspfRedistributeUpdate(metric=None, metric_type=1, route_map=None),
        existing,
    )
    v3_base = [*OSPF_ROOTS["v3"], "redistribute", "connected"]
    assert _paths(updated) == [
        ("delete", [*v3_base, "metric"]),
        ("set", [*v3_base, "metric-type", "1"]),
        ("delete", [*v3_base, "route-map"]),
    ]
    assert all("table" not in path for _op, path in _paths(updated))
