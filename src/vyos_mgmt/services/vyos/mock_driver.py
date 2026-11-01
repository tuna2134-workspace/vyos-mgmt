"""In-memory VyOS emulator.

This driver makes the console fully usable (and testable) without a VyOS
appliance.  It implements the same write semantics as the HTTPS API: a batch of
set/delete operations is applied atomically to a nested configuration tree.
"""

from __future__ import annotations

import copy
import threading
import time
import uuid
from collections.abc import Sequence
from typing import Any

from vyos_mgmt.db.models import RouterDriver
from vyos_mgmt.schemas.bgp import BgpPeerStatus, BgpStatus
from vyos_mgmt.schemas.router import SystemInfo
from vyos_mgmt.services.vyos.base import (
    ConfigOp,
    DeviceTarget,
    VyosCommandError,
    VyosPathNotFound,
)

# Configuration directives whose last path component is a value, not a node.
_LEAF_KEYS = {
    "system-as",
    "remote-as",
    "router-id",
    "description",
    "peer-group",
    "update-source",
    "password",
    "ebgp-multihop",
    "keepalive",
    "holdtime",
    "local-as",
    "number",
    "import",
    "export",
    # Route-map rule controls and match/set leaves.
    "action",
    "prefix",
    "ge",
    "le",
    "prefix-list",
    "community-list",
    "large-community-list",
    "as-path",
    "extcommunity",
    "metric",
    "local-preference",
    "origin",
    "tag",
    "protocol",
    "rpki",
    "interface",
    "nexthop",
    "address",
    "weight",
    "metric-type",
    "ip-next-hop",
    "originator-id",
    "delete",
    "call",
    "continue",
    "goto",
    # OSPF/OSPFv3 global, interface and redistribution leaves.
    "area",
    "network",
    "cost",
    "bandwidth",
    "hello-interval",
    "dead-interval",
    "priority",
    "retransmit-interval",
    "transmit-delay",
    "reference-bandwidth",
    "global",
    "route-map",
    # WireGuard interface/peer leaves.  ``address`` is a multi-value leaf on
    # the interface but a scalar endpoint on a peer; the setter disambiguates
    # by parent context.
    "private-key",
    "public-key",
    "preshared-key",
    "port",
    "mtu",
    "persistent-keepalive",
    "host-name",
}

# Multi-value leaves: VyOS stores each value as a child node keyed by the value
# (for example ``set community add {"64500:100": {}}``).
_MULTI_VALUE_KEYS = {"add", "replace", "prepend"}

# WireGuard multi-value leaves that are not wrapped in add/replace/prepend.
_WIREGUARD_MULTI_VALUE_KEYS = {"allowed-ips"}

# Containers whose own name collides with a leaf key.  ``prefix-list`` is a
# route-map match leaf, but ``policy prefix-list <name>`` is a container; the
# same applies to ``policy route-map`` (a route-map leaf under OSPF
# redistribution), OSPF area IDs (a leaf under an interface, a tag node under
# the protocol root) and BGP address-family networks (a leaf under an OSPF
# interface, a tag node under BGP).
_NODE_PARENT_PATHS = {
    ("policy", "prefix-list"),
    ("policy", "prefix-list6"),
    ("policy", "route-map"),
    ("protocols", "ospf", "area"),
    ("protocols", "ospfv3", "area"),
    ("protocols", "ospf", "interface"),
    ("protocols", "ospfv3", "interface"),
    ("protocols", "bgp", "address-family", "ipv4-unicast", "network"),
    ("protocols", "bgp", "address-family", "ipv6-unicast", "network"),
}


