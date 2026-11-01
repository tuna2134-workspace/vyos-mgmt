"""BGP domain service: VyOS configuration <-> API DTOs plus atomic write plans."""

from __future__ import annotations

import uuid
from typing import Any

from vyos_mgmt.db.models import Router
from vyos_mgmt.schemas.bgp import (
    SUPPORTED_ADDRESS_FAMILIES,
    AddressFamilySettings,
    BgpConfigRead,
    BgpGlobalRead,
    BgpGlobalUpdate,
    BgpNeighborCreate,
    BgpNeighborRead,
    BgpNeighborUpdate,
    BgpNetworkCreate,
    BgpNetworkRead,
    BgpPeerGroupCreate,
    BgpPeerGroupRead,
    BgpPeerGroupUpdate,
    BgpRouterRef,
    BgpStatus,
    BgpTimers,
)
from vyos_mgmt.schemas.route_map import validate_route_map_name
from vyos_mgmt.services.vyos.base import ConfigOp, VyosDriver, VyosPathNotFound

BGP_ROOT = ["protocols", "bgp"]


class BgpServiceError(Exception):
    pass


class BgpConflictError(BgpServiceError):
    pass


class BgpNotFoundError(BgpServiceError):
    pass


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _present(node: Any, key: str) -> bool:
    return isinstance(node, dict) and key in node


def _leaf_text(value: Any) -> str | None:
    """Return a VyOS leaf value, accepting a single-key dict representation."""

    if isinstance(value, str):
        return value
    if isinstance(value, dict) and len(value) == 1:
        key, child = next(iter(value.items()))
        if child == {}:
            return str(key)
    return None


def _route_map_name(value: Any) -> str | None:
    """Read a route-map reference, ignoring values that fail API validation."""

    text = _leaf_text(value)
    if not text:
        return None
    try:
        return validate_route_map_name(text)
    except ValueError:
        return None


def _af_settings(raw_af: Any) -> AddressFamilySettings:
    raw_af = _dict(raw_af)
    allowas = raw_af.get("allowas-in")
    allowas_number: int | None = None
    if isinstance(allowas, dict):
        allowas_number = _as_int(allowas.get("number"))
    elif allowas is not None:
        allowas_number = _as_int(allowas)
    if allowas_number is not None and not 1 <= allowas_number <= 10:
        allowas_number = None

    route_map = _dict(raw_af.get("route-map"))
    return AddressFamilySettings(
        route_reflector_client=_present(raw_af, "route-reflector-client"),
        next_hop_self=_present(raw_af, "next-hop-self"),
        soft_reconfiguration_inbound=_present(_dict(raw_af.get("soft-reconfiguration")), "inbound"),
        default_originate=_present(raw_af, "default-originate"),
        allowas_in=allowas_number,
        route_map_import=_route_map_name(route_map.get("import")),
        route_map_export=_route_map_name(route_map.get("export")),
    )


def _parse_timers(raw: Any) -> BgpTimers | None:
    raw = _dict(raw)
    keepalive = _as_int(raw.get("keepalive"))
    holdtime = _as_int(raw.get("holdtime"))
    if keepalive is None or holdtime is None or holdtime <= keepalive:
        return None
    try:
        return BgpTimers(keepalive=keepalive, holdtime=holdtime)
    except ValueError:
        return None


def _parse_local_as(raw: Any) -> int | None:
    if isinstance(raw, dict):
        return _as_int(raw.get("as"))
    return _as_int(raw)


def _parse_address_families(raw: Any) -> dict[str, AddressFamilySettings]:
    raw = _dict(raw)
    families: dict[str, AddressFamilySettings] = {}
    for af in SUPPORTED_ADDRESS_FAMILIES:
        if af in raw:
            families[af] = _af_settings(raw.get(af))
    return families


