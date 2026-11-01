"""Route-map domain service: VyOS ``policy route-map`` <-> API DTOs.

The service deliberately uses one atomic driver batch per mutation.  Rule
updates are *field syncs*: only the managed leaves/containers that actually
changed are touched, so unsupported VyOS directives on the same rule survive an
API update.  Reads tolerate the small representation differences between VyOS
versions (scalars, lists and dict-keyed multi-value leaves) and ignore values
that would not pass API validation rather than failing the whole listing.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from vyos_mgmt.db.models import Router
from vyos_mgmt.schemas.route_map import (
    CommunityAction,
    RouteMapCreate,
    RouteMapList,
    RouteMapMatch,
    RouteMapRead,
    RouteMapRuleCreate,
    RouteMapRuleRead,
    RouteMapRuleUpdate,
    RouteMapSet,
    RouteMapUpdate,
    validate_community_value,
    validate_metric,
    validate_route_map_name,
)
from vyos_mgmt.services.vyos.base import ConfigOp, VyosDriver, VyosPathNotFound

ROUTE_MAP_ROOT = ["policy", "route-map"]
BGP_ROOT = ["protocols", "bgp"]
OSPF_ROOTS = {"v2": ["protocols", "ospf"], "v3": ["protocols", "ospfv3"]}
PREFIX_LIST_ROOTS = {
    "ipv4": ["policy", "prefix-list"],
    "ipv6": ["policy", "prefix-list6"],
}

_ORIGINS = frozenset({"igp", "egp", "incomplete"})
_PROTOCOLS = frozenset(
    {
        "babel",
        "bgp",
        "connected",
        "isis",
        "kernel",
        "ospf",
        "ospfv3",
        "rip",
        "ripng",
        "static",
        "table",
        "vnc",
    }
)
_RPKI_STATES = frozenset({"invalid", "notfound", "valid"})
_METRIC_TYPES = frozenset({"type-1", "type-2"})
_COMMUNITY_SUBKEYS = ("add", "replace", "delete", "none")

# Managed leaf locations.  Values are paths relative to the rule's ``match`` /
# ``set`` node; the final path component is the VyOS leaf key.
MATCH_LEAF_PATHS: dict[str, list[str]] = {
    "ipv4_prefix_list": ["ip", "address", "prefix-list"],
    "ipv6_prefix_list": ["ipv6", "address", "prefix-list"],
    "as_path": ["as-path"],
    "community_list": ["community", "community-list"],
    "large_community_list": ["large-community", "large-community-list"],
    "extcommunity": ["extcommunity"],
    "metric": ["metric"],
    "local_preference": ["local-preference"],
    "origin": ["origin"],
    "tag": ["tag"],
    "protocol": ["protocol"],
    "rpki": ["rpki"],
    "ip_nexthop": ["ip", "nexthop", "address"],
    "ipv6_nexthop": ["ipv6", "nexthop", "address"],
    "interface": ["interface"],
}

SET_LEAF_PATHS: dict[str, list[str]] = {
    "local_preference": ["local-preference"],
    "metric": ["metric"],
    "origin": ["origin"],
    "weight": ["weight"],
    "metric_type": ["metric-type"],
    "tag": ["tag"],
    "ip_next_hop": ["ip-next-hop"],
    "originator_id": ["originator-id"],
}


class RouteMapError(Exception):
    """Base class for route-map domain failures."""


class RouteMapConflictError(RouteMapError):
    """A route map or rule with the requested identifier already exists."""


class RouteMapExistsError(RouteMapConflictError):
    pass


class RouteMapRuleExistsError(RouteMapConflictError):
    pass


class RouteMapNotFoundError(RouteMapError):
    pass


class RouteMapRuleNotFoundError(RouteMapError):
    pass


class RouteMapInUseError(RouteMapError):
    """Deletion was refused because the route map is referenced elsewhere."""

    def __init__(self, message: str, *, used_by: list[str]) -> None:
        super().__init__(message)
        self.used_by = used_by


class RouteMapValidationError(RouteMapError):
    """A semantic validation error that Pydantic cannot express on its own."""

    def __init__(self, message: str, *, field: str = "goto_rule", value: Any = None) -> None:
        super().__init__(message)
        self.field = field
        self.value = value


class RouteMapPrefixListNotFoundError(RouteMapValidationError):
    """A ``match`` prefix-list reference does not exist on the device.

    VyOS verifies these references at commit time, so the API rejects the write
    with ``422 prefix_list_not_found`` instead of producing a failing commit.
    """

    def __init__(self, message: str, *, field: str, value: str, family: str) -> None:
        super().__init__(message, field=field, value=value)
        self.family = family


# ---------------------------------------------------------------------------
# Config-tree helpers
# ---------------------------------------------------------------------------


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _present(node: Any, key: str) -> bool:
    return isinstance(node, dict) and key in node


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _scalar(value: Any) -> str | None:
    """Return a vyos leaf value.

    Normal devices return strings.  Some tooling returns single-key dicts for
    value nodes; accept those too, but never mistake a multi-key container for a
    scalar.
    """

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


def _leaf_values(value: Any) -> list[str]:
    """Parse a VyOS multi-value leaf (dict-keyed, list or scalar)."""

    if value is None:
        return []
    if isinstance(value, dict):
        return [str(key) for key in value]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            if isinstance(item, dict):
                values.extend(str(key) for key in item)
            elif item is not None:
                values.append(str(item))
        return values
    if isinstance(value, str):
        return [value] if value else []
    return [str(value)]


def _dig(node: Any, path: list[str]) -> Any:
    cursor: Any = node
    for part in path:
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor


def _dig_present(node: Any, path: list[str]) -> bool:
    cursor: Any = node
    for part in path:
        if not isinstance(cursor, dict) or part not in cursor:
            return False
        cursor = cursor[part]
    return True


def _enum(value: Any, allowed: frozenset[str] | set[str]) -> str | None:
    candidate = _scalar(value)
    return candidate if candidate in allowed else None


def _safe_community_values(value: Any) -> list[str]:
    values: list[str] = []
    for item in _leaf_values(value):
        try:
            values.append(validate_community_value(item))
        except ValueError:
            continue
    return values


def _valid_asns(value: Any) -> list[int]:
    asns: list[int] = []
    for item in _leaf_values(value):
        asn = _as_int(item)
        if asn is not None and 1 <= asn <= 4_294_967_295:
            asns.append(asn)
    return asns


def _sorted_rule_items(raw: Any) -> list[tuple[int, dict[str, Any]]]:
    items: list[tuple[int, dict[str, Any]]] = []
    for key, value in _dict(raw).items():
        number = _as_int(key)
        if number is None or not 1 <= number <= 65_535:
            continue
        items.append((number, _dict(value)))
    return sorted(items, key=lambda item: item[0])


def _parse_on_match(raw: dict[str, Any]) -> tuple[str | None, int | None]:
    node = _dict(raw.get("on-match"))
    if _present(node, "next") or _scalar(raw.get("on-match")) == "next":
        return "next", None
    goto = _as_int(node.get("goto"))
    if goto is not None and 1 <= goto <= 65_535:
        return "goto", goto
    return None, None


def _parse_match(raw: Any) -> RouteMapMatch:
    match = _dict(raw)
    ip = _dict(match.get("ip"))
    ipv6 = _dict(match.get("ipv6"))
    community = _dict(match.get("community"))
    large_community = _dict(match.get("large-community"))
    nexthop_address = _scalar(_dict(ip.get("nexthop")).get("address"))
    return RouteMapMatch(
        ipv4_prefix_list=_scalar(_dict(ip.get("address")).get("prefix-list")),
        ipv6_prefix_list=_scalar(_dict(ipv6.get("address")).get("prefix-list")),
        as_path=_scalar(match.get("as-path")),
        community_list=_scalar(community.get("community-list")),
        community_exact_match=_present(community, "exact-match"),
        large_community_list=_scalar(large_community.get("large-community-list")),
        extcommunity=_scalar(match.get("extcommunity")),
        metric=_as_int(match.get("metric")),
        local_preference=_as_int(match.get("local-preference")),
        origin=_enum(match.get("origin"), _ORIGINS),
        tag=_as_int(match.get("tag")),
        protocol=_enum(match.get("protocol"), _PROTOCOLS),
        rpki=_enum(match.get("rpki"), _RPKI_STATES),
        ip_nexthop=nexthop_address or _scalar(ip.get("nexthop")),
        ipv6_nexthop=(
            _scalar(_dict(ipv6.get("nexthop")).get("address")) or _scalar(ipv6.get("nexthop"))
        ),
        interface=_scalar(match.get("interface")),
    )


def _parse_community(raw: Any) -> tuple[CommunityAction | None, list[str], str | None]:
    community = _dict(raw)
    if _present(community, "add"):
        return "add", _safe_community_values(community.get("add")), None
    if _present(community, "replace"):
        return "replace", _safe_community_values(community.get("replace")), None
    if _present(community, "delete"):
        return "delete", [], _scalar(community.get("delete"))
    if _present(community, "none"):
        return "none", [], None
    return None, [], None


def _parse_set(raw: Any) -> RouteMapSet:
    node = _dict(raw)
    action, values, delete = _parse_community(node.get("community"))
    metric = _scalar(node.get("metric"))
    if metric is not None:
        try:
            metric = validate_metric(metric)
        except ValueError:
            metric = None
    return RouteMapSet(
        local_preference=_as_int(node.get("local-preference")),
        metric=metric,
        origin=_enum(node.get("origin"), _ORIGINS),
        weight=_as_int(node.get("weight")),
        metric_type=_enum(node.get("metric-type"), _METRIC_TYPES),
        tag=_as_int(node.get("tag")),
        as_path_prepend=_valid_asns(_dict(node.get("as-path")).get("prepend")),
        community_action=action,
        community_values=values,
        community_delete=delete,
        ip_next_hop=_scalar(node.get("ip-next-hop")),
        originator_id=_scalar(node.get("originator-id")),
    )


def _parse_rule(number: int, raw: Any) -> RouteMapRuleRead | None:
    rule = _dict(raw)
    action = rule.get("action")
    if action not in {"permit", "deny"}:
        # ``action`` is mandatory in VyOS; an incomplete rule cannot be
        # represented by the contract, so omit it from the read model.
        return None
    on_match, goto_rule = _parse_on_match(rule)
    if on_match == "goto" and goto_rule == number:
        # Malformed device config; keep the rule visible without the loop.
        on_match, goto_rule = None, None
    call = _scalar(rule.get("call"))
    if call is not None:
        try:
            call = validate_route_map_name(call)
        except ValueError:
            call = None
    candidate = {
        "number": number,
        "action": action,
        "description": _scalar(rule.get("description")),
        "match": _parse_match(rule.get("match")),
        "set": _parse_set(rule.get("set")),
        "on_match": on_match,
        "goto_rule": goto_rule,
        "call": call,
        "continue_rule": _as_int(rule.get("continue")),
    }
    try:
        return RouteMapRuleRead.model_validate(candidate)
    except ValidationError:
        return None


def parse_route_map(name: str, raw: Any) -> RouteMapRead:
    """Parse one ``policy route-map <name>`` node into a read model."""

    node = _dict(raw)
    rules = [
        rule
        for number, rule_raw in _sorted_rule_items(node.get("rule"))
        if (rule := _parse_rule(number, rule_raw)) is not None
    ]
    description = node.get("description")
    return RouteMapRead(
        name=name,
        description=description if isinstance(description, str) else None,
        rules=rules,
    )


def parse_route_maps(raw: Any) -> list[RouteMapRead]:
    """Parse the ``policy route-map`` tree, sorted by route-map name."""

    return [parse_route_map(name, value) for name, value in sorted(_dict(raw).items())]


def _usage_label(path: list[str]) -> str:
    """Render a BGP reference path as a short, readable label."""

    parts = list(path[2:]) if path[:2] == ["protocols", "bgp"] else list(path)
    parts = [part for part in parts if part != "route-map"]

    if parts[:1] == ["neighbor"] and "address-family" in parts:
        index = parts.index("address-family")
        address = parts[1] if len(parts) > 1 else "?"
        af = parts[index + 1] if len(parts) > index + 1 else "?"
        tail = parts[index + 2 :]
        suffix = f" · {' '.join(tail)}" if tail else ""
        return f"BGP neighbor {address} · {af}{suffix}"

    if parts[:1] == ["peer-group"] and "address-family" in parts:
        index = parts.index("address-family")
        name = parts[1] if len(parts) > 1 else "?"
        af = parts[index + 1] if len(parts) > index + 1 else "?"
        tail = parts[index + 2 :]
        suffix = f" · {' '.join(tail)}" if tail else ""
        return f"BGP peer-group {name} · {af}{suffix}"

    if parts[:1] == ["address-family"]:
        af = parts[1] if len(parts) > 1 else "?"
        for kind, label in (
            ("network", "network"),
            ("aggregate-address", "aggregate"),
            ("redistribute", "redistribute"),
        ):
            if kind in parts:
                index = parts.index(kind)
                value = parts[index + 1] if len(parts) > index + 1 else "?"
                return f"BGP {label} {value} · {af}"

    return "BGP " + " ".join(parts).replace("address-family", "AF")


def _collect_ospf_usage(raw: dict[str, Any], version: str) -> dict[str, set[str]]:
    """Return route-map references from OSPF/OSPFv3 redistribution."""

    usage: dict[str, set[str]] = {}
    for source, rule_raw in sorted(_dict(_dict(raw).get("redistribute")).items()):
        name = _scalar(_dict(rule_raw).get("route-map"))
        if name:
            label = f"OSPFv{version[1]} redistribute {source} · route-map"
            usage.setdefault(name, set()).add(label)
    return usage


def collect_route_map_usage(
    bgp_raw: dict[str, Any],
    route_maps_raw: dict[str, Any],
    *,
    ospf_raw: dict[str, Any] | None = None,
    ospfv3_raw: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Return ``route-map name -> sorted reference labels``.

    Every ``route-map`` node under ``protocols bgp`` is inspected generically,
    which covers neighbors, peer groups, networks, redistribute, aggregate and
    default-originate references (current and future BGP submodules).  Route-map
    ``call`` directives are also references because deleting a called map would
    break the caller.  OSPF/OSPFv3 ``redistribute <source> route-map``
    references are included so a map used by redistribution cannot be deleted.
    """

    usage: dict[str, set[str]] = {}

    def add(name: str | None, label: str) -> None:
        if name:
            usage.setdefault(name, set()).add(label)

    def walk(node: Any, path: list[str]) -> None:
        for key, value in _dict(node).items():
            key_path = [*path, str(key)]
            if key == "route-map":
                if isinstance(value, dict):
                    for direction, reference in value.items():
                        name = _scalar(reference)
                        add(name, _usage_label([*key_path, str(direction)]))
                elif isinstance(value, list):
                    for reference in value:
                        add(_scalar(reference), _usage_label(key_path))
                else:
                    add(_scalar(value), _usage_label(key_path))
            elif isinstance(value, dict):
                walk(value, key_path)

    walk(bgp_raw, ["protocols", "bgp"])

    for raw, version in ((ospf_raw, "v2"), (ospfv3_raw, "v3")):
        if raw is None:
            continue
        for name, labels in _collect_ospf_usage(raw, version).items():
            usage.setdefault(name, set()).update(labels)

    for map_name, map_raw in _dict(route_maps_raw).items():
        for number, rule_raw in _sorted_rule_items(_dict(map_raw).get("rule")):
            add(
                _scalar(rule_raw.get("call")),
                f"Route-map {map_name} rule {number} call",
            )

    return {name: sorted(labels) for name, labels in usage.items()}


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
    key_path: list[str],
    desired: str | None,
) -> None:
    current = _scalar(_dig(existing, key_path))
    if desired:
        if current != desired:
            ops.append(_set([*base, *key_path, desired]))
    elif _dig_present(existing, key_path):
        ops.append(_delete([*base, *key_path]))


