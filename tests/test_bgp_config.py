"""Unit tests for VyOS BGP config parsing and write-op planning."""

from __future__ import annotations

import uuid
from typing import Any

from vyos_mgmt.schemas.bgp import (
    AddressFamilySettings,
    BgpGlobalUpdate,
    BgpNeighborCreate,
    BgpNeighborUpdate,
    BgpPeerGroupCreate,
    BgpPeerGroupUpdate,
    BgpTimers,
)
from vyos_mgmt.services.bgp_service import (
    BGP_ROOT,
    build_global_ops,
    build_neighbor_create_ops,
    build_peer_group_create_ops,
    neighbor_update_ops,
    parse_bgp_config,
    peer_group_update_ops,
)
from vyos_mgmt.services.vyos.base import ConfigOp

RAW_CONFIG: dict[str, Any] = {
    "system-as": "64512",
    "parameters": {"router-id": "10.255.0.1", "log-neighbor-changes": {}},
    "neighbor": {
        "192.0.2.1": {
            "remote-as": "65001",
            "description": "Transit A",
            "password": "hunter2",
            "timers": {"keepalive": "30", "holdtime": "90"},
            "local-as": {"as": "64512"},
            "address-family": {
                "ipv4-unicast": {
                    "route-reflector-client": {},
                    "soft-reconfiguration": {"inbound": {}},
                    "allowas-in": {"number": "3"},
                    "route-map": {"import": "BGP-IN", "export": "BGP-OUT"},
                }
            },
        },
        "2001:db8::1": {
            "remote-as": "65003",
            "address-family": {"ipv6-unicast": {}},
        },
    },
    "peer-group": {
        "transit": {
            "remote-as": "65001",
            "description": "Transit peers",
            "address-family": {"ipv4-unicast": {"next-hop-self": {}}},
        }
    },
    "address-family": {
        "ipv4-unicast": {"network": {"203.0.113.0/24": {}}},
        "ipv6-unicast": {"network": {"2001:db8:100::/48": {}}},
    },
}


def _paths(ops: list[ConfigOp], op: str = "set") -> list[list[str]]:
    return [item.path for item in ops if item.op == op]


def test_parse_full_config() -> None:
    router_id = uuid.uuid4()
    config = parse_bgp_config(router_id, "edge", RAW_CONFIG)

    assert config.router.id == router_id
    assert config.router.name == "edge"
    assert config.configured is True
    assert config.global_config.configured is True
    assert config.global_config.system_as == 64512
    assert config.global_config.router_id == "10.255.0.1"
    assert config.global_config.log_neighbor_changes is True

    first = config.neighbors[0]
    assert first.address == "192.0.2.1"
    assert first.remote_as == 65001
    assert first.description == "Transit A"
    assert first.password_configured is True
    assert first.timers == BgpTimers(keepalive=30, holdtime=90)
    assert first.local_as == 64512
    assert first.address_families["ipv4-unicast"].route_reflector_client is True
    assert first.address_families["ipv4-unicast"].soft_reconfiguration_inbound is True
    assert first.address_families["ipv4-unicast"].allowas_in == 3
    assert first.address_families["ipv4-unicast"].route_map_import == "BGP-IN"
    assert first.address_families["ipv4-unicast"].route_map_export == "BGP-OUT"

    assert config.neighbors[1].address_families["ipv6-unicast"].next_hop_self is False
    assert config.peer_groups[0].name == "transit"
    assert config.peer_groups[0].address_families["ipv4-unicast"].next_hop_self is True
    assert {(network.af, network.prefix) for network in config.networks} == {
        ("ipv4-unicast", "203.0.113.0/24"),
        ("ipv6-unicast", "2001:db8:100::/48"),
    }


def test_parse_empty_config() -> None:
    config = parse_bgp_config(uuid.uuid4(), "empty", {})
    assert config.configured is False
    assert config.global_config.configured is False
    assert config.neighbors == []
    assert config.peer_groups == []
    assert config.networks == []


def test_global_alias_serialisation() -> None:
    config = parse_bgp_config(uuid.uuid4(), "edge", RAW_CONFIG)
    data = config.model_dump(by_alias=True)
    assert "global" in data
    assert "global_config" not in data
    assert data["global"]["system_as"] == 64512