def _parse_neighbor(address: str, raw: Any) -> BgpNeighborRead:
    raw = _dict(raw)
    return BgpNeighborRead(
        address=address,
        remote_as=_as_int(raw.get("remote-as")),
        description=raw.get("description") if isinstance(raw.get("description"), str) else None,
        peer_group=raw.get("peer-group") if isinstance(raw.get("peer-group"), str) else None,
        update_source=(
            raw.get("update-source") if isinstance(raw.get("update-source"), str) else None
        ),
        ebgp_multihop=_as_int(raw.get("ebgp-multihop")),
        password_configured=_present(raw, "password") and bool(raw.get("password")),
        passive=_present(raw, "passive"),
        shutdown=_present(raw, "shutdown"),
        timers=_parse_timers(raw.get("timers")),
        local_as=_parse_local_as(raw.get("local-as")),
        address_families=_parse_address_families(raw.get("address-family")),
    )


def _parse_peer_group(name: str, raw: Any) -> BgpPeerGroupRead:
    raw = _dict(raw)
    return BgpPeerGroupRead(
        name=name,
        remote_as=_as_int(raw.get("remote-as")),
        description=raw.get("description") if isinstance(raw.get("description"), str) else None,
        update_source=(
            raw.get("update-source") if isinstance(raw.get("update-source"), str) else None
        ),
        ebgp_multihop=_as_int(raw.get("ebgp-multihop")),
        password_configured=_present(raw, "password") and bool(raw.get("password")),
        address_families=_parse_address_families(raw.get("address-family")),
    )


def _network_keys(raw: Any) -> list[str]:
    if isinstance(raw, dict):
        return sorted(str(key) for key in raw)
    if isinstance(raw, list):
        return sorted(str(item) for item in raw)
    if isinstance(raw, str):
        return [raw]
    return []


def parse_bgp_config(router_id: uuid.UUID, router_name: str, raw: dict[str, Any]) -> BgpConfigRead:
    raw = _dict(raw)
    parameters = _dict(raw.get("parameters"))
    global_config = BgpGlobalRead(
        configured=bool(raw),
        system_as=_as_int(raw.get("system-as")),
        router_id=(
            parameters.get("router-id") if isinstance(parameters.get("router-id"), str) else None
        ),
        log_neighbor_changes=_present(parameters, "log-neighbor-changes"),
    )

    neighbors = [
        _parse_neighbor(address, neighbor)
        for address, neighbor in sorted(_dict(raw.get("neighbor")).items())
    ]
    peer_groups = [
        _parse_peer_group(name, group)
        for name, group in sorted(_dict(raw.get("peer-group")).items())
    ]

    networks: list[BgpNetworkRead] = []
    address_families = _dict(raw.get("address-family"))
    for af in SUPPORTED_ADDRESS_FAMILIES:
        af_node = _dict(address_families.get(af))
        for prefix in _network_keys(af_node.get("network")):
            networks.append(BgpNetworkRead(af=af, prefix=prefix))

    return BgpConfigRead(
        router=BgpRouterRef(id=router_id, name=router_name),
        configured=bool(raw),
        global_config=global_config,
        neighbors=neighbors,
        peer_groups=peer_groups,
        networks=networks,
    )


def _set(path: list[str]) -> ConfigOp:
    return ConfigOp("set", path)


def _delete(path: list[str]) -> ConfigOp:
    return ConfigOp("delete", path)


def _delete_if_present(ops: list[ConfigOp], base: list[str], node: Any, key: str) -> None:
    if _present(node, key):
        ops.append(_delete([*base, key]))


def _set_or_delete(
    ops: list[ConfigOp],
    base: list[str],
    node: Any,
    key: str,
    value: str | None,
) -> None:
    if value:
        ops.append(_set([*base, key, value]))
    else:
        _delete_if_present(ops, base, node, key)