def _sync_match(
    ops: list[ConfigOp],
    rule_base: list[str],
    desired: RouteMapMatch,
    existing: Any,
) -> None:
    base = [*rule_base, "match"]
    existing_match = _dict(existing)
    for field, key_path in MATCH_LEAF_PATHS.items():
        value = getattr(desired, field)
        _sync_leaf(
            ops,
            base,
            existing_match,
            key_path,
            None if value is None else str(value),
        )

    community = _dict(existing_match.get("community"))
    exact_present = _present(community, "exact-match")
    exact_path = [*base, "community", "exact-match"]
    if desired.community_exact_match and not exact_present:
        ops.append(_set(exact_path))
    elif not desired.community_exact_match and exact_present:
        ops.append(_delete(exact_path))


def _existing_community_state(raw: Any) -> tuple[str | None, tuple[str, ...], str | None]:
    action, values, delete = _parse_community(raw)
    if action in {"add", "replace"}:
        return action, tuple(sorted(values)), None
    return action, (), delete


def _desired_community_state(
    desired: RouteMapSet,
) -> tuple[str | None, tuple[str, ...], str | None]:
    action = desired.community_action
    if action in {"add", "replace"}:
        return action, tuple(sorted(desired.community_values)), None
    return action, (), desired.community_delete


