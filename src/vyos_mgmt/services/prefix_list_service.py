"""Prefix-list domain service: VyOS ``policy prefix-list[6]`` <-> API DTOs.

IPv4 lists live under ``policy prefix-list`` and IPv6 lists under
``policy prefix-list6``; the API identifies an object by ``family`` + ``name``.
The service uses one atomic driver batch per mutation and updates are field
syncs, so unsupported VyOS directives on a rule survive an API update.

``in_use`` / ``used_by`` are derived from route-map match conditions and BGP
prefix-list filters.  Those references are not created by this API, but
deleting a referenced list would break the device commit, so deletion is
refused with the reference labels attached.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from pydantic import ValidationError

from vyos_mgmt.db.models import Router
from vyos_mgmt.schemas.prefix_list import (
    PrefixListCreate,
    PrefixListFamily,
    PrefixListList,
    PrefixListRead,
    PrefixListRuleCreate,
    PrefixListRuleRead,
    PrefixListRuleUpdate,
    PrefixListUpdate,
)
from vyos_mgmt.services.vyos.base import ConfigOp, VyosDriver, VyosPathNotFound

PREFIX_LIST_ROOTS: dict[PrefixListFamily, list[str]] = {
    "ipv4": ["policy", "prefix-list"],
    "ipv6": ["policy", "prefix-list6"],
}
FAMILY_LABELS: dict[PrefixListFamily, str] = {"ipv4": "IPv4", "ipv6": "IPv6"}
ROUTE_MAP_ROOT = ["policy", "route-map"]
BGP_ROOT = ["protocols", "bgp"]


class PrefixListError(Exception):
    """Base class for prefix-list domain failures."""


class PrefixListConflictError(PrefixListError):
    """A prefix list or rule with the requested identifier already exists."""


class PrefixListExistsError(PrefixListConflictError):
    pass


class PrefixListRuleExistsError(PrefixListConflictError):
    pass


class PrefixListRuleDuplicateError(PrefixListConflictError):
    """Another rule already matches the same action/prefix/ge/le tuple."""


class PrefixListNotFoundError(PrefixListError):
    pass


class PrefixListRuleNotFoundError(PrefixListError):
    pass


class PrefixListInUseError(PrefixListError):
    """Deletion was refused because the list is referenced elsewhere."""

    def __init__(self, message: str, *, used_by: list[str]) -> None:
        super().__init__(message)
        self.used_by = used_by


class PrefixListValidationError(PrefixListError):
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


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _sorted_rule_items(raw: Any) -> list[tuple[int, dict[str, Any]]]:
    items: list[tuple[int, dict[str, Any]]] = []
    for key, value in _dict(raw).items():
        number = _as_int(key)
        if number is None or not 1 <= number <= 65_535:
            continue
        items.append((number, _dict(value)))
    return sorted(items, key=lambda item: item[0])


def _network_for_family(value: str, family: PrefixListFamily) -> ipaddress.IPv4Network | None:
    """Parse and canonicalise a prefix, returning ``None`` on a family mismatch."""

    try:
        network = ipaddress.ip_network(value.strip(), strict=True)
    except ValueError:
        return None
    expected_version = 4 if family == "ipv4" else 6
    if network.version != expected_version:
        return None
    return network


def _parse_rule(number: int, raw: Any, family: PrefixListFamily) -> PrefixListRuleRead | None:
    rule = _dict(raw)
    action = _scalar(rule.get("action"))
    if action not in {"permit", "deny"}:
        # ``action`` is mandatory in VyOS; an incomplete rule cannot be
        # represented by the contract, so omit it from the read model.
        return None
    prefix = _scalar(rule.get("prefix"))
    if not prefix:
        return None
    network = _network_for_family(prefix, family)
    if network is None:
        # Either malformed or configured in the wrong family tree; a read model
        # cannot represent it, so skip it rather than failing the whole list.
        return None
    candidate = {
        "number": number,
        "action": action,
        "prefix": str(network),
        "ge": _as_int(rule.get("ge")),
        "le": _as_int(rule.get("le")),
        "description": _scalar(rule.get("description")),
    }
    try:
        return PrefixListRuleRead.model_validate(candidate)
    except ValidationError:
        return None


def parse_prefix_list(family: PrefixListFamily, name: str, raw: Any) -> PrefixListRead:
    """Parse one ``policy prefix-list <name>`` (or prefix-list6) node."""

    node = _dict(raw)
    rules = [
        rule
        for number, rule_raw in _sorted_rule_items(node.get("rule"))
        if (rule := _parse_rule(number, rule_raw, family)) is not None
    ]
    description = _scalar(node.get("description"))
    return PrefixListRead(
        name=name,
        family=family,
        description=description if description else None,
        rules=rules,
    )


def parse_prefix_lists(family: PrefixListFamily, raw: Any) -> list[PrefixListRead]:
    """Parse a prefix-list tree, sorted by name."""

    return [parse_prefix_list(family, name, value) for name, value in sorted(_dict(raw).items())]


def _family_for_path(path: list[str]) -> PrefixListFamily:
    return "ipv6" if "ipv6-unicast" in path else "ipv4"


def _bgp_usage_label(path: list[str]) -> str:
    """Render a BGP reference path as a short, readable label.

    Mirrors the route-map service labels (``BGP neighbor <addr> ·
    ipv4-unicast · prefix-list import``) so the UI can show both consistently.
    """

    parts = list(path[2:]) if path[:2] == ["protocols", "bgp"] else list(path)

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


def collect_prefix_list_usage(
    route_maps_raw: dict[str, Any], bgp_raw: dict[str, Any]
) -> dict[tuple[PrefixListFamily, str], list[str]]:
    """Return ``(family, name) -> sorted reference labels``.

    Route-map references are read from ``match ip|ipv6 address|nexthop
    prefix-list``.  BGP references are discovered generically by walking the
    ``protocols bgp`` tree for any ``prefix-list`` node, which covers neighbor
    and peer-group address-family import/export filters plus future BGP
    submodules.  The family is inferred from the path (``ipv6-unicast`` means
    IPv6, everything else IPv4).
    """

    usage: dict[tuple[PrefixListFamily, str], set[str]] = {}

    def add(family: PrefixListFamily, name: str | None, label: str) -> None:
        if name:
            usage.setdefault((family, name), set()).add(label)

    for map_name, map_raw in _dict(route_maps_raw).items():
        for number, rule_raw in _sorted_rule_items(_dict(map_raw).get("rule")):
            match = _dict(rule_raw.get("match"))
            for family, section in (("ipv4", "ip"), ("ipv6", "ipv6")):
                family_match = _dict(match.get(section))
                for name in _leaf_values(_dict(family_match.get("address")).get("prefix-list")):
                    add(
                        family,
                        name,
                        f"Route-map {map_name} · rule {number} · "
                        f"{FAMILY_LABELS[family]} prefix-list",
                    )
                for name in _leaf_values(_dict(family_match.get("nexthop")).get("prefix-list")):
                    add(
                        family,
                        name,
                        f"Route-map {map_name} · rule {number} · "
                        f"{FAMILY_LABELS[family]} nexthop prefix-list",
                    )

    def walk(node: Any, path: list[str]) -> None:
        for key, value in _dict(node).items():
            key_path = [*path, str(key)]
            if key == "prefix-list":
                family = _family_for_path(key_path)
                if isinstance(value, dict):
                    for direction, reference in value.items():
                        for name in _leaf_values(reference):
                            add(family, name, _bgp_usage_label([*key_path, str(direction)]))
                else:
                    for name in _leaf_values(value):
                        add(family, name, _bgp_usage_label(key_path))
            elif isinstance(value, dict):
                walk(value, key_path)

    walk(bgp_raw, ["protocols", "bgp"])

    return {key: sorted(labels) for key, labels in usage.items()}


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


def _rule_base(family: PrefixListFamily, name: str, number: int) -> list[str]:
    return [*PREFIX_LIST_ROOTS[family], name, "rule", str(number)]


def build_list_create_ops(
    family: PrefixListFamily, name: str, description: str | None
) -> list[ConfigOp]:
    base = [*PREFIX_LIST_ROOTS[family], name]
    ops = [_set(base)]
    if description:
        ops.append(_set([*base, "description", description]))
    return ops


def build_list_update_ops(
    family: PrefixListFamily,
    name: str,
    description: str | None,
    existing: dict[str, Any],
) -> list[ConfigOp]:
    ops: list[ConfigOp] = []
    _sync_leaf(ops, [*PREFIX_LIST_ROOTS[family], name], existing, "description", description)
    return ops


def build_list_delete_ops(family: PrefixListFamily, name: str) -> list[ConfigOp]:
    return [_delete([*PREFIX_LIST_ROOTS[family], name])]


def build_rule_create_ops(
    family: PrefixListFamily, name: str, rule: PrefixListRuleCreate
) -> list[ConfigOp]:
    base = _rule_base(family, name, rule.number)
    ops = [_set(base), _set([*base, "action", rule.action])]
    # ``prefix`` is mandatory in VyOS; the schema guarantees it is present.
    ops.append(_set([*base, "prefix", rule.prefix]))
    if rule.ge is not None:
        ops.append(_set([*base, "ge", str(rule.ge)]))
    if rule.le is not None:
        ops.append(_set([*base, "le", str(rule.le)]))
    if rule.description:
        ops.append(_set([*base, "description", rule.description]))
    return ops


def build_rule_update_ops(
    family: PrefixListFamily,
    name: str,
    number: int,
    rule: PrefixListRuleUpdate,
    existing: dict[str, Any],
) -> list[ConfigOp]:
    """Sync the managed leaves; unknown fields on the rule are never touched."""

    base = _rule_base(family, name, number)
    ops: list[ConfigOp] = []

    current_action = _scalar(existing.get("action"))
    if current_action != rule.action:
        ops.append(_set([*base, "action", rule.action]))

    current_prefix = _scalar(existing.get("prefix"))
    current_network = (
        _network_for_family(current_prefix, family) if current_prefix is not None else None
    )
    if current_network is None or str(current_network) != rule.prefix:
        ops.append(_set([*base, "prefix", rule.prefix]))

    _sync_int_leaf(ops, base, existing, "ge", rule.ge)
    _sync_int_leaf(ops, base, existing, "le", rule.le)
    _sync_leaf(ops, base, existing, "description", rule.description)
    return ops


def build_rule_delete_ops(family: PrefixListFamily, name: str, number: int) -> list[ConfigOp]:
    return [_delete(_rule_base(family, name, number))]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _rule_signature(
    rule: PrefixListRuleCreate | PrefixListRuleUpdate,
) -> tuple[str, str, int | None, int | None]:
    return (rule.action, rule.prefix, rule.ge, rule.le)


def _raw_rule_signature(
    family: PrefixListFamily, raw: Any
) -> tuple[str, str, int | None, int | None] | None:
    rule = _dict(raw)
    action = _scalar(rule.get("action"))
    prefix = _scalar(rule.get("prefix"))
    if action not in {"permit", "deny"} or not prefix:
        return None
    network = _network_for_family(prefix, family)
    if network is None:
        return None
    return (action, str(network), _as_int(rule.get("ge")), _as_int(rule.get("le")))


class PrefixListService:
    def __init__(self, driver: VyosDriver, router: Router) -> None:
        self._driver = driver
        self._router = router

    async def _raw_tree(self, family: PrefixListFamily) -> dict[str, Any]:
        try:
            raw = await self._driver.get_config(PREFIX_LIST_ROOTS[family])
        except VyosPathNotFound:
            return {}
        return _dict(raw)

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

    async def _usage(self) -> dict[tuple[PrefixListFamily, str], list[str]]:
        return collect_prefix_list_usage(await self._raw_route_maps(), await self._raw_bgp())

    @staticmethod
    def _with_usage(
        prefix_list: PrefixListRead,
        usage: dict[tuple[PrefixListFamily, str], list[str]],
    ) -> PrefixListRead:
        used_by = usage.get((prefix_list.family, prefix_list.name), [])
        return prefix_list.model_copy(update={"in_use": bool(used_by), "used_by": used_by})

    async def list(self, family: PrefixListFamily | None = None) -> PrefixListList:
        families: tuple[PrefixListFamily, ...] = (
            (family,) if family is not None else ("ipv4", "ipv6")
        )
        usage = await self._usage()
        items: list[PrefixListRead] = []
        for current in families:
            raw = await self._raw_tree(current)
            items.extend(self._with_usage(item, usage) for item in parse_prefix_lists(current, raw))
        items.sort(key=lambda item: (item.family, item.name))
        return PrefixListList(items=items, total=len(items))

    async def get(self, family: PrefixListFamily, name: str) -> PrefixListRead:
        raw = await self._raw_tree(family)
        if name not in raw:
            raise PrefixListNotFoundError(
                f"{FAMILY_LABELS[family]} prefix-list {name} does not exist"
            )
        usage = await self._usage()
        return self._with_usage(parse_prefix_list(family, name, raw[name]), usage)

    async def create(self, payload: PrefixListCreate) -> PrefixListRead:
        raw = await self._raw_tree(payload.family)
        if payload.name in raw:
            raise PrefixListExistsError(
                f"{FAMILY_LABELS[payload.family]} prefix-list {payload.name} already exists"
            )
        await self._driver.apply(
            build_list_create_ops(payload.family, payload.name, payload.description)
        )
        return await self.get(payload.family, payload.name)

    async def update(
        self, family: PrefixListFamily, name: str, payload: PrefixListUpdate
    ) -> PrefixListRead:
        raw = await self._raw_tree(family)
        if name not in raw:
            raise PrefixListNotFoundError(
                f"{FAMILY_LABELS[family]} prefix-list {name} does not exist"
            )
        ops = build_list_update_ops(family, name, payload.description, _dict(raw[name]))
        if ops:
            await self._driver.apply(ops)
        return await self.get(family, name)

    async def delete(self, family: PrefixListFamily, name: str) -> None:
        raw = await self._raw_tree(family)
        if name not in raw:
            raise PrefixListNotFoundError(
                f"{FAMILY_LABELS[family]} prefix-list {name} does not exist"
            )
        usage = await self._usage()
        used_by = usage.get((family, name), [])
        if used_by:
            raise PrefixListInUseError(
                f"{FAMILY_LABELS[family]} prefix-list {name} is in use and cannot be deleted",
                used_by=used_by,
            )
        await self._driver.apply(build_list_delete_ops(family, name))

    def _validate_prefix(self, family: PrefixListFamily, name: str, prefix: str) -> None:
        network = _network_for_family(prefix, family)
        if network is None:
            raise PrefixListValidationError(
                f"Prefix {prefix} is not valid for {FAMILY_LABELS[family]} prefix-list {name}",
                field="prefix",
                value=prefix,
            )

    async def create_rule(
        self, family: PrefixListFamily, name: str, payload: PrefixListRuleCreate
    ) -> PrefixListRead:
        raw = await self._raw_tree(family)
        if name not in raw:
            raise PrefixListNotFoundError(
                f"{FAMILY_LABELS[family]} prefix-list {name} does not exist"
            )
        rules = _dict(_dict(raw[name]).get("rule"))
        if str(payload.number) in rules:
            raise PrefixListRuleExistsError(
                f"Rule {payload.number} already exists in "
                f"{FAMILY_LABELS[family]} prefix-list {name}"
            )
        self._validate_prefix(family, name, payload.prefix)
        desired = _rule_signature(payload)
        for number, existing_rule in _sorted_rule_items(rules):
            if _raw_rule_signature(family, existing_rule) == desired:
                raise PrefixListRuleDuplicateError(
                    f"Rule {payload.number} duplicates rule {number} in "
                    f"{FAMILY_LABELS[family]} prefix-list {name} "
                    f"(same action, prefix, ge and le)"
                )
        await self._driver.apply(build_rule_create_ops(family, name, payload))
        return await self.get(family, name)

    async def update_rule(
        self,
        family: PrefixListFamily,
        name: str,
        number: int,
        payload: PrefixListRuleUpdate,
    ) -> PrefixListRead:
        raw = await self._raw_tree(family)
        if name not in raw:
            raise PrefixListNotFoundError(
                f"{FAMILY_LABELS[family]} prefix-list {name} does not exist"
            )
        rules = _dict(_dict(raw[name]).get("rule"))
        existing = rules.get(str(number))
        if not isinstance(existing, dict):
            raise PrefixListRuleNotFoundError(
                f"Rule {number} does not exist in {FAMILY_LABELS[family]} prefix-list {name}"
            )
        self._validate_prefix(family, name, payload.prefix)
        desired = _rule_signature(payload)
        for other_number, other_rule in _sorted_rule_items(rules):
            if other_number == number:
                continue
            if _raw_rule_signature(family, other_rule) == desired:
                raise PrefixListRuleDuplicateError(
                    f"Rule {number} duplicates rule {other_number} in "
                    f"{FAMILY_LABELS[family]} prefix-list {name} "
                    f"(same action, prefix, ge and le)"
                )
        ops = build_rule_update_ops(family, name, number, payload, existing)
        if ops:
            await self._driver.apply(ops)
        return await self.get(family, name)

    async def delete_rule(self, family: PrefixListFamily, name: str, number: int) -> PrefixListRead:
        raw = await self._raw_tree(family)
        if name not in raw:
            raise PrefixListNotFoundError(
                f"{FAMILY_LABELS[family]} prefix-list {name} does not exist"
            )
        rules = _dict(_dict(raw[name]).get("rule"))
        if str(number) not in rules:
            raise PrefixListRuleNotFoundError(
                f"Rule {number} does not exist in {FAMILY_LABELS[family]} prefix-list {name}"
            )
        await self._driver.apply(build_rule_delete_ops(family, name, number))
        return await self.get(family, name)