def _sync_address_families(
    ops: list[ConfigOp],
    base: list[str],
    desired: dict[str, AddressFamilySettings],
    existing: Any,
) -> None:
    existing = _dict(existing)
    desired_keys = set(desired)
    for af in existing:
        if af in SUPPORTED_ADDRESS_FAMILIES and af not in desired_keys:
            ops.append(_delete([*base, "address-family", af]))

    for af, settings in desired.items():
        af_base = [*base, "address-family", af]
        existing_af = _dict(existing.get(af))
        ops.append(_set(af_base))

        flag_paths = {
            "route_reflector_client": ["route-reflector-client"],
            "next_hop_self": ["next-hop-self"],
            "soft_reconfiguration_inbound": ["soft-reconfiguration", "inbound"],
            "default_originate": ["default-originate"],
        }
        for field, tail in flag_paths.items():
            enabled = bool(getattr(settings, field))
            present = _present(existing_af, tail[0])
            if len(tail) > 1:
                present = present and _present(_dict(existing_af.get(tail[0])), tail[1])
            if enabled:
                ops.append(_set(af_base + tail))
            elif present:
                ops.append(_delete(af_base + tail))

        if settings.allowas_in:
            ops.append(_set([*af_base, "allowas-in", "number", str(settings.allowas_in)]))
        elif _present(existing_af, "allowas-in"):
            ops.append(_delete([*af_base, "allowas-in"]))

        existing_route_map = _dict(existing_af.get("route-map"))
        for field, direction in (
            ("route_map_import", "import"),
            ("route_map_export", "export"),
        ):
            desired = getattr(settings, field)
            current = _leaf_text(existing_route_map.get(direction))
            if desired:
                if current != desired:
                    ops.append(_set([*af_base, "route-map", direction, desired]))
            elif _present(existing_route_map, direction):
                ops.append(_delete([*af_base, "route-map", direction]))


def build_global_ops(payload: BgpGlobalUpdate, existing: dict[str, Any]) -> list[ConfigOp]:
    base = BGP_ROOT
    parameters = _dict(existing.get("parameters"))
    ops: list[ConfigOp] = [_set([*base, "system-as", str(payload.system_as)])]

    if payload.router_id:
        ops.append(_set([*base, "parameters", "router-id", payload.router_id]))
    else:
        _delete_if_present(ops, [*base, "parameters"], parameters, "router-id")

    if payload.log_neighbor_changes:
        if not _present(parameters, "log-neighbor-changes"):
            ops.append(_set([*base, "parameters", "log-neighbor-changes"]))
    else:
        _delete_if_present(ops, [*base, "parameters"], parameters, "log-neighbor-changes")
    return ops


def _neighbor_base(address: str) -> list[str]:
    return [*BGP_ROOT, "neighbor", address]


def build_neighbor_create_ops(payload: BgpNeighborCreate) -> list[ConfigOp]:
    base = _neighbor_base(payload.address)
    ops: list[ConfigOp] = [_set([*base, "remote-as", str(payload.remote_as)])]

    _set_or_delete(ops, base, {}, "description", payload.description)
    _set_or_delete(ops, base, {}, "peer-group", payload.peer_group)
    _set_or_delete(ops, base, {}, "update-source", payload.update_source)
    if payload.ebgp_multihop is not None:
        ops.append(_set([*base, "ebgp-multihop", str(payload.ebgp_multihop)]))
    if payload.password:
        ops.append(_set([*base, "password", payload.password]))
    if payload.passive:
        ops.append(_set([*base, "passive"]))
    if payload.shutdown:
        ops.append(_set([*base, "shutdown"]))
    if payload.timers:
        ops.append(_set([*base, "timers", "keepalive", str(payload.timers.keepalive)]))
        ops.append(_set([*base, "timers", "holdtime", str(payload.timers.holdtime)]))
    if payload.local_as:
        ops.append(_set([*base, "local-as", str(payload.local_as)]))
    _sync_address_families(ops, base, payload.address_families, {})
    return ops