def _sync_set(
    ops: list[ConfigOp],
    rule_base: list[str],
    desired: RouteMapSet,
    existing: Any,
) -> None:
    base = [*rule_base, "set"]
    existing_set = _dict(existing)
    for field, key_path in SET_LEAF_PATHS.items():
        value = getattr(desired, field)
        _sync_leaf(
            ops,
            base,
            existing_set,
            key_path,
            None if value is None else str(value),
        )

    existing_asns = _valid_asns(_dict(existing_set.get("as-path")).get("prepend"))
    if existing_asns != desired.as_path_prepend:
        if _dig_present(existing_set, ["as-path", "prepend"]):
            ops.append(_delete([*base, "as-path", "prepend"]))
        for asn in desired.as_path_prepend:
            ops.append(_set([*base, "as-path", "prepend", str(asn)]))

    existing_community = _existing_community_state(existing_set.get("community"))
    desired_community = _desired_community_state(desired)
    if existing_community != desired_community:
        existing_node = _dict(existing_set.get("community"))
        for subkey in _COMMUNITY_SUBKEYS:
            if _present(existing_node, subkey):
                ops.append(_delete([*base, "community", subkey]))
        action = desired.community_action
        if action in {"add", "replace"}:
            for value in desired.community_values:
                ops.append(_set([*base, "community", action, value]))
        elif action == "delete" and desired.community_delete:
            ops.append(_set([*base, "community", "delete", desired.community_delete]))
        elif action == "none":
            ops.append(_set([*base, "community", "none"]))


