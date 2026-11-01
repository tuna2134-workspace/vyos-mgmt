"""OSPFv2/OSPFv3 domain service.

One service handles both address families because the VyOS trees are almost
identical:

* ``v2`` -> ``protocols ospf`` (IPv4)
* ``v3`` -> ``protocols ospfv3`` (IPv6)

Reads canonicalise area IDs (VyOS accepts decimal and dotted notation, the API
always returns dotted decimal) and tolerate unsupported device directives.
Writes use exactly one atomic ``driver.apply`` batch per mutation and update
only the managed leaves, so unknown directives on areas, interfaces and
redistribution entries survive an API update.
"""

from __future__ import annotations

import ipaddress
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import ValidationError

from vyos_mgmt.db.models import Router
from vyos_mgmt.schemas.ospf import (
    SUPPORTED_NETWORK_TYPES,
    OspfAreaCreate,
    OspfAreaRead,
    OspfAreaType,
    OspfAreaUpdate,
    OspfConfigRead,
    OspfGlobal,
    OspfInterfaceCreate,
    OspfInterfaceRead,
    OspfInterfaceUpdate,
    OspfNeighborStatus,
    OspfRedistributeCreate,
    OspfRedistributeRead,
    OspfRedistributeUpdate,
    OspfRouterRef,
    OspfStatus,
    OspfVersion,
    area_sort_key,
    canonicalize_area_id,
    supported_network_types,
    supported_redistribute_sources,
    validate_network_type_for_version,
    validate_redistribute_source_for_version,
    validate_route_map_name,
)
from vyos_mgmt.services.vyos.base import (
    ConfigOp,
    VyosCommandError,
    VyosDriver,
    VyosPathNotFound,
)

OSPF_ROOTS: dict[OspfVersion, list[str]] = {
    "v2": ["protocols", "ospf"],
    "v3": ["protocols", "ospfv3"],
}
OSPF_SHOW_NEIGHBORS: dict[OspfVersion, list[str]] = {
    "v2": ["ip", "ospf", "neighbor"],
    "v3": ["ipv6", "ospfv3", "neighbor"],
}
OSPF_VERSION_LABELS: dict[OspfVersion, str] = {"v2": "OSPFv2", "v3": "OSPFv3"}
ROUTE_MAP_ROOT = ["policy", "route-map"]

_NOT_RUNNING_MARKERS = (
    "not running",
    "not configured",
    "daemon",
)


class OspfError(Exception):
    """Base class for OSPF domain failures."""


class OspfConflictError(OspfError):
    """A conflicting object already exists."""


class OspfAreaExistsError(OspfConflictError):
    pass


class OspfInterfaceExistsError(OspfConflictError):
    pass


class OspfRedistributeExistsError(OspfConflictError):
    pass


class OspfNotFoundError(OspfError):
    """A requested object does not exist on the device."""


class OspfAreaNotFoundError(OspfNotFoundError):
    pass


class OspfInterfaceNotFoundError(OspfNotFoundError):
    pass


class OspfRedistributeNotFoundError(OspfNotFoundError):
    pass


class OspfAreaInUseError(OspfError):
    """Deletion was refused because an interface references the area."""

    def __init__(self, message: str, *, used_by: list[str]) -> None:
        super().__init__(message)
        self.used_by = used_by


class OspfValidationError(OspfError):
    """A semantic validation error that Pydantic cannot express on its own."""

    def __init__(self, message: str, *, field: str, value: Any = None) -> None:
        super().__init__(message)
        self.field = field
        self.value = value


class OspfAreaReferenceError(OspfValidationError):
    """An interface references an area that is not configured (422)."""


class OspfRouteMapNotFoundError(OspfValidationError):
    """A redistribution rule references a missing route map (422)."""