def _seed_route_maps() -> dict[str, Any]:
    """Realistic policy objects so the route-map UI is useful out of the box."""

    return {
        "BGP-IN": {
            "description": "Inbound filtering for transit",
            "rule": {
                "10": {
                    "action": "permit",
                    "description": "Allow transit prefixes",
                    "match": {
                        "ip": {"address": {"prefix-list": "TRANSIT-IN"}},
                        "community": {"community-list": "CUSTOMER-COMM"},
                        "origin": "igp",
                        "protocol": "bgp",
                        "rpki": "valid",
                    },
                    "set": {
                        "local-preference": "200",
                        "metric": "+50",
                        "community": {"add": {"64512:100": {}}},
                    },
                    "on-match": {"next": {}},
                },
                "20": {
                    "action": "deny",
                    "description": "Drop transit bogons",
                    "match": {"ip": {"address": {"prefix-list": "TRANSIT-BOGONS"}}},
                },
            },
        },
        "BGP-OUT": {
            "description": "Outbound announcements",
            "rule": {
                "10": {
                    "action": "permit",
                    "description": "Prepend AS path and tag communities",
                    "match": {"as-path": "CUSTOMER-AS"},
                    "set": {
                        "as-path": {"prepend": {"64512": {}}},
                        "community": {
                            "add": {"64512:200": {}, "no-export": {}},
                        },
                    },
                }
            },
        },
        "LOCAL-PREF": {
            "description": "Raise local preference for customer routes",
            "rule": {
                "10": {
                    "action": "permit",
                    "description": "Customers get preferred",
                    "match": {
                        "community": {
                            "community-list": "CUSTOMER-COMM",
                            "exact-match": {},
                        }
                    },
                    "set": {"local-preference": "250"},
                    "call": "BGP-OUT",
                }
            },
        },
        "OSPF-OUT": {
            "description": "Redistributed connected routes",
            "rule": {
                "10": {
                    "action": "permit",
                    "description": "Tag redistributed connected routes",
                    "set": {"metric": "+10", "tag": "100"},
                }
            },
        },
    }


def _seed_prefix_lists() -> dict[str, Any]:
    """IPv4 policy prefix-lists referenced by the seeded route maps."""

    return {
        "TRANSIT-IN": {
            "description": "Transit customer prefixes",
            "rule": {
                "10": {
                    "action": "permit",
                    "prefix": "203.0.113.0/24",
                    "ge": "24",
                    "le": "32",
                    "description": "Customer /24s",
                }
            },
        },
        "TRANSIT-BOGONS": {
            "description": "Drop private and reserved ranges",
            "rule": {
                "10": {"action": "deny", "prefix": "10.0.0.0/8", "le": "32"},
                "20": {"action": "deny", "prefix": "172.16.0.0/12", "le": "32"},
                "30": {"action": "deny", "prefix": "192.168.0.0/16", "le": "32"},
                "40": {
                    "action": "permit",
                    "prefix": "0.0.0.0/0",
                    "le": "32",
                    "description": "Catch-all permit",
                },
            },
        },
    }


def _seed_prefix_lists6() -> dict[str, Any]:
    """IPv6 policy prefix-lists (``policy prefix-list6``)."""

    return {
        "TRANSIT-V6": {
            "description": "Transit IPv6 customer prefixes",
            "rule": {
                "10": {
                    "action": "permit",
                    "prefix": "2001:db8:100::/48",
                    "ge": "48",
                    "le": "64",
                    "description": "Customer /48s and /64s",
                },
                "20": {
                    "action": "deny",
                    "prefix": "::/0",
                    "le": "128",
                    "description": "Catch-all deny",
                },
            },
        }
    }


def _seed_ospfv2() -> dict[str, Any]:
    """Realistic OSPFv2 configuration with normal and stub areas."""

    return {
        "parameters": {"router-id": "10.255.0.1"},
        "log-adjacency-changes": {"detail": {}},
        "auto-cost": {"reference-bandwidth": "1000"},
        "default-information": {"originate": {}},
        "distance": {"global": "110"},
        "area": {
            "0.0.0.0": {},
            "0.0.0.1": {"area-type": {"stub": {"no-summary": {}}}},
        },
        "interface": {
            "eth0": {
                "area": "0.0.0.0",
                "network": "point-to-point",
                "cost": "10",
                "hello-interval": "10",
                "dead-interval": "40",
                "priority": "1",
                "bfd": {},
            },
            "eth1": {
                "area": "0.0.0.1",
                "network": "broadcast",
                "cost": "20",
                "priority": "1",
                "passive": {},
            },
        },
        "redistribute": {
            "connected": {
                "metric": "20",
                "metric-type": "2",
                "route-map": "OSPF-OUT",
            }
        },
    }