def _sync_rule_control(
    ops: list[ConfigOp],
    rule_base: list[str],
    desired: RouteMapRuleCreate | RouteMapRuleUpdate,
    existing: dict[str, Any],
) -> None:
    existing_on, existing_goto = _parse_on_match(existing)
    desired_on = desired.on_match
    desired_goto = desired.goto_rule if desired_on == "goto" else None
    if (existing_on, existing_goto) != (desired_on, desired_goto):
        # ``on-match`` has exactly two managed shapes (next presence and goto
        # scalar); rebuilding the subtree avoids leaving the old mode behind.
        if _present(existing, "on-match"):
            ops.append(_delete([*rule_base, "on-match"]))
        if desired_on == "next":
            ops.append(_set([*rule_base, "on-match", "next"]))
        elif desired_on == "goto" and desired_goto is not None:
            ops.append(_set([*rule_base, "on-match", "goto", str(desired_goto)]))

    _sync_leaf(ops, rule_base, existing, ["call"], desired.call)
    _sync_leaf(
        ops,
        rule_base,
        existing,
        ["continue"],
        None if desired.continue_rule is None else str(desired.continue_rule),
    )


def _rule_base(name: str, number: int) -> list[str]:
    return [*ROUTE_MAP_ROOT, name, "rule", str(number)]