def test_build_global_ops_update_and_remove() -> None:
    update = BgpGlobalUpdate(system_as=65000, router_id="10.0.0.2", log_neighbor_changes=True)
    paths = _paths(build_global_ops(update, RAW_CONFIG))
    assert [*BGP_ROOT, "system-as", "65000"] in paths
    assert [*BGP_ROOT, "parameters", "router-id", "10.0.0.2"] in paths
    # log-neighbor-changes already exists, so no redundant set op.
    assert [*BGP_ROOT, "parameters", "log-neighbor-changes"] not in paths

    removal = BgpGlobalUpdate(system_as=64512, router_id=None, log_neighbor_changes=False)
    delete_paths = _paths(build_global_ops(removal, RAW_CONFIG), "delete")
    assert [*BGP_ROOT, "parameters", "router-id"] in delete_paths
    assert [*BGP_ROOT, "parameters", "log-neighbor-changes"] in delete_paths


def test_build_global_ops_adds_log_flag() -> None:
    update = BgpGlobalUpdate(system_as=64512, router_id="10.0.0.1", log_neighbor_changes=True)
    paths = _paths(build_global_ops(update, {}))
    assert [*BGP_ROOT, "parameters", "log-neighbor-changes"] in paths


def test_neighbor_create_ops_include_secret_and_af() -> None:
    payload = BgpNeighborCreate(
        address="203.0.113.9",
        remote_as=65100,
        description="New peer",
        password="s3cret",
        timers=BgpTimers(keepalive=30, holdtime=90),
        address_families={
            "ipv4-unicast": AddressFamilySettings(next_hop_self=True),
            "ipv6-unicast": AddressFamilySettings(),
        },
    )
    ops = build_neighbor_create_ops(payload)
    paths = _paths(ops)
    base = [*BGP_ROOT, "neighbor", "203.0.113.9"]
    assert [*base, "remote-as", "65100"] in paths
    assert [*base, "password", "s3cret"] in paths
    assert [*base, "timers", "keepalive", "30"] in paths
    assert [*base, "address-family", "ipv4-unicast"] in paths
    assert [*base, "address-family", "ipv6-unicast"] in paths
    assert [*base, "address-family", "ipv4-unicast", "next-hop-self"] in paths


def test_neighbor_update_ops_remove_optional_settings() -> None:
    existing = RAW_CONFIG["neighbor"]["192.0.2.1"]
    payload = BgpNeighborUpdate(
        description=None,
        peer_group="",
        update_source=None,
        password="",
        timers=None,
        ebgp_multihop=None,
        local_as=None,
    )
    delete_paths = _paths(neighbor_update_ops("192.0.2.1", payload, existing), "delete")
    base = [*BGP_ROOT, "neighbor", "192.0.2.1"]
    assert [*base, "description"] in delete_paths
    assert [*base, "password"] in delete_paths
    assert [*base, "timers"] in delete_paths
    assert [*base, "local-as"] in delete_paths
    # peer-group/update-source were not present, so nothing to delete.
    assert [*base, "peer-group"] not in delete_paths
    assert [*base, "update-source"] not in delete_paths


def test_neighbor_update_ops_are_partial() -> None:
    existing = RAW_CONFIG["neighbor"]["192.0.2.1"]
    payload = BgpNeighborUpdate(remote_as=65010, passive=True, shutdown=True)
    ops = neighbor_update_ops("192.0.2.1", payload, existing)
    paths = _paths(ops)
    base = [*BGP_ROOT, "neighbor", "192.0.2.1"]
    assert [*base, "remote-as", "65010"] in paths
    assert [*base, "passive"] in paths
    assert [*base, "shutdown"] in paths
    # Omitted fields are untouched.
    assert [*base, "description"] not in paths
    assert not _paths(ops, "delete")


def test_neighbor_update_ops_address_families_are_authoritative() -> None:
    existing = RAW_CONFIG["neighbor"]["192.0.2.1"]
    payload = BgpNeighborUpdate(
        address_families={"ipv6-unicast": AddressFamilySettings(next_hop_self=True)}
    )
    ops = neighbor_update_ops("192.0.2.1", payload, existing)
    paths = _paths(ops)
    delete_paths = _paths(ops, "delete")
    base = [*BGP_ROOT, "neighbor", "192.0.2.1", "address-family"]
    assert [*base, "ipv4-unicast"] in delete_paths
    assert [*base, "ipv6-unicast"] in paths
    assert [*base, "ipv6-unicast", "next-hop-self"] in paths