def _seed_ospfv3() -> dict[str, Any]:
    """Realistic OSPFv3 configuration with normal and NSSA areas."""

    return {
        "parameters": {"router-id": "10.255.0.1"},
        "log-adjacency-changes": {},
        "auto-cost": {"reference-bandwidth": "1000"},
        "default-information": {"originate": {"always": {}}},
        "distance": {"global": "110"},
        "area": {
            "0.0.0.0": {},
            "0.0.0.2": {"area-type": {"nssa": {"no-summary": {}}}},
        },
        "interface": {
            "eth0": {
                "area": "0.0.0.0",
                "network": "point-to-point",
                "cost": "10",
                "hello-interval": "10",
                "dead-interval": "40",
                "priority": "1",
                "bfd": {},
                "mtu-ignore": {},
            },
            "eth1": {
                "area": "0.0.0.2",
                "network": "broadcast",
                "cost": "20",
                "priority": "1",
                "passive": {},
            },
        },
        "redistribute": {"connected": {"metric-type": "2", "route-map": "OSPF-OUT"}},
    }


# Valid Base64-encoded 32-byte WireGuard keys used by the seeded topology.
WIREGUARD_SEED_PRIVATE_KEY = "sDYSuvqwXrjo9TJcQmWhXaMVKXDniFFcQATT9Ydppm8="
WIREGUARD_SEED_PEER_PUBLIC_KEY = "TporhvqgxwnbnFfVD4vBS3W75vYjINO2UI4LF9iROmQ="
WIREGUARD_SEED_ROAD_WARRIOR_PUBLIC_KEY = "Zf1Iibwmo2eaTQx6EY7US75HKO5RZ2WaklsTQMi6fl4="
WIREGUARD_SEED_PRESHARED_KEY = "J+qO2PNBJ+EpYO4FHcmE1XOBRBHJjQjV4qy+s7R80fo="


def _seed_wireguard() -> dict[str, Any]:
    """A realistic site-to-site tunnel plus one road-warrior peer."""

    return {
        "wg0": {
            "address": {
                "10.100.0.1/24": {},
                "2001:db8:100::1/64": {},
            },
            "description": "Tokyo branch tunnel",
            "port": "51820",
            "mtu": "1420",
            "private-key": WIREGUARD_SEED_PRIVATE_KEY,
            "peer": {
                "branch-office": {
                    "description": "Branch router",
                    "public-key": WIREGUARD_SEED_PEER_PUBLIC_KEY,
                    "preshared-key": WIREGUARD_SEED_PRESHARED_KEY,
                    "allowed-ips": {
                        "192.168.50.0/24": {},
                        "192.168.60.0/24": {},
                    },
                    "address": "198.51.100.10",
                    "port": "51820",
                    "persistent-keepalive": "25",
                },
                "road-warrior": {
                    "description": "Remote worker",
                    "public-key": WIREGUARD_SEED_ROAD_WARRIOR_PUBLIC_KEY,
                    "allowed-ips": {"10.200.0.5/32": {}},
                },
            },
        }
    }


def _seed_static_routes() -> dict[str, Any]:
    """Realistic IPv4/IPv6 static routes for the demo device.

    Covers the API shapes that matter: a default via a gateway, an
    interface-only route, blackhole/reject routes with distance and tag, a
    multi-next-hop route (one disabled) and the IPv6 equivalents.
    """

    return {
        "route": {
            "0.0.0.0/0": {
                "description": "Default via transit",
                "next-hop": {"192.0.2.254": {}},
            },
            "10.0.0.0/8": {
                "description": "Lab block (discard)",
                "blackhole": {"distance": "255", "tag": "100"},
            },
            "172.16.0.0/12": {
                "description": "RFC1918 lab range",
                "reject": {"distance": "250", "tag": "200"},
            },
            "192.168.50.0/24": {
                "description": "Branch LAN via eth1",
                "interface": {"eth1": {}},
            },
            "203.0.113.0/24": {
                "description": "Customer block via transit",
                "next-hop": {
                    "192.0.2.1": {"interface": "eth0", "distance": "10"},
                    "198.51.100.1": {"disable": {}},
                },
            },
        },
        "route6": {
            "::/0": {
                "description": "IPv6 default via transit",
                "next-hop": {"2001:db8:ffff::1": {}},
            },
            "2001:db8:100::/64": {
                "description": "Branch LAN (IPv6)",
                "next-hop": {"2001:db8:100::1": {"interface": "eth0", "distance": "10"}},
            },
            "2001:db8:200::/48": {
                "description": "IPv6 lab discard",
                "reject": {"distance": "250", "tag": "300"},
            },
            "2001:db8:300::/48": {
                "description": "IPv6 interface route",
                "interface": {"eth1": {}},
            },
        },
    }