def build_rule_create_ops(name: str, rule: RouteMapRuleCreate) -> list[ConfigOp]:
    base = _rule_base(name, rule.number)
    ops = [_set(base), _set([*base, "action", rule.action])]
    if rule.description:
        ops.append(_set([*base, "description", rule.description]))
    _sync_match(ops, base, rule.match, {})
    _sync_set(ops, base, rule.set, {})
    _sync_rule_control(ops, base, rule, {})
    return ops


def build_rule_update_ops(
    name: str,
    number: int,
    rule: RouteMapRuleUpdate,
    existing: dict[str, Any],
) -> list[ConfigOp]:
    base = _rule_base(name, number)
    ops: list[ConfigOp] = []

    current_action = _scalar(existing.get("action"))
    if current_action != rule.action:
        ops.append(_set([*base, "action", rule.action]))

    _sync_leaf(ops, base, existing, ["description"], rule.description)
    _sync_match(ops, base, rule.match, existing.get("match"))
    _sync_set(ops, base, rule.set, existing.get("set"))
    _sync_rule_control(ops, base, rule, existing)
    return ops


def build_rule_delete_ops(name: str, number: int) -> list[ConfigOp]:
    return [_delete(_rule_base(name, number))]


def build_map_create_ops(name: str, description: str | None) -> list[ConfigOp]:
    base = [*ROUTE_MAP_ROOT, name]
    ops = [_set(base)]
    if description:
        ops.append(_set([*base, "description", description]))
    return ops