def test_peer_group_create_and_update_ops() -> None:
    create = BgpPeerGroupCreate(
        name="ix", remote_as=65200, description="IX peers", password="secret"
    )
    create_paths = _paths(build_peer_group_create_ops(create))
    base = [*BGP_ROOT, "peer-group", "ix"]
    assert [*base, "remote-as", "65200"] in create_paths
    assert [*base, "password", "secret"] in create_paths

    existing = RAW_CONFIG["peer-group"]["transit"]
    update = BgpPeerGroupUpdate(description=None, ebgp_multihop=None)
    update_ops = peer_group_update_ops("transit", update, existing)
    assert [*BGP_ROOT, "peer-group", "transit", "description"] in _paths(update_ops, "delete")


def test_parse_route_map_names_defensively() -> None:
    raw = {
        "neighbor": {
            "192.0.2.9": {
                "remote-as": "65009",
                "address-family": {
                    "ipv4-unicast": {
                        "route-map": {
                            "import": {"BGP-IN": {}},
                            "export": "not a valid name",
                        }
                    },
                    "ipv6-unicast": {"route-map": {"import": "BGP-IN"}},
                },
            }
        }
    }
    config = parse_bgp_config(uuid.uuid4(), "edge", raw)
    neighbor = config.neighbors[0]
    assert neighbor.address_families["ipv4-unicast"].route_map_import == "BGP-IN"
    assert neighbor.address_families["ipv4-unicast"].route_map_export is None
    assert neighbor.address_families["ipv6-unicast"].route_map_import == "BGP-IN"
    assert neighbor.address_families["ipv6-unicast"].route_map_export is None


def test_neighbor_update_ops_sync_route_map_fields() -> None:
    existing = {
        "remote-as": "65001",
        "address-family": {
            "ipv4-unicast": {"route-map": {"import": "OLD-IN", "export": "OLD-OUT"}}
        },
    }
    payload = BgpNeighborUpdate(
        address_families={
            "ipv4-unicast": AddressFamilySettings(
                route_map_import="NEW-IN",
                route_map_export=None,
            )
        }
    )
    ops = neighbor_update_ops("192.0.2.1", payload, existing)
    paths = _paths(ops)
    delete_paths = _paths(ops, "delete")
    af_base = [*BGP_ROOT, "neighbor", "192.0.2.1", "address-family", "ipv4-unicast"]
    assert [*af_base, "route-map", "import", "NEW-IN"] in paths
    assert [*af_base, "route-map", "export"] in delete_paths
    assert [*af_base, "route-map", "import"] not in delete_paths


def test_neighbor_update_ops_skip_unchanged_route_map_fields() -> None:
    existing = {
        "address-family": {"ipv4-unicast": {"route-map": {"import": "BGP-IN", "export": "BGP-OUT"}}}
    }
    payload = BgpNeighborUpdate(
        address_families={
            "ipv4-unicast": AddressFamilySettings(
                route_map_import="BGP-IN",
                route_map_export="BGP-OUT",
            )
        }
    )
    ops = neighbor_update_ops("192.0.2.1", payload, existing)
    af_base = [*BGP_ROOT, "neighbor", "192.0.2.1", "address-family", "ipv4-unicast"]
    route_map_paths = [path for path in _paths(ops) if "route-map" in path]
    route_map_deletes = [path for path in _paths(ops, "delete") if "route-map" in path]
    assert route_map_paths == []
    assert route_map_deletes == []
    assert af_base in _paths(ops)


def test_peer_group_create_ops_include_route_maps() -> None:
    payload = BgpPeerGroupCreate(
        name="rm-group",
        remote_as=65060,
        address_families={
            "ipv6-unicast": AddressFamilySettings(
                route_map_import="BGP-IN",
                route_map_export="BGP-OUT",
            )
        },
    )
    paths = _paths(build_peer_group_create_ops(payload))
    base = [*BGP_ROOT, "peer-group", "rm-group", "address-family", "ipv6-unicast"]
    assert [*base, "route-map", "import", "BGP-IN"] in paths
    assert [*base, "route-map", "export", "BGP-OUT"] in paths