# ---------------------------------------------------------------------------
# Config-tree helpers
# ---------------------------------------------------------------------------


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _present(node: Any, key: str) -> bool:
    return isinstance(node, dict) and key in node


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
    if isinstance(value, bool):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _as_bounded_int(value: Any, minimum: int, maximum: int) -> int | None:
    number = _as_int(value)
    if number is None or not minimum <= number <= maximum:
        return None
    return number


def _parse_area_key(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return canonicalize_area_id(str(value))
    except ValueError:
        return None


def _area_index(raw_areas: Any) -> dict[str, str]:
    """Map canonical area IDs to the raw device key (decimal or dotted).

    A malformed key is ignored: it cannot be represented by the API.  If the
    device somehow contains two keys that canonicalise to the same area, the
    first key in sorted order wins deterministically.
    """

    index: dict[str, str] = {}
    for raw_key in sorted(_dict(raw_areas)):
        canonical = _parse_area_key(raw_key)
        if canonical is not None:
            index.setdefault(canonical, str(raw_key))
    return index


def _interface_area(raw: dict[str, Any]) -> str | None:
    return _parse_area_key(_scalar(raw.get("area")))


def _area_type(raw: dict[str, Any]) -> tuple[OspfAreaType, bool]:
    """Read the managed area type and ``no_summary`` flag."""

    node = raw.get("area-type")
    container = _dict(node)
    for candidate in ("stub", "nssa"):
        if _present(container, candidate):
            area_type = cast(OspfAreaType, candidate)
            return area_type, _present(_dict(container[candidate]), "no-summary")
    scalar = _scalar(node)
    if scalar in {"stub", "nssa"}:
        return cast(OspfAreaType, scalar), False
    return "normal", False


def parse_global(raw: Any) -> OspfGlobal:
    """Parse global OSPF settings, dropping values the API cannot represent."""

    node = _dict(raw)
    parameters = _dict(node.get("parameters"))
    router_id = _scalar(parameters.get("router-id"))
    try:
        router_id = str(ipaddress.IPv4Address(router_id)) if router_id else None
    except ValueError:
        router_id = None

    log_node = node.get("log-adjacency-changes")
    if not _present(node, "log-adjacency-changes"):
        log_value = "none"
    elif _present(_dict(log_node), "detail") or _scalar(log_node) == "detail":
        log_value = "detail"
    else:
        log_value = "normal"

    auto_cost = _as_bounded_int(
        _dict(node.get("auto-cost")).get("reference-bandwidth"), 1, 4_294_967
    )
    default_information = _dict(node.get("default-information"))
    originate = _present(default_information, "originate")
    always = originate and _present(_dict(default_information.get("originate")), "always")
    distance = _as_bounded_int(_dict(node.get("distance")).get("global"), 1, 255)

    return OspfGlobal(
        router_id=router_id,
        log_adjacency_changes=log_value,
        auto_cost_reference_bandwidth=auto_cost,
        default_information_originate=originate,
        default_information_always=always,
        distance_global=distance,
    )


def parse_area(canonical_id: str, raw: Any, interface_count: int) -> OspfAreaRead:
    area_type, no_summary = _area_type(_dict(raw))
    return OspfAreaRead(
        area_id=canonical_id,
        area_type=area_type,
        no_summary=no_summary,
        interface_count=interface_count,
    )


def parse_interface(name: str, raw: Any) -> OspfInterfaceRead | None:
    node = _dict(raw)
    area_id = _interface_area(node)
    network_value = _scalar(node.get("network"))
    network_type = network_value if network_value in {*SUPPORTED_NETWORK_TYPES["v2"]} else None
    passive_node = node.get("passive")
    passive = _present(node, "passive") and not _present(_dict(passive_node), "disable")
    candidate = {
        "name": name,
        "area_id": area_id,
        "network_type": network_type,
        "cost": _as_bounded_int(node.get("cost"), 1, 65_535),
        "hello_interval": _as_bounded_int(node.get("hello-interval"), 1, 65_535),
        "dead_interval": _as_bounded_int(node.get("dead-interval"), 1, 65_535),
        "priority": _as_bounded_int(node.get("priority"), 0, 255),
        "passive": passive,
        "bfd": _present(node, "bfd"),
        "mtu_ignore": _present(node, "mtu-ignore"),
        "retransmit_interval": _as_bounded_int(node.get("retransmit-interval"), 1, 65_535),
        "transmit_delay": _as_bounded_int(node.get("transmit-delay"), 1, 65_535),
    }
    try:
        return OspfInterfaceRead.model_validate(candidate)
    except ValidationError:
        return None


def parse_redistribution(source: str, raw: Any) -> OspfRedistributeRead:
    node = _dict(raw)
    metric_type = _as_int(node.get("metric-type"))
    route_map = _scalar(node.get("route-map"))
    if route_map is not None:
        try:
            route_map = validate_route_map_name(route_map)
        except ValueError:
            route_map = None
    return OspfRedistributeRead(
        source=source,
        metric=_as_bounded_int(node.get("metric"), 1, 16_777_214),
        metric_type=metric_type if metric_type in {1, 2} else None,
        route_map=route_map,
    )


def parse_ospf_config(
    router_id: uuid.UUID,
    router_name: str,
    version: OspfVersion,
    raw: Any,
) -> OspfConfigRead:
    """Parse one ``protocols ospf``/``protocols ospfv3`` root."""

    root = _dict(raw)
    raw_areas = _dict(root.get("area"))
    raw_interfaces = _dict(root.get("interface"))

    counts: dict[str, int] = {}
    for interface in raw_interfaces.values():
        area_id = _interface_area(_dict(interface))
        if area_id is not None:
            counts[area_id] = counts.get(area_id, 0) + 1

    areas = [
        parse_area(canonical, raw_areas[raw_key], counts.get(canonical, 0))
        for canonical, raw_key in sorted(
            _area_index(raw_areas).items(), key=lambda item: area_sort_key(item[0])
        )
    ]

    interfaces = sorted(
        (
            parsed
            for name, value in raw_interfaces.items()
            if (parsed := parse_interface(str(name), value)) is not None
        ),
        key=lambda item: item.name,
    )

    redistributions = [
        parse_redistribution(str(source), value)
        for source, value in sorted(_dict(root.get("redistribute")).items())
    ]

    return OspfConfigRead(
        router=OspfRouterRef(id=router_id, name=router_name),
        version=version,
        configured=bool(root),
        global_config=parse_global(root),
        areas=areas,
        interfaces=interfaces,
        redistributions=redistributions,
        supported_network_types=supported_network_types(version),
        supported_redistribute_sources=supported_redistribute_sources(version),
    )


# ---------------------------------------------------------------------------
# Operational status parsing
# ---------------------------------------------------------------------------


def _looks_not_running(output: str) -> bool:
    lowered = output.lower()
    return any(marker in lowered for marker in _NOT_RUNNING_MARKERS)


def parse_ospf_neighbors(output: str) -> list[OspfNeighborStatus]:
    """Parse ``show ip ospf neighbor`` / ``show ipv6 ospfv3 neighbor``.

    The tabular output has the columns::

        Neighbor ID Pri State Dead Time Address Interface RXmtL RqstL DBsmL

    Only the first six columns are mapped; the retransmit/request/DB-summary
    counters are operational details the contract does not expose.
    """

    neighbors: list[OspfNeighborStatus] = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 6:
            continue
        if fields[0].lower() == "neighbor":
            continue
        try:
            neighbor_id = str(ipaddress.IPv4Address(fields[0]))
        except ValueError:
            continue
        priority = _as_int(fields[1])
        state = fields[2]
        neighbors.append(
            OspfNeighborStatus(
                neighbor_id=neighbor_id,
                priority=priority if priority is not None and 0 <= priority <= 255 else None,
                state=state,
                dead_time=fields[3],
                address=fields[4],
                interface=fields[5],
                established=state.startswith("Full"),
            )
        )
    return neighbors


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


def _sync_presence(
    ops: list[ConfigOp],
    base: list[str],
    existing: dict[str, Any],
    key: str,
    desired: bool,
) -> None:
    if desired and key not in existing:
        ops.append(_set([*base, key]))
    elif not desired and key in existing:
        ops.append(_delete([*base, key]))


def _sync_passive(
    ops: list[ConfigOp],
    base: list[str],
    existing: dict[str, Any],
    desired: bool,
) -> None:
    """Sync passive state.

    OSPFv2 models ``passive`` as a node with an optional ``disable`` child,
    while OSPFv3 uses a valueless leaf.  The API only exposes the effective
    state, so an explicit ``disable`` is cleared when passive is requested.
    """

    node = existing.get("passive")
    present = "passive" in existing
    disabled = _present(_dict(node), "disable")
    current = present and not disabled
    if desired == current:
        return
    if desired:
        if present:
            ops.append(_delete([*base, "passive"]))
        ops.append(_set([*base, "passive"]))
    else:
        ops.append(_delete([*base, "passive"]))


def build_global_update_ops(
    version: OspfVersion, payload: OspfGlobal, existing: dict[str, Any]
) -> list[ConfigOp]:
    """Plan a full replacement of the API-managed global leaves."""

    root = OSPF_ROOTS[version]
    node = _dict(existing)
    parameters = _dict(node.get("parameters"))
    ops: list[ConfigOp] = []

    _sync_leaf(ops, [*root, "parameters"], parameters, "router-id", payload.router_id)

    log_present = "log-adjacency-changes" in node
    log_node = _dict(node.get("log-adjacency-changes"))
    current_log = (
        "detail"
        if _present(log_node, "detail") or _scalar(node.get("log-adjacency-changes")) == "detail"
        else ("normal" if log_present else "none")
    )
    if payload.log_adjacency_changes == "none":
        if log_present:
            ops.append(_delete([*root, "log-adjacency-changes"]))
    elif payload.log_adjacency_changes == "normal":
        if not log_present:
            ops.append(_set([*root, "log-adjacency-changes"]))
        elif _present(log_node, "detail"):
            ops.append(_delete([*root, "log-adjacency-changes", "detail"]))
    else:
        if not log_present:
            ops.append(_set([*root, "log-adjacency-changes"]))
        if current_log != "detail":
            ops.append(_set([*root, "log-adjacency-changes", "detail"]))

    _sync_int_leaf(
        ops,
        [*root, "auto-cost"],
        _dict(node.get("auto-cost")),
        "reference-bandwidth",
        payload.auto_cost_reference_bandwidth,
    )

    default_information = _dict(node.get("default-information"))
    originate_present = _present(default_information, "originate")
    if payload.default_information_originate:
        if not originate_present:
            ops.append(_set([*root, "default-information", "originate"]))
        always_present = _present(_dict(default_information.get("originate")), "always")
        if payload.default_information_always and not always_present:
            ops.append(_set([*root, "default-information", "originate", "always"]))
        elif not payload.default_information_always and always_present:
            ops.append(_delete([*root, "default-information", "originate", "always"]))
    elif originate_present:
        ops.append(_delete([*root, "default-information", "originate"]))

    _sync_int_leaf(
        ops,
        [*root, "distance"],
        _dict(node.get("distance")),
        "global",
        payload.distance_global,
    )
    return ops


def build_area_create_ops(version: OspfVersion, payload: OspfAreaCreate) -> list[ConfigOp]:
    base = [*OSPF_ROOTS[version], "area", payload.area_id]
    ops: list[ConfigOp] = [_set(base)]
    if payload.area_type != "normal":
        ops.append(_set([*base, "area-type", payload.area_type]))
        if payload.no_summary:
            ops.append(_set([*base, "area-type", payload.area_type, "no-summary"]))
    return ops


def build_area_update_ops(
    version: OspfVersion,
    raw_key: str,
    payload: OspfAreaUpdate,
    existing: dict[str, Any],
) -> list[ConfigOp]:
    """Sync area type/no-summary without touching other area directives."""

    base = [*OSPF_ROOTS[version], "area", raw_key]
    current_type, current_no_summary = _area_type(existing)
    area_type_present = "area-type" in existing
    ops: list[ConfigOp] = []

    if payload.area_type == "normal":
        if area_type_present:
            ops.append(_delete([*base, "area-type"]))
        return ops

    if current_type == payload.area_type and area_type_present:
        if current_no_summary != payload.no_summary:
            path = [*base, "area-type", payload.area_type, "no-summary"]
            ops.append(_set(path) if payload.no_summary else _delete(path))
        return ops

    if area_type_present:
        ops.append(_delete([*base, "area-type"]))
    ops.append(_set([*base, "area-type", payload.area_type]))
    if payload.no_summary:
        ops.append(_set([*base, "area-type", payload.area_type, "no-summary"]))
    return ops


def build_area_delete_ops(version: OspfVersion, raw_key: str) -> list[ConfigOp]:
    return [_delete([*OSPF_ROOTS[version], "area", raw_key])]


def _interface_leaf_ops(
    ops: list[ConfigOp],
    base: list[str],
    existing: dict[str, Any],
    payload: OspfInterfaceCreate | OspfInterfaceUpdate,
) -> None:
    _sync_leaf(ops, base, existing, "area", payload.area_id)
    _sync_leaf(ops, base, existing, "network", payload.network_type)
    _sync_int_leaf(ops, base, existing, "cost", payload.cost)
    _sync_int_leaf(ops, base, existing, "hello-interval", payload.hello_interval)
    _sync_int_leaf(ops, base, existing, "dead-interval", payload.dead_interval)
    _sync_int_leaf(ops, base, existing, "priority", payload.priority)
    _sync_passive(ops, base, existing, payload.passive)
    _sync_presence(ops, base, existing, "bfd", payload.bfd)
    _sync_presence(ops, base, existing, "mtu-ignore", payload.mtu_ignore)
    _sync_int_leaf(ops, base, existing, "retransmit-interval", payload.retransmit_interval)
    _sync_int_leaf(ops, base, existing, "transmit-delay", payload.transmit_delay)


def build_interface_create_ops(
    version: OspfVersion, payload: OspfInterfaceCreate
) -> list[ConfigOp]:
    base = [*OSPF_ROOTS[version], "interface", payload.name]
    ops: list[ConfigOp] = [_set(base)]
    _interface_leaf_ops(ops, base, {}, payload)
    return ops


def build_interface_update_ops(
    version: OspfVersion,
    name: str,
    payload: OspfInterfaceUpdate,
    existing: dict[str, Any],
) -> list[ConfigOp]:
    base = [*OSPF_ROOTS[version], "interface", name]
    ops: list[ConfigOp] = []
    _interface_leaf_ops(ops, base, existing, payload)
    return ops


def build_interface_delete_ops(version: OspfVersion, name: str) -> list[ConfigOp]:
    return [_delete([*OSPF_ROOTS[version], "interface", name])]


def build_redistribute_create_ops(
    version: OspfVersion, payload: OspfRedistributeCreate
) -> list[ConfigOp]:
    base = [*OSPF_ROOTS[version], "redistribute", payload.source]
    ops: list[ConfigOp] = [_set(base)]
    if payload.metric is not None:
        ops.append(_set([*base, "metric", str(payload.metric)]))
    if payload.metric_type is not None:
        ops.append(_set([*base, "metric-type", str(payload.metric_type)]))
    if payload.route_map:
        ops.append(_set([*base, "route-map", payload.route_map]))
    return ops


def build_redistribute_update_ops(
    version: OspfVersion,
    source: str,
    payload: OspfRedistributeUpdate,
    existing: dict[str, Any],
) -> list[ConfigOp]:
    base = [*OSPF_ROOTS[version], "redistribute", source]
    ops: list[ConfigOp] = []
    _sync_int_leaf(ops, base, existing, "metric", payload.metric)
    _sync_int_leaf(ops, base, existing, "metric-type", payload.metric_type)
    _sync_leaf(ops, base, existing, "route-map", payload.route_map)
    return ops


def build_redistribute_delete_ops(version: OspfVersion, source: str) -> list[ConfigOp]:
    return [_delete([*OSPF_ROOTS[version], "redistribute", source])]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class OspfService:
    def __init__(self, driver: VyosDriver, router: Router) -> None:
        self._driver = driver
        self._router = router

    @staticmethod
    def _root(version: OspfVersion) -> list[str]:
        return OSPF_ROOTS[version]

    async def _raw_config(self, version: OspfVersion) -> dict[str, Any]:
        try:
            raw = await self._driver.get_config(self._root(version))
        except VyosPathNotFound:
            return {}
        return _dict(raw)

    async def _raw_route_maps(self) -> dict[str, Any]:
        try:
            raw = await self._driver.get_config(ROUTE_MAP_ROOT)
        except VyosPathNotFound:
            return {}
        return _dict(raw)

    async def _validate_route_map(self, name: str | None) -> None:
        if not name:
            return
        route_maps = await self._raw_route_maps()
        if name not in route_maps:
            raise OspfRouteMapNotFoundError(
                f"Route map {name} does not exist; create it before referencing it "
                "from OSPF redistribution",
                field="route_map",
                value=name,
            )

    @staticmethod
    def _canonical_area_id(area_id: str) -> str:
        try:
            return canonicalize_area_id(area_id)
        except ValueError as exc:
            raise OspfValidationError(str(exc), field="area_id", value=area_id) from exc

    @staticmethod
    def _validate_area_reference(area_id: str, raw: dict[str, Any]) -> None:
        if area_id not in _area_index(raw.get("area")):
            raise OspfAreaReferenceError(
                f"Area {area_id} does not exist; create it before activating an interface",
                field="area_id",
                value=area_id,
            )

    @staticmethod
    def _validate_network_type(version: OspfVersion, network_type: str | None) -> None:
        if not network_type:
            return
        try:
            validate_network_type_for_version(network_type, version)
        except ValueError as exc:
            raise OspfValidationError(str(exc), field="network_type", value=network_type) from exc

    @staticmethod
    def _validate_source(version: OspfVersion, source: str) -> str:
        try:
            return validate_redistribute_source_for_version(source, version)
        except ValueError as exc:
            raise OspfValidationError(str(exc), field="source", value=source) from exc

    def _parse(self, version: OspfVersion, raw: dict[str, Any]) -> OspfConfigRead:
        return parse_ospf_config(self._router.id, self._router.name, version, raw)

    async def get_config(self, version: OspfVersion) -> OspfConfigRead:
        return self._parse(version, await self._raw_config(version))

    async def update_global(self, version: OspfVersion, payload: OspfGlobal) -> OspfConfigRead:
        raw = await self._raw_config(version)
        ops = build_global_update_ops(version, payload, raw)
        if ops:
            await self._driver.apply(ops)
        return self._parse(version, await self._raw_config(version))

    async def delete_process(self, version: OspfVersion) -> None:
        try:
            await self._driver.apply([_delete(self._root(version))])
        except VyosPathNotFound:
            # Already absent: DELETE is idempotent.
            return

    # -- Areas -------------------------------------------------------------

    async def create_area(self, version: OspfVersion, payload: OspfAreaCreate) -> OspfConfigRead:
        raw = await self._raw_config(version)
        if payload.area_id in _area_index(raw.get("area")):
            raise OspfAreaExistsError(
                f"{OSPF_VERSION_LABELS[version]} area {payload.area_id} already exists"
            )
        await self._driver.apply(build_area_create_ops(version, payload))
        return self._parse(version, await self._raw_config(version))

    async def update_area(
        self, version: OspfVersion, area_id: str, payload: OspfAreaUpdate
    ) -> OspfConfigRead:
        area_id = self._canonical_area_id(area_id)
        raw = await self._raw_config(version)
        index = _area_index(raw.get("area"))
        raw_key = index.get(area_id)
        if raw_key is None:
            raise OspfAreaNotFoundError(
                f"{OSPF_VERSION_LABELS[version]} area {area_id} does not exist"
            )
        existing = _dict(_dict(raw.get("area")).get(raw_key))
        ops = build_area_update_ops(version, raw_key, payload, existing)
        if ops:
            await self._driver.apply(ops)
        return self._parse(version, await self._raw_config(version))

    async def delete_area(self, version: OspfVersion, area_id: str) -> OspfConfigRead:
        area_id = self._canonical_area_id(area_id)
        raw = await self._raw_config(version)
        index = _area_index(raw.get("area"))
        raw_key = index.get(area_id)
        if raw_key is None:
            raise OspfAreaNotFoundError(
                f"{OSPF_VERSION_LABELS[version]} area {area_id} does not exist"
            )

        used_by = sorted(
            str(name)
            for name, interface in _dict(raw.get("interface")).items()
            if _interface_area(_dict(interface)) == area_id
        )
        if used_by:
            raise OspfAreaInUseError(
                f"{OSPF_VERSION_LABELS[version]} area {area_id} is in use and cannot be deleted",
                used_by=used_by,
            )
        await self._driver.apply(build_area_delete_ops(version, raw_key))
        return self._parse(version, await self._raw_config(version))

    # -- Interfaces --------------------------------------------------------

    async def create_interface(
        self, version: OspfVersion, payload: OspfInterfaceCreate
    ) -> OspfConfigRead:
        raw = await self._raw_config(version)
        if payload.name in _dict(raw.get("interface")):
            raise OspfInterfaceExistsError(
                f"{OSPF_VERSION_LABELS[version]} interface {payload.name} already exists"
            )
        self._validate_area_reference(payload.area_id, raw)
        self._validate_network_type(version, payload.network_type)
        await self._driver.apply(build_interface_create_ops(version, payload))
        return self._parse(version, await self._raw_config(version))

    async def update_interface(
        self, version: OspfVersion, name: str, payload: OspfInterfaceUpdate
    ) -> OspfConfigRead:
        raw = await self._raw_config(version)
        interfaces = _dict(raw.get("interface"))
        if name not in interfaces:
            raise OspfInterfaceNotFoundError(
                f"{OSPF_VERSION_LABELS[version]} interface {name} does not exist"
            )
        self._validate_area_reference(payload.area_id, raw)
        self._validate_network_type(version, payload.network_type)
        ops = build_interface_update_ops(version, name, payload, _dict(interfaces[name]))
        if ops:
            await self._driver.apply(ops)
        return self._parse(version, await self._raw_config(version))

    async def delete_interface(self, version: OspfVersion, name: str) -> OspfConfigRead:
        raw = await self._raw_config(version)
        if name not in _dict(raw.get("interface")):
            raise OspfInterfaceNotFoundError(
                f"{OSPF_VERSION_LABELS[version]} interface {name} does not exist"
            )
        await self._driver.apply(build_interface_delete_ops(version, name))
        return self._parse(version, await self._raw_config(version))

    # -- Redistribution ----------------------------------------------------

    async def create_redistribute(
        self, version: OspfVersion, payload: OspfRedistributeCreate
    ) -> OspfConfigRead:
        raw = await self._raw_config(version)
        source = self._validate_source(version, payload.source)
        if source in _dict(raw.get("redistribute")):
            raise OspfRedistributeExistsError(
                f"{OSPF_VERSION_LABELS[version]} already redistributes {source}"
            )
        await self._validate_route_map(payload.route_map)
        payload = payload.model_copy(update={"source": source})
        await self._driver.apply(build_redistribute_create_ops(version, payload))
        return self._parse(version, await self._raw_config(version))

    async def update_redistribute(
        self,
        version: OspfVersion,
        source: str,
        payload: OspfRedistributeUpdate,
    ) -> OspfConfigRead:
        raw = await self._raw_config(version)
        source = self._validate_source(version, source)
        redistribute = _dict(raw.get("redistribute"))
        if source not in redistribute:
            raise OspfRedistributeNotFoundError(
                f"{OSPF_VERSION_LABELS[version]} does not redistribute {source}"
            )
        await self._validate_route_map(payload.route_map)
        ops = build_redistribute_update_ops(version, source, payload, _dict(redistribute[source]))
        if ops:
            await self._driver.apply(ops)
        return self._parse(version, await self._raw_config(version))

    async def delete_redistribute(self, version: OspfVersion, source: str) -> OspfConfigRead:
        raw = await self._raw_config(version)
        source = self._validate_source(version, source)
        if source not in _dict(raw.get("redistribute")):
            raise OspfRedistributeNotFoundError(
                f"{OSPF_VERSION_LABELS[version]} does not redistribute {source}"
            )
        await self._driver.apply(build_redistribute_delete_ops(version, source))
        return self._parse(version, await self._raw_config(version))

    # -- Status ------------------------------------------------------------

    async def get_status(self, version: OspfVersion) -> OspfStatus:
        raw = await self._raw_config(version)
        router_id = parse_global(raw).router_id
        if not raw:
            return OspfStatus(
                configured=False,
                version=version,
                router_id=None,
                collected_at=datetime.now(UTC),
            )

        def _status(neighbors: list[OspfNeighborStatus], error: str | None) -> OspfStatus:
            return OspfStatus(
                configured=True,
                version=version,
                router_id=router_id,
                neighbors=neighbors,
                total_neighbors=len(neighbors),
                full_neighbors=sum(1 for neighbor in neighbors if neighbor.established),
                collected_at=datetime.now(UTC),
                error=error,
            )

        try:
            output = await self._driver.show(OSPF_SHOW_NEIGHBORS[version])
        except VyosCommandError as exc:
            message = str(exc)
            if isinstance(exc, VyosPathNotFound) or _looks_not_running(message):
                return _status(
                    [],
                    message
                    or (
                        f"{OSPF_VERSION_LABELS[version]} is configured but the routing "
                        "daemon is not running"
                    ),
                )
            raise

        neighbors = parse_ospf_neighbors(output)
        error: str | None = None
        if not neighbors and _looks_not_running(output):
            error = output.strip() or (
                f"{OSPF_VERSION_LABELS[version]} is configured but the routing "
                "daemon is not running"
            )
        return _status(neighbors, error)


__all__ = [
    "OSPF_ROOTS",
    "OSPF_SHOW_NEIGHBORS",
    "OspfAreaExistsError",
    "OspfAreaInUseError",
    "OspfAreaNotFoundError",
    "OspfAreaReferenceError",
    "OspfConflictError",
    "OspfError",
    "OspfInterfaceExistsError",
    "OspfInterfaceNotFoundError",
    "OspfNotFoundError",
    "OspfRedistributeExistsError",
    "OspfRedistributeNotFoundError",
    "OspfRouteMapNotFoundError",
    "OspfService",
    "OspfValidationError",
    "build_area_create_ops",
    "build_area_delete_ops",
    "build_area_update_ops",
    "build_global_update_ops",
    "build_interface_create_ops",
    "build_interface_delete_ops",
    "build_interface_update_ops",
    "build_redistribute_create_ops",
    "build_redistribute_delete_ops",
    "build_redistribute_update_ops",
    "parse_area",
    "parse_global",
    "parse_interface",
    "parse_ospf_config",
    "parse_ospf_neighbors",
    "parse_redistribution",
]