def neighbor_update_ops(
    address: str, payload: BgpNeighborUpdate, existing: dict[str, Any]
) -> list[ConfigOp]:
    base = _neighbor_base(address)
    existing = _dict(existing)
    fields = payload.model_fields_set
    ops: list[ConfigOp] = []

    if "remote_as" in fields and payload.remote_as is not None:
        ops.append(_set([*base, "remote-as", str(payload.remote_as)]))
    if "description" in fields:
        _set_or_delete(ops, base, existing, "description", payload.description)
    if "peer_group" in fields:
        _set_or_delete(ops, base, existing, "peer-group", payload.peer_group)
    if "update_source" in fields:
        _set_or_delete(ops, base, existing, "update-source", payload.update_source)
    if "ebgp_multihop" in fields:
        if payload.ebgp_multihop is not None:
            ops.append(_set([*base, "ebgp-multihop", str(payload.ebgp_multihop)]))
        else:
            _delete_if_present(ops, base, existing, "ebgp-multihop")
    if "password" in fields:
        if payload.password:
            ops.append(_set([*base, "password", payload.password]))
        else:
            _delete_if_present(ops, base, existing, "password")
    if "passive" in fields and payload.passive is not None:
        if payload.passive:
            ops.append(_set([*base, "passive"]))
        else:
            _delete_if_present(ops, base, existing, "passive")
    if "shutdown" in fields and payload.shutdown is not None:
        if payload.shutdown:
            ops.append(_set([*base, "shutdown"]))
        else:
            _delete_if_present(ops, base, existing, "shutdown")
    if "timers" in fields:
        if payload.timers:
            ops.append(_set([*base, "timers", "keepalive", str(payload.timers.keepalive)]))
            ops.append(_set([*base, "timers", "holdtime", str(payload.timers.holdtime)]))
        else:
            _delete_if_present(ops, base, existing, "timers")
    if "local_as" in fields:
        if payload.local_as is not None:
            ops.append(_set([*base, "local-as", str(payload.local_as)]))
        else:
            _delete_if_present(ops, base, existing, "local-as")
    if "address_families" in fields and payload.address_families is not None:
        _sync_address_families(ops, base, payload.address_families, existing.get("address-family"))
    return ops


def _peer_group_base(name: str) -> list[str]:
    return [*BGP_ROOT, "peer-group", name]


def build_peer_group_create_ops(payload: BgpPeerGroupCreate) -> list[ConfigOp]:
    base = _peer_group_base(payload.name)
    ops: list[ConfigOp] = [_set([*base, "remote-as", str(payload.remote_as)])]
    _set_or_delete(ops, base, {}, "description", payload.description)
    _set_or_delete(ops, base, {}, "update-source", payload.update_source)
    if payload.ebgp_multihop is not None:
        ops.append(_set([*base, "ebgp-multihop", str(payload.ebgp_multihop)]))
    if payload.password:
        ops.append(_set([*base, "password", payload.password]))
    _sync_address_families(ops, base, payload.address_families, {})
    return ops


def peer_group_update_ops(
    name: str, payload: BgpPeerGroupUpdate, existing: dict[str, Any]
) -> list[ConfigOp]:
    base = _peer_group_base(name)
    existing = _dict(existing)
    fields = payload.model_fields_set
    ops: list[ConfigOp] = []

    if "remote_as" in fields and payload.remote_as is not None:
        ops.append(_set([*base, "remote-as", str(payload.remote_as)]))
    if "description" in fields:
        _set_or_delete(ops, base, existing, "description", payload.description)
    if "update_source" in fields:
        _set_or_delete(ops, base, existing, "update-source", payload.update_source)
    if "ebgp_multihop" in fields:
        if payload.ebgp_multihop is not None:
            ops.append(_set([*base, "ebgp-multihop", str(payload.ebgp_multihop)]))
        else:
            _delete_if_present(ops, base, existing, "ebgp-multihop")
    if "password" in fields:
        if payload.password:
            ops.append(_set([*base, "password", payload.password]))
        else:
            _delete_if_present(ops, base, existing, "password")
    if "address_families" in fields and payload.address_families is not None:
        _sync_address_families(ops, base, payload.address_families, existing.get("address-family"))
    return ops