def _seed_config(hostname: str) -> dict[str, Any]:
    return {
        "system": {"host-name": hostname},
        "interfaces": {"wireguard": _seed_wireguard()},
        "policy": {
            "route-map": _seed_route_maps(),
            "prefix-list": _seed_prefix_lists(),
            "prefix-list6": _seed_prefix_lists6(),
        },
        "protocols": {
            "bgp": {
                "system-as": "64512",
                "parameters": {"router-id": "10.255.0.1", "log-neighbor-changes": {}},
                "neighbor": {
                    "192.0.2.1": {
                        "remote-as": "65001",
                        "description": "Transit A",
                        "ebgp-multihop": "2",
                        "address-family": {
                            "ipv4-unicast": {
                                "route-reflector-client": {},
                                "soft-reconfiguration": {"inbound": {}},
                                "route-map": {"import": "BGP-IN", "export": "BGP-OUT"},
                            }
                        },
                    },
                    "198.51.100.1": {
                        "remote-as": "65002",
                        "description": "IX peer (maintenance)",
                        "shutdown": {},
                        "address-family": {"ipv4-unicast": {}},
                    },
                    "2001:db8:ffff::1": {
                        "remote-as": "65003",
                        "description": "IPv6 transit",
                        "address-family": {"ipv6-unicast": {}},
                    },
                },
                "peer-group": {
                    "transit": {
                        "remote-as": "65001",
                        "description": "Transit peers",
                        "address-family": {"ipv4-unicast": {}},
                    }
                },
                "address-family": {
                    "ipv4-unicast": {"network": {"203.0.113.0/24": {}}},
                    "ipv6-unicast": {"network": {"2001:db8:100::/48": {}}},
                },
            },
            "ospf": _seed_ospfv2(),
            "ospfv3": _seed_ospfv3(),
            "static": _seed_static_routes(),
        },
    }


def _is_wireguard_interface_address(parent: list[str]) -> bool:
    """True for ``interfaces wireguard <wgN> address`` (multi-value context).

    A peer's ``address`` is a scalar endpoint, so the parent context matters.
    """

    return (
        len(parent) == 4
        and parent[0] == "interfaces"
        and parent[1] == "wireguard"
        and parent[3] == "address"
    )


def _is_static_route_path(parent: list[str]) -> bool:
    """True when a parent path is inside ``protocols static route[6]``."""

    return (
        len(parent) >= 3
        and parent[0] == "protocols"
        and parent[1] == "static"
        and parent[2] in {"route", "route6"}
    )


def _is_static_route_interface_tag(parent: list[str]) -> bool:
    """True for ``protocols static route[6] <prefix> interface``.

    ``interface`` under a route is a tag node (one per interface), while
    ``interface`` under a next hop is a leaf naming that next hop's interface.
    """

    return _is_static_route_path(parent) and len(parent) == 5 and parent[4] == "interface"


def _is_static_route_distance_leaf(parent: list[str]) -> bool:
    """True for the static-route ``distance`` leaf.

    ``distance`` is a leaf inside ``blackhole``/``reject``, a next hop and an
    interface tag node, but a tag node itself under OSPF (``distance global``),
    so it cannot simply join :data:`_LEAF_KEYS`.
    """

    return _is_static_route_path(parent) and len(parent) >= 5 and parent[-1] == "distance"


def _navigate(tree: dict[str, Any], path: Sequence[str]) -> Any:
    node: Any = tree
    for part in path:
        if not isinstance(node, dict) or part not in node:
            raise VyosPathNotFound(f"Configuration path not found: {' '.join(path)}")
        node = node[part]
    return node


