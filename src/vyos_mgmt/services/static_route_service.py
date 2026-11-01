"""Static-route domain service: VyOS ``protocols static route[6]`` <-> API DTOs.

IPv4 static routes live under ``protocols static route <ipv4net>`` and IPv6
routes under ``protocols static route6 <ipv6net>``; one module handles both.
The API identifies a route by ``family`` + canonical ``prefix``.

Reads canonicalise the device key (IPv6 compression, dotted-quad variants) and
the next-hop addresses, sort routes by family then prefix, and skip anything the
API model cannot represent (for example a route with both ``blackhole`` and
``reject``) instead of failing the whole list.

Writes use exactly one atomic ``driver.apply`` batch per mutation.  An update is
a full replacement of the managed fields (``description``, ``blackhole``,
``reject``, ``distance``, ``tag`` and ``next_hops``) but only the managed leaves
are touched, so unknown directives on retained next hops (BFD, SRv6 segments,
VRF) survive.  Type transitions clean up the obsolete nodes in the same batch.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from pydantic import ValidationError

from vyos_mgmt.db.models import Router
from vyos_mgmt.schemas.static_route import (
    STATIC_ROUTE_FAMILIES,
    StaticNextHop,
    StaticRouteCreate,
    StaticRouteFamily,
    StaticRouteList,
    StaticRouteRead,
    StaticRouteUpdate,
    canonical_route_prefix,
    family_version,
)
from vyos_mgmt.services.vyos.base import ConfigOp, VyosDriver, VyosPathNotFound

STATIC_ROUTE_ROOTS: dict[StaticRouteFamily, list[str]] = {
    "ipv4": ["protocols", "static", "route"],
    "ipv6": ["protocols", "static", "route6"],
}
FAMILY_LABELS: dict[StaticRouteFamily, str] = {"ipv4": "IPv4", "ipv6": "IPv6"}
MANAGED_TYPE_NODES: tuple[str, ...] = ("blackhole", "reject")
MANAGED_NEXT_HOP_NODES: tuple[str, ...] = ("next-hop", "interface")


class StaticRouteError(Exception):
    """Base class for static-route domain failures."""


class StaticRouteConflictError(StaticRouteError):
    """A route with the requested family+prefix already exists."""


class StaticRouteExistsError(StaticRouteConflictError):
    pass


class StaticRouteNotFoundError(StaticRouteError):
    pass


class StaticRouteValidationError(StaticRouteError):
    """A semantic validation error that Pydantic cannot express on its own."""

    def __init__(self, message: str, *, field: str = "prefix", value: Any = None) -> None:
        super().__init__(message)
        self.field = field
        self.value = value


# ---------------------------------------------------------------------------
# Config-tree helpers
# ---------------------------------------------------------------------------


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _scalar(value: Any) -> str | None:
    """Return a VyOS leaf value, tolerating single-key value nodes."""

    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict) and len(value) == 1:
        key, child = next(iter(value.items()))
        if child == {}:
            return str(key)
    return None


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _network_for_family(
    value: Any, family: StaticRouteFamily
) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    """Parse a device prefix key, returning ``None`` for malformed/wrong-family keys."""

    if not isinstance(value, str):
        return None
    try:
        network = ipaddress.ip_network(value.strip(), strict=True)
    except ValueError:
        return None
    if network.version != family_version(family):
        return None
    return network


def _address_for_family(value: Any, family: StaticRouteFamily) -> str | None:
    """Canonicalise a device next-hop address key for the given family."""

    if not isinstance(value, str):
        return None
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if address.version != family_version(family):
        return None
    return str(address)


def _canonical_prefix(family: StaticRouteFamily, prefix: str) -> str:
    """Canonicalise an API prefix or raise a field-scoped validation error."""

    try:
        return canonical_route_prefix(prefix, family)
    except ValueError as exc:
        raise StaticRouteValidationError(str(exc), field="prefix", value=prefix) from exc


def _prefix_sort_key(prefix: str) -> tuple[int, int, int]:
    network = ipaddress.ip_network(prefix, strict=True)
    return (network.version, int(network.network_address), network.prefixlen)


def _next_hop_sort_key(hop: StaticNextHop) -> tuple[int, bytes, str]:
    """Sort addressed hops numerically before interface-only hops."""

    if hop.address is None:
        return (1, b"", hop.interface or "")
    return (0, ipaddress.ip_address(hop.address).packed, hop.interface or "")


def _address_sort_key(value: str) -> tuple[int, int]:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:  # pragma: no cover - guarded by schema/service validation
        return (99, 0)
    return (address.version, int(address))


def _resolve_prefix(family: StaticRouteFamily, raw: Any, prefix: str) -> str | None:
    """Return the raw device key matching a canonical API prefix, if any.

    The device may store an equivalent but differently spelled key (for example
    an uncompressed IPv6 network or a dotted-quad IPv4-mapped IPv6 prefix), so
    both sides are canonicalised before comparing.
    """

    target = _canonical_prefix(family, prefix)
    for key in _dict(raw):
        network = _network_for_family(str(key), family)
        if network is not None and str(network) == target:
            return str(key)
    return None


# ---------------------------------------------------------------------------
# Read parsing
# ---------------------------------------------------------------------------


def _parse_next_hop(address: str | None, raw: Any) -> StaticNextHop | None:
    node = _dict(raw)
    candidate: dict[str, Any] = {
        "address": address,
        "interface": _scalar(node.get("interface")),
        "distance": _as_int(node.get("distance")),
        "enabled": "disable" not in node,
    }
    try:
        return StaticNextHop.model_validate(candidate)
    except ValidationError:
        # An unrepresentable next hop (bad address key, malformed interface
        # name, out-of-range distance) is skipped rather than failing the route.
        return None


def parse_next_hops(raw: Any, family: StaticRouteFamily) -> list[StaticNextHop]:
    """Parse addressed and interface-only next hops, sorted deterministically."""

    node = _dict(raw)
    hops: list[StaticNextHop] = []
    for raw_address, raw_hop in _dict(node.get("next-hop")).items():
        address = _address_for_family(raw_address, family)
        if address is None:
            continue
        hop = _parse_next_hop(address, raw_hop)
        if hop is not None:
            hops.append(hop)
    for raw_interface, raw_hop in _dict(node.get("interface")).items():
        hop = _parse_next_hop(None, {"interface": str(raw_interface), **_dict(raw_hop)})
        if hop is not None:
            hops.append(hop)
    hops.sort(key=_next_hop_sort_key)
    return hops


def parse_static_route(family: StaticRouteFamily, prefix: str, raw: Any) -> StaticRouteRead | None:
    """Parse one ``protocols static route[6] <prefix>`` node.

    Returns ``None`` when the config cannot be represented by the API model
    (wrong-family or malformed key, both discard types at once, a unicast route
    without any usable next hop, or an out-of-range value).
    """

    node = _dict(raw)
    network = _network_for_family(prefix, family)
    if network is None:
        return None
    blackhole = "blackhole" in node
    reject = "reject" in node
    if blackhole and reject:
        return None
    discard = _dict(node.get("blackhole" if blackhole else "reject")) if blackhole or reject else {}
    next_hops = [] if blackhole or reject else parse_next_hops(node, family)
    if not blackhole and not reject and not next_hops:
        return None
    candidate = {
        "family": family,
        "prefix": str(network),
        "description": _scalar(node.get("description")),
        "blackhole": blackhole,
        "reject": reject,
        "distance": _as_int(discard.get("distance")) if discard else None,
        "tag": _as_int(discard.get("tag")) if discard else None,
        "next_hops": [hop.model_dump() for hop in next_hops],
    }
    try:
        return StaticRouteRead.model_validate(candidate)
    except ValidationError:
        return None


def parse_static_routes(family: StaticRouteFamily, raw: Any) -> list[StaticRouteRead]:
    """Parse a static-route tree, sorted by numeric prefix."""

    routes = [
        route
        for key, value in _dict(raw).items()
        if (route := parse_static_route(family, str(key), value)) is not None
    ]
    routes.sort(key=lambda route: _prefix_sort_key(route.prefix))
    return routes


# ---------------------------------------------------------------------------
# Write planning
# ---------------------------------------------------------------------------


def _set(path: list[str]) -> ConfigOp:
    return ConfigOp("set", path)


def _delete(path: list[str]) -> ConfigOp:
    return ConfigOp("delete", path)


def _sync_leaf(
    ops: list[ConfigOp],
    base: list[str],
    existing: dict[str, Any],
    key: str,
    desired: str | None,
) -> None:
    current = _scalar(existing.get(key))
    if desired:
        if current != desired:
            ops.append(_set([*base, key, desired]))
    elif key in existing:
        ops.append(_delete([*base, key]))


def _sync_int_leaf(
    ops: list[ConfigOp],
    base: list[str],
    existing: dict[str, Any],
    key: str,
    desired: int | None,
) -> None:
    current = _as_int(existing.get(key))
    if desired is None:
        if key in existing:
            ops.append(_delete([*base, key]))
    elif current != desired:
        ops.append(_set([*base, key, str(desired)]))


def _sync_disable(
    ops: list[ConfigOp], base: list[str], existing: dict[str, Any], enabled: bool
) -> None:
    """Sync the valueless ``disable`` node with ``enabled``."""

    disabled = "disable" in existing
    if enabled and disabled:
        ops.append(_delete([*base, "disable"]))
    elif not enabled and not disabled:
        ops.append(_set([*base, "disable"]))


def _plan_addressed_next_hops(
    ops: list[ConfigOp],
    base: list[str],
    existing: dict[str, Any],
    family: StaticRouteFamily,
    hops: list[StaticNextHop],
) -> None:
    existing_next = _dict(existing.get("next-hop"))
    # The VyOS ``next-hop`` tag node is keyed by address, so one address maps to
    # one next hop; later duplicates in the payload win (the schema only rejects
    # duplicate (address, interface) pairs).
    desired: dict[str, StaticNextHop] = {}
    for hop in hops:
        if hop.address is not None:
            desired[hop.address] = hop

    existing_keys: dict[str, str] = {}
    for raw_address in existing_next:
        canonical = _address_for_family(str(raw_address), family)
        if canonical is not None:
            existing_keys[canonical] = str(raw_address)

    for canonical, raw_address in existing_keys.items():
        if canonical not in desired:
            ops.append(_delete([*base, "next-hop", raw_address]))

    for canonical in sorted(desired, key=_address_sort_key):
        hop = desired[canonical]
        raw_address = existing_keys.get(canonical)
        if raw_address is None:
            node_base = [*base, "next-hop", canonical]
            node: dict[str, Any] = {}
            ops.append(_set(node_base))
        else:
            node_base = [*base, "next-hop", raw_address]
            node = _dict(existing_next.get(raw_address))
        if hop.interface is not None:
            if _scalar(node.get("interface")) != hop.interface:
                ops.append(_set([*node_base, "interface", hop.interface]))
        elif "interface" in node:
            ops.append(_delete([*node_base, "interface"]))
        _sync_int_leaf(ops, node_base, node, "distance", hop.distance)
        _sync_disable(ops, node_base, node, hop.enabled)


def _plan_interface_next_hops(
    ops: list[ConfigOp],
    base: list[str],
    existing: dict[str, Any],
    hops: list[StaticNextHop],
) -> None:
    existing_interfaces = _dict(existing.get("interface"))
    desired: dict[str, StaticNextHop] = {}
    for hop in hops:
        if hop.address is None and hop.interface is not None:
            desired[hop.interface] = hop

    for raw_interface in existing_interfaces:
        if str(raw_interface) not in desired:
            ops.append(_delete([*base, "interface", str(raw_interface)]))

    for name in sorted(desired):
        hop = desired[name]
        if name in existing_interfaces:
            node_base = [*base, "interface", name]
            node = _dict(existing_interfaces[name])
        else:
            node_base = [*base, "interface", name]
            node = {}
            ops.append(_set(node_base))
        _sync_int_leaf(ops, node_base, node, "distance", hop.distance)
        _sync_disable(ops, node_base, node, hop.enabled)


def _plan_next_hops(
    ops: list[ConfigOp],
    base: list[str],
    existing: dict[str, Any],
    family: StaticRouteFamily,
    hops: list[StaticNextHop],
) -> None:
    _plan_addressed_next_hops(ops, base, existing, family, hops)
    _plan_interface_next_hops(ops, base, existing, hops)


def _desired_type(blackhole: bool, reject: bool) -> str:
    if blackhole:
        return "blackhole"
    if reject:
        return "reject"
    return "unicast"


def build_create_ops(
    family: StaticRouteFamily, prefix: str, payload: StaticRouteCreate | StaticRouteUpdate
) -> list[ConfigOp]:
    """Plan the atomic batch that creates one static route."""

    base = [*STATIC_ROUTE_ROOTS[family], prefix]
    return [_set(base), *build_update_ops(family, prefix, payload, {})]


def build_update_ops(
    family: StaticRouteFamily,
    prefix: str,
    payload: StaticRouteUpdate | StaticRouteCreate,
    existing: dict[str, Any],
) -> list[ConfigOp]:
    """Plan the batch that makes the managed fields match ``payload``.

    ``prefix`` is the **raw** device key (see :func:`_resolve_prefix`), so an
    update never rewrites an equivalent prefix spelling.  Only managed leaves
    are touched; unknown leaves on retained next hops are preserved.
    """

    base = [*STATIC_ROUTE_ROOTS[family], prefix]
    ops: list[ConfigOp] = []

    _sync_leaf(ops, base, existing, "description", payload.description)

    desired = _desired_type(payload.blackhole, payload.reject)
    for node_name in MANAGED_TYPE_NODES:
        if node_name == desired:
            node_base = [*base, node_name]
            if node_name not in existing:
                ops.append(_set(node_base))
            node = _dict(existing.get(node_name))
            _sync_int_leaf(ops, node_base, node, "distance", payload.distance)
            _sync_int_leaf(ops, node_base, node, "tag", payload.tag)
        elif node_name in existing:
            ops.append(_delete([*base, node_name]))

    # Route-level distance/tag do not exist in the VyOS schema; drop any stray
    # value so a unicast route can never inherit a stale metric.
    for key in ("distance", "tag"):
        if key in existing:
            ops.append(_delete([*base, key]))

    if desired == "unicast":
        _plan_next_hops(ops, base, existing, family, payload.next_hops)
    else:
        for key in MANAGED_NEXT_HOP_NODES:
            if key in existing:
                ops.append(_delete([*base, key]))
    return ops


def build_delete_ops(family: StaticRouteFamily, prefix: str) -> list[ConfigOp]:
    return [_delete([*STATIC_ROUTE_ROOTS[family], prefix])]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class StaticRouteService:
    def __init__(self, driver: VyosDriver, router: Router) -> None:
        self._driver = driver
        self._router = router

    async def _raw_tree(self, family: StaticRouteFamily) -> dict[str, Any]:
        try:
            raw = await self._driver.get_config(STATIC_ROUTE_ROOTS[family])
        except VyosPathNotFound:
            return {}
        return _dict(raw)

    async def list(self, family: StaticRouteFamily | None = None) -> StaticRouteList:
        families: tuple[StaticRouteFamily, ...] = (
            (family,) if family is not None else STATIC_ROUTE_FAMILIES
        )
        items: list[StaticRouteRead] = []
        for current in families:
            items.extend(parse_static_routes(current, await self._raw_tree(current)))
        items.sort(key=lambda item: (item.family, *_prefix_sort_key(item.prefix)))
        return StaticRouteList(items=items, total=len(items))

    async def get(self, family: StaticRouteFamily, prefix: str) -> StaticRouteRead:
        raw = await self._raw_tree(family)
        key = _resolve_prefix(family, raw, prefix)
        if key is None:
            raise StaticRouteNotFoundError(
                f"{FAMILY_LABELS[family]} static route {prefix} does not exist"
            )
        route = parse_static_route(family, key, raw[key])
        if route is None:
            raise StaticRouteNotFoundError(
                f"{FAMILY_LABELS[family]} static route {prefix} cannot be represented "
                "by the API (unsupported or malformed device configuration)"
            )
        return route

    def _validate_next_hop_families(
        self, family: StaticRouteFamily, payload: StaticRouteCreate | StaticRouteUpdate
    ) -> None:
        """Enforce the route family on next-hop addresses.

        ``StaticRouteUpdate`` does not need a body family, so the schema cannot
        check this on its own; the create schema already did, but running the
        check again is cheap and keeps both write paths identical.
        """

        expected = family_version(family)
        for index, hop in enumerate(payload.next_hops):
            if hop.address is None:
                continue
            version = ipaddress.ip_address(hop.address).version
            if version != expected:
                raise StaticRouteValidationError(
                    f"Next-hop address {hop.address} is IPv{version} but the route "
                    f"family is {family}",
                    field=f"next_hops.{index}.address",
                    value=hop.address,
                )

    async def create(self, payload: StaticRouteCreate) -> StaticRouteRead:
        raw = await self._raw_tree(payload.family)
        if _resolve_prefix(payload.family, raw, payload.prefix) is not None:
            raise StaticRouteExistsError(
                f"{FAMILY_LABELS[payload.family]} static route {payload.prefix} already exists"
            )
        self._validate_next_hop_families(payload.family, payload)
        await self._driver.apply(build_create_ops(payload.family, payload.prefix, payload))
        return await self.get(payload.family, payload.prefix)

    async def update(
        self, family: StaticRouteFamily, prefix: str, payload: StaticRouteUpdate
    ) -> StaticRouteRead:
        raw = await self._raw_tree(family)
        key = _resolve_prefix(family, raw, prefix)
        if key is None:
            raise StaticRouteNotFoundError(
                f"{FAMILY_LABELS[family]} static route {prefix} does not exist"
            )
        self._validate_next_hop_families(family, payload)
        ops = build_update_ops(family, key, payload, _dict(raw[key]))
        if ops:
            await self._driver.apply(ops)
        return await self.get(family, key)

    async def delete(self, family: StaticRouteFamily, prefix: str) -> None:
        raw = await self._raw_tree(family)
        key = _resolve_prefix(family, raw, prefix)
        if key is None:
            raise StaticRouteNotFoundError(
                f"{FAMILY_LABELS[family]} static route {prefix} does not exist"
            )
        await self._driver.apply(build_delete_ops(family, key))


__all__ = [
    "FAMILY_LABELS",
    "MANAGED_NEXT_HOP_NODES",
    "MANAGED_TYPE_NODES",
    "STATIC_ROUTE_ROOTS",
    "StaticRouteConflictError",
    "StaticRouteError",
    "StaticRouteExistsError",
    "StaticRouteNotFoundError",
    "StaticRouteService",
    "StaticRouteValidationError",
    "build_create_ops",
    "build_delete_ops",
    "build_update_ops",
    "parse_next_hops",
    "parse_static_route",
    "parse_static_routes",
]