class BgpService:
    def __init__(self, driver: VyosDriver, router: Router) -> None:
        self._driver = driver
        self._router = router

    async def _raw_config(self) -> dict[str, Any]:
        try:
            raw = await self._driver.get_config(BGP_ROOT)
        except VyosPathNotFound:
            return {}
        return _dict(raw)

    def _parse(self, raw: dict[str, Any]) -> BgpConfigRead:
        return parse_bgp_config(self._router.id, self._router.name, raw)

    async def get_config(self) -> BgpConfigRead:
        return self._parse(await self._raw_config())

    async def get_status(self) -> BgpStatus:
        raw = await self._raw_config()
        if not raw:
            return BgpStatus(configured=False, error="BGP is not configured on this router")

        status = await self._driver.get_bgp_status()
        parameters = _dict(raw.get("parameters"))
        if status.router_id is None and isinstance(parameters.get("router-id"), str):
            status.router_id = parameters["router-id"]
        if status.local_as is None:
            status.local_as = _as_int(raw.get("system-as"))
        status.configured = True
        return status

    async def update_global(self, payload: BgpGlobalUpdate) -> BgpConfigRead:
        raw = await self._raw_config()
        ops = build_global_ops(payload, raw)
        await self._driver.apply(ops)
        return self._parse(await self._raw_config())

    async def delete_bgp(self) -> None:
        try:
            await self._driver.apply([_delete(BGP_ROOT)])
        except VyosPathNotFound:
            # Already absent: DELETE is idempotent.
            return

    async def create_neighbor(self, payload: BgpNeighborCreate) -> BgpConfigRead:
        raw = await self._raw_config()
        neighbors = _dict(raw.get("neighbor"))
        if payload.address in neighbors:
            raise BgpConflictError(f"Neighbor {payload.address} already exists")
        await self._driver.apply(build_neighbor_create_ops(payload))
        return self._parse(await self._raw_config())

    async def update_neighbor(self, address: str, payload: BgpNeighborUpdate) -> BgpConfigRead:
        raw = await self._raw_config()
        neighbors = _dict(raw.get("neighbor"))
        if address not in neighbors:
            raise BgpNotFoundError(f"Neighbor {address} does not exist")
        ops = neighbor_update_ops(address, payload, _dict(neighbors[address]))
        if ops:
            await self._driver.apply(ops)
        return self._parse(await self._raw_config())

    async def delete_neighbor(self, address: str) -> BgpConfigRead:
        raw = await self._raw_config()
        if address not in _dict(raw.get("neighbor")):
            raise BgpNotFoundError(f"Neighbor {address} does not exist")
        await self._driver.apply([_delete(_neighbor_base(address))])
        return self._parse(await self._raw_config())

    async def add_network(self, payload: BgpNetworkCreate) -> BgpConfigRead:
        raw = await self._raw_config()
        address_families = _dict(raw.get("address-family"))
        networks = _dict(_dict(address_families.get(payload.af)).get("network"))
        if payload.prefix in networks:
            raise BgpConflictError(f"Network {payload.prefix} is already advertised")
        path = [*BGP_ROOT, "address-family", payload.af, "network", payload.prefix]
        await self._driver.apply([_set(path)])
        return self._parse(await self._raw_config())

    async def delete_network(self, af: str, prefix: str) -> BgpConfigRead:
        raw = await self._raw_config()
        address_families = _dict(raw.get("address-family"))
        networks = _dict(_dict(address_families.get(af)).get("network"))
        if prefix not in networks:
            raise BgpNotFoundError(f"Network {prefix} is not advertised in {af}")
        path = [*BGP_ROOT, "address-family", af, "network", prefix]
        await self._driver.apply([_delete(path)])
        return self._parse(await self._raw_config())

    async def create_peer_group(self, payload: BgpPeerGroupCreate) -> BgpConfigRead:
        raw = await self._raw_config()
        if payload.name in _dict(raw.get("peer-group")):
            raise BgpConflictError(f"Peer group {payload.name} already exists")
        await self._driver.apply(build_peer_group_create_ops(payload))
        return self._parse(await self._raw_config())

    async def update_peer_group(self, name: str, payload: BgpPeerGroupUpdate) -> BgpConfigRead:
        raw = await self._raw_config()
        groups = _dict(raw.get("peer-group"))
        if name not in groups:
            raise BgpNotFoundError(f"Peer group {name} does not exist")
        ops = peer_group_update_ops(name, payload, _dict(groups[name]))
        if ops:
            await self._driver.apply(ops)
        return self._parse(await self._raw_config())

    async def delete_peer_group(self, name: str) -> BgpConfigRead:
        raw = await self._raw_config()
        if name not in _dict(raw.get("peer-group")):
            raise BgpNotFoundError(f"Peer group {name} does not exist")
        await self._driver.apply([_delete(_peer_group_base(name))])
        return self._parse(await self._raw_config())