class MockDriver:
    _trees: dict[uuid.UUID, dict[str, Any]] = {}
    _lock = threading.RLock()

    def __init__(self, target: DeviceTarget) -> None:
        self._target = target
        with self._lock:
            if target.id not in self._trees:
                hostname = target.name.lower().replace(" ", "-") or "mock-router"
                self._trees[target.id] = _seed_config(hostname)

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._trees.clear()

    async def get_config(self, path: Sequence[str]) -> Any:
        with self._lock:
            tree = self._trees[self._target.id]
            try:
                node = _navigate(tree, path)
            except VyosPathNotFound:
                raise
            return copy.deepcopy(node)

    async def show(self, path: Sequence[str]) -> str:
        with self._lock:
            tree = self._trees[self._target.id]
        if list(path) == ["version"]:
            return (
                "Version:      VyOS 1.5-rolling-202601010000 (mock)\n"
                "Built by:     mock@localhost\n"
                "System type:  x86_64\n"
                f"Uptime:       {self._uptime_string()}\n"
            )
        if list(path) == ["bgp", "summary"]:
            return self._render_summary(tree)
        if list(path) == ["ip", "ospf", "neighbor"]:
            return self._render_ospf_neighbors(tree, "v2")
        if list(path) == ["ipv6", "ospfv3", "neighbor"]:
            return self._render_ospf_neighbors(tree, "v3")
        command = list(path)
        if (
            len(command) == 4
            and command[:2] == ["interfaces", "wireguard"]
            and command[3] == "summary"
        ):
            return self._render_wireguard_summary(tree, command[2])
        raise VyosCommandError(f"Unsupported mock operational command: {' '.join(path)}")

    async def apply(self, ops: Sequence[ConfigOp]) -> None:
        with self._lock:
            tree = self._trees[self._target.id]
            working = copy.deepcopy(tree)
            for op in ops:
                if op.op == "set":
                    self._set_path(working, op.path)
                else:
                    self._delete_path(working, op.path)
            self._trees[self._target.id] = working

    def _set_path(self, tree: dict[str, Any], path: list[str]) -> None:
        if len(path) < 2:
            raise VyosCommandError("Invalid configuration path")
        *parent, leaf = path
        multi_value = bool(parent) and (
            parent[-1] in _MULTI_VALUE_KEYS
            or parent[-1] in _WIREGUARD_MULTI_VALUE_KEYS
            or _is_wireguard_interface_address(parent)
        )
        if multi_value:
            # Multi-value leaf: keep one child node per value.
            container_path = path[:-1]
            container = tree
            for part in container_path[:-1]:
                node = container.get(part)
                if not isinstance(node, dict):
                    node = {}
                    container[part] = node
                container = node
            values = container.get(container_path[-1])
            if not isinstance(values, dict):
                values = {}
                container[container_path[-1]] = values
            values[leaf] = {}
        elif parent and (
            (
                parent[-1] in _LEAF_KEYS
                and tuple(parent) not in _NODE_PARENT_PATHS
                and not _is_static_route_interface_tag(parent)
            )
            or _is_static_route_distance_leaf(parent)
        ):
            # A value node: the final token is the value to store.
            container_path = path[:-1]
            container = tree
            for part in container_path[:-1]:
                node = container.get(part)
                if not isinstance(node, dict):
                    node = {}
                    container[part] = node
                container = node
            container[container_path[-1]] = leaf
        else:
            container = tree
            for part in path:
                node = container.get(part)
                if not isinstance(node, dict):
                    node = {}
                    container[part] = node
                container = node

    def _delete_path(self, tree: dict[str, Any], path: list[str]) -> None:
        if not path:
            raise VyosCommandError("Invalid configuration path")
        *parents, key = path
        container = tree
        for part in parents:
            node = container.get(part)
            if not isinstance(node, dict):
                return
            container = node
        container.pop(key, None)

    def _bgp(self, tree: dict[str, Any]) -> dict[str, Any]:
        protocols = tree.get("protocols", {})
        bgp = protocols.get("bgp", {}) if isinstance(protocols, dict) else {}
        return bgp if isinstance(bgp, dict) else {}

    def _ospf(self, tree: dict[str, Any], version: str) -> dict[str, Any]:
        protocols = tree.get("protocols", {})
        key = "ospf" if version == "v2" else "ospfv3"
        ospf = protocols.get(key, {}) if isinstance(protocols, dict) else {}
        return ospf if isinstance(ospf, dict) else {}

    def _wireguard(self, tree: dict[str, Any]) -> dict[str, Any]:
        interfaces = tree.get("interfaces", {})
        wireguard = interfaces.get("wireguard", {}) if isinstance(interfaces, dict) else {}
        return wireguard if isinstance(wireguard, dict) else {}

    def _render_wireguard_summary(self, tree: dict[str, Any], name: str) -> str:
        """Render ``show interfaces wireguard <name> summary`` from the config.

        The interface and peer blocks are derived from the configuration tree,
        so the mock remains useful after CRUD operations.  A disabled interface
        is reported as a command failure, which the service surfaces as a
        ``configured but not running`` status.
        """

        from vyos_mgmt.services.wireguard_service import WireGuardKeyError, derive_public_key

        interfaces = self._wireguard(tree)
        node = interfaces.get(name)
        if not isinstance(node, dict):
            raise VyosPathNotFound(f"WireGuard interface {name} is not configured")
        if "disable" in node:
            raise VyosCommandError(f"WireGuard interface {name} is disabled")

        private_key = node.get("private-key")
        public_key = ""
        if isinstance(private_key, str):
            try:
                public_key = derive_public_key(private_key)
            except WireGuardKeyError:
                public_key = ""

        lines = [f"interface: {name}"]
        if public_key:
            lines.append(f"  public key: {public_key}")
        lines.append("  private key: (hidden)")
        if node.get("port") is not None:
            lines.append(f"  listening port: {node['port']}")

        handshakes = (
            "23 hours, 45 minutes, 26 seconds ago",
            "2 days, 3 hours, 8 minutes, 11 seconds ago",
        )
        transfers = (
            "1.26 MiB received, 6.47 MiB sent",
            "512 KiB received, 1.02 MiB sent",
        )
        peers = node.get("peer", {})
        if not isinstance(peers, dict):
            peers = {}
        index = 0
        for _alias, peer in sorted(peers.items()):
            if not isinstance(peer, dict) or "disable" in peer:
                continue
            lines.append("")
            lines.append(f"peer: {peer.get('public-key', '')}")
            endpoint = peer.get("address") or peer.get("host-name")
            if endpoint:
                formatted = f"[{endpoint}]" if ":" in str(endpoint) else str(endpoint)
                if peer.get("port") is not None:
                    formatted = f"{formatted}:{peer['port']}"
                lines.append(f"  endpoint: {formatted}")
            allowed = peer.get("allowed-ips")
            if isinstance(allowed, dict) and allowed:
                lines.append(f"  allowed ips: {', '.join(sorted(allowed))}")
            if peer.get("persistent-keepalive") is not None:
                lines.append(
                    f"  persistent keepalive: every {peer['persistent-keepalive']} seconds"
                )
            lines.append(f"  latest handshake: {handshakes[index % len(handshakes)]}")
            lines.append(f"  transfer: {transfers[index % len(transfers)]}")
            index += 1

        return "\n".join(lines) + "\n"

    def _render_ospf_neighbors(self, tree: dict[str, Any], version: str) -> str:
        """Render a realistic ``show ... neighbor`` table.

        The neighbours are derived from the configured interfaces so the mock
        stays useful after interfaces are added or removed: the first two
        interfaces get one neighbour each; for OSPFv3 the second neighbour is
        2-Way to exercise the ``established`` flag.
        """

        ospf = self._ospf(tree, version)
        if not ospf:
            return f"OSPF{'v3' if version == 'v3' else ''} is not running\n"

        interfaces = sorted(ospf.get("interface", {}))
        lines = [
            "Neighbor ID     Pri State           Dead Time Address         "
            "Interface                        RXmtL RqstL DBsmL"
        ]
        for index, interface in enumerate(interfaces[:2]):
            if version == "v2":
                neighbor_id = f"10.0.0.{index + 2}"
                address = f"10.0.0.{index + 2}"
                state = "Full/DR" if index == 0 else "Full/Backup"
                dead_time = "38.365s" if index == 0 else "39.102s"
            else:
                neighbor_id = f"10.0.0.{index + 2}"
                address = f"fe80::1{index + 1}"
                state = "Full/DR" if index == 0 else "2-Way/DROther"
                dead_time = "38.365s" if index == 0 else "00:00:37"
            lines.append(
                f"{neighbor_id:<15} {1:>3} {state:<15} {dead_time:<15} "
                f"{address:<15} {interface:<32} {0:>5} {0:>5} {0:>5}"
            )
        lines.append("")
        return "\n".join(lines) + "\n"

    def _uptime_string(self) -> str:
        return "14d 03h 12m"

    def _peer_statuses(self, tree: dict[str, Any]) -> list[BgpPeerStatus]:
        bgp = self._bgp(tree)
        neighbors = bgp.get("neighbor", {})
        if not isinstance(neighbors, dict):
            return []
        peers: list[BgpPeerStatus] = []
        for index, (address, data) in enumerate(sorted(neighbors.items())):
            if not isinstance(data, dict):
                data = {}
            families = data.get("address-family", {})
            family = "ipv4-unicast"
            if isinstance(families, dict) and families:
                family = "ipv6-unicast" if "ipv6-unicast" in families else "ipv4-unicast"
            shutdown = "shutdown" in data
            established = not shutdown
            peers.append(
                BgpPeerStatus(
                    address=address,
                    remote_as=data.get("remote-as"),
                    state="Idle (Admin)" if shutdown else "Established",
                    established=established,
                    uptime=None if shutdown else f"{index + 2}d 0{index + 1}h 22m",
                    prefixes_received=0 if shutdown else 12 + index * 7,
                    prefixes_sent=0 if shutdown else 3 + index,
                    msg_received=120 + index * 31,
                    msg_sent=118 + index * 29,
                    description=data.get("description"),
                    address_family=family,
                )
            )
        return peers

    def _render_summary(self, tree: dict[str, Any]) -> str:
        bgp = self._bgp(tree)
        if not bgp:
            return "BGP is not configured\n"
        router_id = bgp.get("parameters", {}).get("router-id", "0.0.0.0")
        local_as = bgp.get("system-as", "0")
        lines = [
            "IPv4 Unicast Summary:",
            f"BGP router identifier {router_id}, local AS number {local_as}",
            "BGP table version 42",
            "RIB entries 48, using 9216 bytes of memory",
            "Peers 3, using 63 KiB of memory",
            "",
            "Neighbor          V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ  "
            "Up/Down State/PfxRcd   PfxSnt Desc",
        ]
        for peer in self._peer_statuses(tree):
            state_field = peer.prefixes_received if peer.established else peer.state
            desc = peer.description or "N/A"
            lines.append(
                f"{peer.address:<17} 4  {peer.remote_as or 0:>9}  {peer.msg_received or 0:>8}  "
                f"{peer.msg_sent or 0:>8}  0       0    0  "
                f"{peer.uptime or 'never':>8} {state_field!s:>11}  "
                f"{peer.prefixes_sent or 0:>6} {desc}"
            )
        lines.append("")
        lines.append(f"Total number of neighbors {len(self._peer_statuses(tree))}")
        return "\n".join(lines) + "\n"

    async def get_bgp_status(self) -> BgpStatus:
        with self._lock:
            tree = copy.deepcopy(self._trees[self._target.id])
        bgp = self._bgp(tree)
        if not bgp:
            return BgpStatus(configured=False, error="BGP is not configured")
        peers = self._peer_statuses(tree)
        parameters = bgp.get("parameters", {})
        return BgpStatus(
            configured=True,
            router_id=parameters.get("router-id") if isinstance(parameters, dict) else None,
            local_as=int(bgp["system-as"]) if str(bgp.get("system-as", "")).isdigit() else None,
            peers=peers,
            total_peers=len(peers),
            established_peers=sum(1 for peer in peers if peer.established),
        )

    async def get_system_info(self) -> SystemInfo:
        with self._lock:
            tree = copy.deepcopy(self._trees[self._target.id])
        system = tree.get("system", {})
        hostname = system.get("host-name") if isinstance(system, dict) else None
        started = time.perf_counter()
        return SystemInfo(
            hostname=hostname,
            version="VyOS 1.5-rolling-202601010000 (mock)",
            uptime=self._uptime_string(),
            driver=RouterDriver.MOCK,
            reachable=True,
            latency_ms=round((time.perf_counter() - started) * 1000 + 3.2, 2),
        )

    async def close(self) -> None:
        return None