def build_map_update_ops(
    name: str, description: str | None, existing: dict[str, Any]
) -> list[ConfigOp]:
    ops: list[ConfigOp] = []
    _sync_leaf(ops, [*ROUTE_MAP_ROOT, name], existing, ["description"], description)
    return ops


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class RouteMapService:
    def __init__(self, driver: VyosDriver, router: Router) -> None:
        self._driver = driver
        self._router = router

    async def _raw_route_maps(self) -> dict[str, Any]:
        try:
            raw = await self._driver.get_config(ROUTE_MAP_ROOT)
        except VyosPathNotFound:
            return {}
        return _dict(raw)

    async def _raw_bgp(self) -> dict[str, Any]:
        try:
            raw = await self._driver.get_config(BGP_ROOT)
        except VyosPathNotFound:
            return {}
        return _dict(raw)

    async def _raw_ospf(self, version: str) -> dict[str, Any]:
        try:
            raw = await self._driver.get_config(OSPF_ROOTS[version])
        except VyosPathNotFound:
            return {}
        return _dict(raw)

    async def _usage(self, route_maps_raw: dict[str, Any]) -> dict[str, list[str]]:
        return collect_route_map_usage(
            await self._raw_bgp(),
            route_maps_raw,
            ospf_raw=await self._raw_ospf("v2"),
            ospfv3_raw=await self._raw_ospf("v3"),
        )

    async def _prefix_list_names(self, family: str) -> set[str]:
        try:
            raw = await self._driver.get_config(PREFIX_LIST_ROOTS[family])
        except VyosPathNotFound:
            return set()
        return set(_dict(raw))

    async def _validate_rule_references(
        self, rule: RouteMapRuleCreate | RouteMapRuleUpdate
    ) -> None:
        """Reject references to prefix lists that do not exist.

        VyOS commit verification requires ``match ip[6] address prefix-list``
        targets to exist, so the API performs the same check (family-scoped).
        """

        checks = (
            ("ipv4_prefix_list", "ipv4", "IPv4"),
            ("ipv6_prefix_list", "ipv6", "IPv6"),
        )
        for attribute, family, label in checks:
            name = getattr(rule.match, attribute)
            if not name:
                continue
            names = await self._prefix_list_names(family)
            if name not in names:
                raise RouteMapPrefixListNotFoundError(
                    f"{label} prefix-list {name} does not exist; "
                    "create it before referencing it from a route map",
                    field=f"match.{attribute}",
                    value=name,
                    family=family,
                )

    @staticmethod
    def _with_usage(route_map: RouteMapRead, usage: dict[str, list[str]]) -> RouteMapRead:
        used_by = usage.get(route_map.name, [])
        return route_map.model_copy(update={"in_use": bool(used_by), "used_by": used_by})

    async def list(self) -> RouteMapList:
        raw = await self._raw_route_maps()
        usage = await self._usage(raw)
        items = [self._with_usage(item, usage) for item in parse_route_maps(raw)]
        return RouteMapList(items=items, total=len(items))

    async def get(self, name: str) -> RouteMapRead:
        raw = await self._raw_route_maps()
        if name not in raw:
            raise RouteMapNotFoundError(f"Route map {name} does not exist")
        usage = await self._usage(raw)
        return self._with_usage(parse_route_map(name, raw[name]), usage)

    async def create(self, payload: RouteMapCreate) -> RouteMapRead:
        raw = await self._raw_route_maps()
        if payload.name in raw:
            raise RouteMapExistsError(f"Route map {payload.name} already exists")
        await self._driver.apply(build_map_create_ops(payload.name, payload.description))
        return await self.get(payload.name)

    async def update(self, name: str, payload: RouteMapUpdate) -> RouteMapRead:
        raw = await self._raw_route_maps()
        if name not in raw:
            raise RouteMapNotFoundError(f"Route map {name} does not exist")
        ops = build_map_update_ops(name, payload.description, _dict(raw[name]))
        if ops:
            await self._driver.apply(ops)
        return await self.get(name)

    async def delete(self, name: str) -> None:
        raw = await self._raw_route_maps()
        if name not in raw:
            raise RouteMapNotFoundError(f"Route map {name} does not exist")
        usage = await self._usage(raw)
        used_by = usage.get(name, [])
        if used_by:
            raise RouteMapInUseError(
                f"Route map {name} is in use and cannot be deleted",
                used_by=used_by,
            )
        await self._driver.apply([_delete([*ROUTE_MAP_ROOT, name])])

    async def create_rule(self, name: str, payload: RouteMapRuleCreate) -> RouteMapRead:
        raw = await self._raw_route_maps()
        if name not in raw:
            raise RouteMapNotFoundError(f"Route map {name} does not exist")
        rules = _dict(_dict(raw[name]).get("rule"))
        if str(payload.number) in rules:
            raise RouteMapRuleExistsError(
                f"Rule {payload.number} already exists in route map {name}"
            )
        await self._validate_rule_references(payload)
        await self._driver.apply(build_rule_create_ops(name, payload))
        return await self.get(name)

    async def update_rule(
        self, name: str, number: int, payload: RouteMapRuleUpdate
    ) -> RouteMapRead:
        raw = await self._raw_route_maps()
        if name not in raw:
            raise RouteMapNotFoundError(f"Route map {name} does not exist")
        rules = _dict(_dict(raw[name]).get("rule"))
        existing = rules.get(str(number))
        if not isinstance(existing, dict):
            raise RouteMapRuleNotFoundError(f"Rule {number} does not exist in route map {name}")
        if payload.on_match == "goto" and payload.goto_rule == number:
            raise RouteMapValidationError(
                "goto_rule must differ from the rule number",
                field="goto_rule",
                value=payload.goto_rule,
            )
        await self._validate_rule_references(payload)
        ops = build_rule_update_ops(name, number, payload, existing)
        if ops:
            await self._driver.apply(ops)
        return await self.get(name)

    async def delete_rule(self, name: str, number: int) -> RouteMapRead:
        raw = await self._raw_route_maps()
        if name not in raw:
            raise RouteMapNotFoundError(f"Route map {name} does not exist")
        rules = _dict(_dict(raw[name]).get("rule"))
        if str(number) not in rules:
            raise RouteMapRuleNotFoundError(f"Rule {number} does not exist in route map {name}")
        await self._driver.apply(build_rule_delete_ops(name, number))
        return await self.get(name)
