"""WireGuard domain service: ``interfaces wireguard wgN`` <-> API DTOs.

The service owns all translation between the VyOS configuration tree and the
API models:

* keys are generated and public keys derived locally with X25519
  (``cryptography``); private and preshared keys are never logged or returned;
* reads tolerate device defaults and unrepresentable directives;
* every mutation is exactly one atomic ``driver.apply`` batch and only syncs
  the API-managed fields, so unknown device directives survive an update;
* peer conflicts (duplicate alias, public key or exact allowed-IP prefix) are
  rejected before anything is sent to the device.
"""

from __future__ import annotations

import base64
import ipaddress
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from pydantic import ValidationError

from vyos_mgmt.db.models import Router
from vyos_mgmt.schemas.wireguard import (
    MTU_MAX,
    MTU_MIN,
    PORT_MAX,
    PORT_MIN,
    WireGuardInterfaceCreate,
    WireGuardInterfaceDetail,
    WireGuardInterfaceRead,
    WireGuardInterfaceUpdate,
    WireGuardList,
    WireGuardPeerCreate,
    WireGuardPeerRead,
    WireGuardPeerUpdate,
    WireGuardPrivateKeyUpdate,
    WireGuardStatus,
    WireGuardStatusPeer,
    canonical_allowed_ip,
    canonical_interface_address,
    canonical_wireguard_key,
    decode_wireguard_key,
    validate_endpoint,
    validate_wireguard_interface_name,
)
from vyos_mgmt.services.vyos.base import (
    ConfigOp,
    VyosCommandError,
    VyosConnectionError,
    VyosDriver,
    VyosPathNotFound,
)

WIREGUARD_ROOT = ["interfaces", "wireguard"]

_TRANSFER_RE = re.compile(
    r"^(?P<received>.+?)\s+received,?\s*(?P<sent>.+?)\s+sent$",
    re.IGNORECASE,
)
_NOT_RUNNING_MARKERS = (
    "not running",
    "not configured",
    "not found",
    "no such device",
    "unable to access",
    "is disabled",
    "does not exist",
)


class WireGuardError(Exception):
    """Base class for WireGuard domain failures."""


class WireGuardConflictError(WireGuardError):
    """A conflicting object already exists on the device."""


class WireGuardInterfaceExistsError(WireGuardConflictError):
    pass


class WireGuardPeerExistsError(WireGuardConflictError):
    pass


class WireGuardPublicKeyConflictError(WireGuardError):
    """Another peer already uses the same public key."""

    def __init__(self, message: str, *, public_key: str | None = None, peer: str | None = None):
        super().__init__(message)
        self.public_key = public_key
        self.peer = peer


class WireGuardAllowedIpsConflictError(WireGuardError):
    """Another peer already uses one or more of the requested allowed IPs."""

    def __init__(
        self,
        message: str,
        *,
        allowed_ips: list[str],
        peers: list[str],
        conflicts: list[dict[str, str]],
    ) -> None:
        super().__init__(message)
        self.allowed_ips = allowed_ips
        self.peers = peers
        self.conflicts = conflicts


class WireGuardNotFoundError(WireGuardError):
    pass


class WireGuardInterfaceNotFoundError(WireGuardNotFoundError):
    pass


class WireGuardPeerNotFoundError(WireGuardNotFoundError):
    pass


class WireGuardValidationError(WireGuardError):
    """A semantic validation error that Pydantic cannot express on its own."""

    def __init__(self, message: str, *, field: str, value: Any = None) -> None:
        super().__init__(message)
        self.field = field
        self.value = value


class WireGuardKeyError(WireGuardError):
    """An invalid key was supplied; messages never contain the key material."""


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def clamp_private_key(raw: bytes) -> bytes:
    """Apply the RFC 7748 clamping required for X25519/WireGuard private keys."""

    if len(raw) != 32:
        raise WireGuardKeyError("WireGuard private keys must be exactly 32 bytes")
    clamped = bytearray(raw)
    clamped[0] &= 248
    clamped[31] &= 127
    clamped[31] |= 64
    return bytes(clamped)


def generate_private_key() -> str:
    """Generate a clamped, Base64-encoded X25519 private key."""

    return _b64encode(clamp_private_key(os.urandom(32)))


def derive_public_key(private_key: str) -> str:
    """Derive the Base64 public key for a Base64 private key.

    The error message deliberately never includes the supplied key.
    """

    try:
        raw = decode_wireguard_key(private_key)
        public = (
            X25519PrivateKey.from_private_bytes(raw)
            .public_key()
            .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        )
    except (ValueError, TypeError) as exc:
        raise WireGuardKeyError(
            "Invalid WireGuard private key: expected a Base64-encoded 32-byte value"
        ) from exc
    return _b64encode(public)


def generate_keypair() -> tuple[str, str]:
    """Return ``(private_key, public_key)``; both are Base64-encoded."""

    private_key = generate_private_key()
    return private_key, derive_public_key(private_key)


def generate_preshared_key() -> str:
    """Generate a random Base64-encoded 32-byte preshared key."""

    return _b64encode(os.urandom(32))


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
    if isinstance(value, bool):
        return None
    scalar = _scalar(value)
    if scalar is None:
        return None
    try:
        return int(scalar)
    except (TypeError, ValueError):
        return None


def _as_bounded_int(value: Any, minimum: int, maximum: int) -> int | None:
    number = _as_int(value)
    if number is None or not minimum <= number <= maximum:
        return None
    return number


def _private_key(node: dict[str, Any]) -> str | None:
    return _scalar(node.get("private-key"))


def _public_key_from_private(private_key: str | None) -> str | None:
    if not private_key:
        return None
    try:
        return derive_public_key(private_key)
    except WireGuardKeyError:
        return None


def _canonical_peer_key(value: Any) -> str | None:
    scalar = _scalar(value)
    if not scalar:
        return None
    try:
        return canonical_wireguard_key(scalar)
    except ValueError:
        return None


def _canonical_prefixes(value: Any) -> list[str]:
    prefixes: list[str] = []
    for item in _leaf_values(value):
        try:
            prefix = canonical_allowed_ip(item)
        except ValueError:
            continue
        if prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


# ---------------------------------------------------------------------------
# Read parsing
# ---------------------------------------------------------------------------


def parse_peer(name: str, raw: Any) -> WireGuardPeerRead | None:
    """Parse one ``interfaces wireguard <name> peer <alias>`` node.

    A peer without a valid public key cannot be represented by the contract
    (and is unusable on the device), so it is skipped instead of failing the
    whole interface read.
    """

    node = _dict(raw)
    public_key = _canonical_peer_key(node.get("public-key"))
    if public_key is None:
        return None

    endpoint = _scalar(node.get("address")) or _scalar(node.get("host-name"))
    if endpoint:
        try:
            endpoint = validate_endpoint(endpoint)
        except ValueError:
            endpoint = None

    preshared_key = _scalar(node.get("preshared-key"))
    candidate = {
        "name": name,
        "description": _scalar(node.get("description")) or None,
        "public_key": public_key,
        "allowed_ips": _canonical_prefixes(node.get("allowed-ips")),
        "endpoint": endpoint,
        "endpoint_port": _as_bounded_int(node.get("port"), PORT_MIN, PORT_MAX),
        "persistent_keepalive": _as_bounded_int(
            node.get("persistent-keepalive"), PORT_MIN, PORT_MAX
        ),
        "has_preshared_key": bool(preshared_key),
        "enabled": "disable" not in node,
    }
    try:
        return WireGuardPeerRead.model_validate(candidate)
    except ValidationError:
        return None


def parse_peers(raw: Any) -> list[WireGuardPeerRead]:
    """Parse an interface's peer tag-node tree, sorted by alias."""

    peers = [
        peer
        for name, value in sorted(_dict(_dict(raw).get("peer")).items())
        if (peer := parse_peer(str(name), value)) is not None
    ]
    return peers


def parse_interface(name: str, raw: Any) -> WireGuardInterfaceRead:
    """Parse one WireGuard interface, deriving the public key from its private key."""

    node = _dict(raw)
    addresses: list[str] = []
    for value in _leaf_values(node.get("address")):
        try:
            address = canonical_interface_address(value)
        except ValueError:
            continue
        if address not in addresses:
            addresses.append(address)

    return WireGuardInterfaceRead(
        name=name,
        description=_scalar(node.get("description")) or None,
        addresses=addresses,
        port=_as_bounded_int(node.get("port"), PORT_MIN, PORT_MAX),
        mtu=_as_bounded_int(node.get("mtu"), MTU_MIN, MTU_MAX),
        enabled="disable" not in node,
        public_key=_public_key_from_private(_private_key(node)),
        peer_count=len(_dict(node.get("peer"))),
    )


def parse_interface_detail(name: str, raw: Any) -> WireGuardInterfaceDetail:
    """Parse one interface plus its representable peers."""

    interface = parse_interface(name, raw)
    return WireGuardInterfaceDetail(**interface.model_dump(), peers=parse_peers(raw))


def parse_interfaces(raw: Any) -> list[WireGuardInterfaceRead]:
    """Parse the ``interfaces wireguard`` tree, sorted by interface name."""

    parsed: list[WireGuardInterfaceRead] = []
    for name, value in sorted(_dict(raw).items()):
        try:
            validate_wireguard_interface_name(str(name))
        except ValueError:
            continue
        parsed.append(parse_interface(str(name), value))
    return parsed


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


def _sync_multi_values(
    ops: list[ConfigOp],
    base: list[str],
    existing: dict[str, Any],
    key: str,
    desired: list[str],
    canonicalizer: Callable[[str], str],
) -> None:
    """Full replacement of a multi-value leaf, touching only changed values.

    Existing values are compared in canonical form; a value that cannot be
    canonicalised (for example ``dhcp`` on an address) is still removed because
    the field is API-managed and the request replaces it.
    """

    desired_set = set(desired)
    current_set: set[str] = set()
    for raw_value in _leaf_values(existing.get(key)):
        text = str(raw_value)
        try:
            canonical = canonicalizer(text)
        except ValueError:
            ops.append(_delete([*base, key, text]))
            continue
        current_set.add(canonical)
        if canonical not in desired_set:
            ops.append(_delete([*base, key, text]))

    for value in desired:
        if value not in current_set:
            ops.append(_set([*base, key, value]))


def build_interface_create_ops(payload: WireGuardInterfaceCreate) -> list[ConfigOp]:
    """Plan ``POST /wireguard`` as one atomic batch."""

    base = [*WIREGUARD_ROOT, payload.name]
    ops: list[ConfigOp] = [_set(base)]
    if payload.description:
        ops.append(_set([*base, "description", payload.description]))
    ops.append(_set([*base, "private-key", payload.private_key]))
    for address in payload.addresses:
        ops.append(_set([*base, "address", address]))
    if payload.port is not None:
        ops.append(_set([*base, "port", str(payload.port)]))
    if payload.mtu is not None:
        ops.append(_set([*base, "mtu", str(payload.mtu)]))
    if not payload.enabled:
        ops.append(_set([*base, "disable"]))
    return ops


def build_interface_update_ops(
    name: str,
    payload: WireGuardInterfaceUpdate,
    existing: dict[str, Any],
) -> list[ConfigOp]:
    """Sync the managed metadata fields; the private key and peers are untouched."""

    base = [*WIREGUARD_ROOT, name]
    ops: list[ConfigOp] = []
    _sync_leaf(ops, base, existing, "description", payload.description)
    _sync_multi_values(
        ops, base, existing, "address", payload.addresses, canonical_interface_address
    )
    _sync_int_leaf(ops, base, existing, "port", payload.port)
    _sync_int_leaf(ops, base, existing, "mtu", payload.mtu)
    _sync_presence(ops, base, existing, "disable", not payload.enabled)
    return ops


def build_interface_delete_ops(name: str) -> list[ConfigOp]:
    return [_delete([*WIREGUARD_ROOT, name])]


def build_private_key_update_ops(name: str, private_key: str) -> list[ConfigOp]:
    return [_set([*WIREGUARD_ROOT, name, "private-key", private_key])]


def _sync_endpoint(
    ops: list[ConfigOp],
    base: list[str],
    existing: dict[str, Any],
    endpoint: str | None,
) -> None:
    """Map an endpoint to ``address`` (IP) or ``host-name`` (FQDN)."""

    current_address = _scalar(existing.get("address"))
    current_host_name = _scalar(existing.get("host-name"))
    if endpoint is None:
        if "address" in existing:
            ops.append(_delete([*base, "address"]))
        if "host-name" in existing:
            ops.append(_delete([*base, "host-name"]))
        return

    try:
        address = str(ipaddress.ip_address(endpoint))
    except ValueError:
        address = None

    if address is not None:
        if current_address != address:
            ops.append(_set([*base, "address", address]))
        if "host-name" in existing:
            ops.append(_delete([*base, "host-name"]))
    else:
        if current_host_name != endpoint:
            ops.append(_set([*base, "host-name", endpoint]))
        if "address" in existing:
            ops.append(_delete([*base, "address"]))


def _peer_base(interface: str, peer: str) -> list[str]:
    return [*WIREGUARD_ROOT, interface, "peer", peer]


def build_peer_create_ops(interface: str, payload: WireGuardPeerCreate) -> list[ConfigOp]:
    base = _peer_base(interface, payload.name)
    ops: list[ConfigOp] = [_set(base)]
    ops.append(_set([*base, "public-key", payload.public_key]))
    for prefix in payload.allowed_ips:
        ops.append(_set([*base, "allowed-ips", prefix]))
    _sync_endpoint(ops, base, {}, payload.endpoint)
    if payload.endpoint_port is not None:
        ops.append(_set([*base, "port", str(payload.endpoint_port)]))
    if payload.persistent_keepalive is not None:
        ops.append(_set([*base, "persistent-keepalive", str(payload.persistent_keepalive)]))
    if payload.description:
        ops.append(_set([*base, "description", payload.description]))
    if not payload.enabled:
        ops.append(_set([*base, "disable"]))
    if payload.preshared_key:
        ops.append(_set([*base, "preshared-key", payload.preshared_key]))
    return ops


def build_peer_update_ops(
    interface: str,
    peer: str,
    payload: WireGuardPeerUpdate,
    existing: dict[str, Any],
) -> list[ConfigOp]:
    """Sync the managed peer fields, preserving unknown directives.

    ``preshared_key`` is tri-state: omitted preserves the current key, a string
    replaces it and an explicit ``null`` removes it.  ``model_fields_set`` is
    what distinguishes "omitted" from "null".
    """

    base = _peer_base(interface, peer)
    ops: list[ConfigOp] = []
    _sync_leaf(ops, base, existing, "description", payload.description)
    _sync_leaf(ops, base, existing, "public-key", payload.public_key)
    _sync_multi_values(
        ops, base, existing, "allowed-ips", payload.allowed_ips, canonical_allowed_ip
    )
    _sync_endpoint(ops, base, existing, payload.endpoint)
    _sync_int_leaf(ops, base, existing, "port", payload.endpoint_port)
    _sync_int_leaf(ops, base, existing, "persistent-keepalive", payload.persistent_keepalive)
    _sync_presence(ops, base, existing, "disable", not payload.enabled)
    if "preshared_key" in payload.model_fields_set:
        if payload.preshared_key:
            _sync_leaf(ops, base, existing, "preshared-key", payload.preshared_key)
        elif "preshared-key" in existing:
            ops.append(_delete([*base, "preshared-key"]))
    return ops


def build_peer_delete_ops(interface: str, peer: str) -> list[ConfigOp]:
    return [_delete(_peer_base(interface, peer))]


# ---------------------------------------------------------------------------
# Operational status parsing
# ---------------------------------------------------------------------------


def _looks_not_running(output: str) -> bool:
    lowered = output.lower()
    return any(marker in lowered for marker in _NOT_RUNNING_MARKERS)


def parse_wireguard_summary(
    output: str,
) -> tuple[str | None, int | None, list[WireGuardStatusPeer]]:
    """Parse ``show interfaces wireguard <name> summary``.

    The output is a small block format::

        interface: wg0
          public key: <base64>
          private key: (hidden)
          listening port: 51820

        peer: <base64>
          endpoint: 198.51.100.10:51820
          allowed ips: 192.168.50.0/24, 192.168.60.0/24
          latest handshake: 23 hours, 45 minutes, 26 seconds ago
          transfer: 1.26 MiB received, 6.47 MiB sent

    Only the fields the contract exposes are mapped; unknown lines are
    ignored.  Peers whose public key is not a valid 32-byte key are skipped.
    """

    interface_public_key: str | None = None
    listening_port: int | None = None
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if key == "interface":
            current = None
            continue
        if key == "public key":
            if current is None:
                try:
                    interface_public_key = canonical_wireguard_key(value)
                except ValueError:
                    interface_public_key = None
            continue
        if key == "listening port":
            listening_port = _as_bounded_int(value, PORT_MIN, PORT_MAX)
            continue
        if key == "peer":
            current = {
                "public_key": value,
                "endpoint": None,
                "allowed_ips": [],
                "latest_handshake": None,
                "transfer_received": None,
                "transfer_sent": None,
            }
            blocks.append(current)
            continue
        if current is None:
            continue

        if key == "endpoint":
            current["endpoint"] = None if value.lower() in {"(none)", "none"} else value
        elif key == "allowed ips":
            prefixes: list[str] = []
            for item in value.split(","):
                try:
                    prefix = canonical_allowed_ip(item)
                except ValueError:
                    continue
                if prefix not in prefixes:
                    prefixes.append(prefix)
            current["allowed_ips"] = prefixes
        elif key == "latest handshake":
            current["latest_handshake"] = value or None
        elif key == "transfer":
            match = _TRANSFER_RE.match(value)
            if match:
                current["transfer_received"] = match.group("received").strip() or None
                current["transfer_sent"] = match.group("sent").strip() or None

    peers: list[WireGuardStatusPeer] = []
    for block in blocks:
        try:
            peers.append(WireGuardStatusPeer.model_validate(block))
        except ValidationError:
            continue
    return interface_public_key, listening_port, peers


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class WireGuardService:
    def __init__(self, driver: VyosDriver, router: Router) -> None:
        self._driver = driver
        self._router = router

    async def _raw_root(self) -> dict[str, Any]:
        try:
            raw = await self._driver.get_config(WIREGUARD_ROOT)
        except VyosPathNotFound:
            return {}
        return _dict(raw)

    async def _require_interface(self, name: str) -> dict[str, Any]:
        raw = await self._raw_root()
        if name not in raw:
            raise WireGuardInterfaceNotFoundError(f"WireGuard interface {name} does not exist")
        return _dict(raw[name])

    async def list(self) -> WireGuardList:
        items = parse_interfaces(await self._raw_root())
        return WireGuardList(items=items, total=len(items))

    async def get(self, name: str) -> WireGuardInterfaceDetail:
        raw = await self._raw_root()
        if name not in raw:
            raise WireGuardInterfaceNotFoundError(f"WireGuard interface {name} does not exist")
        return parse_interface_detail(name, raw[name])

    # -- Interfaces --------------------------------------------------------

    async def create(self, payload: WireGuardInterfaceCreate) -> WireGuardInterfaceDetail:
        raw = await self._raw_root()
        if payload.name in raw:
            raise WireGuardInterfaceExistsError(
                f"WireGuard interface {payload.name} already exists"
            )
        await self._driver.apply(build_interface_create_ops(payload))
        return await self.get(payload.name)

    async def update(
        self, name: str, payload: WireGuardInterfaceUpdate
    ) -> WireGuardInterfaceDetail:
        existing = await self._require_interface(name)
        ops = build_interface_update_ops(name, payload, existing)
        if ops:
            await self._driver.apply(ops)
        return await self.get(name)

    async def delete(self, name: str) -> None:
        await self._require_interface(name)
        await self._driver.apply(build_interface_delete_ops(name))

    async def rotate_private_key(
        self, name: str, payload: WireGuardPrivateKeyUpdate
    ) -> WireGuardInterfaceDetail:
        """Replace the private key; the key itself is never returned or logged."""

        await self._require_interface(name)
        await self._driver.apply(build_private_key_update_ops(name, payload.private_key))
        return await self.get(name)

    # -- Peers -------------------------------------------------------------

    @staticmethod
    def _check_peer_conflicts(
        peers: dict[str, Any],
        payload: WireGuardPeerCreate | WireGuardPeerUpdate,
        *,
        exclude: str | None = None,
    ) -> None:
        """Reject duplicate public keys and exact allowed-IP overlaps.

        ``exclude`` is the peer being updated, so a peer never conflicts with
        itself.
        """

        for other_name, other_raw in sorted(peers.items()):
            if exclude is not None and str(other_name) == exclude:
                continue
            other_key = _canonical_peer_key(_dict(other_raw).get("public-key"))
            if other_key is not None and other_key == payload.public_key:
                raise WireGuardPublicKeyConflictError(
                    f"Public key is already used by peer {other_name}",
                    public_key=payload.public_key,
                    peer=str(other_name),
                )

        conflicts: list[dict[str, str]] = []
        for other_name, other_raw in sorted(peers.items()):
            if exclude is not None and str(other_name) == exclude:
                continue
            other_ips = set(_canonical_prefixes(_dict(other_raw).get("allowed-ips")))
            for prefix in payload.allowed_ips:
                if prefix in other_ips:
                    conflicts.append({"allowed_ip": prefix, "peer": str(other_name)})
        if conflicts:
            conflicts.sort(key=lambda item: (item["allowed_ip"], item["peer"]))
            allowed_ips = sorted({item["allowed_ip"] for item in conflicts})
            peer_names = sorted({item["peer"] for item in conflicts})
            raise WireGuardAllowedIpsConflictError(
                "Allowed IP " + ", ".join(allowed_ips) + " is already assigned to another peer",
                allowed_ips=allowed_ips,
                peers=peer_names,
                conflicts=conflicts,
            )

    async def create_peer(
        self, interface: str, payload: WireGuardPeerCreate
    ) -> WireGuardInterfaceDetail:
        node = await self._require_interface(interface)
        peers = _dict(node.get("peer"))
        if payload.name in peers:
            raise WireGuardPeerExistsError(
                f"Peer {payload.name} already exists on WireGuard interface {interface}"
            )
        self._check_peer_conflicts(peers, payload)
        await self._driver.apply(build_peer_create_ops(interface, payload))
        return await self.get(interface)

    async def update_peer(
        self, interface: str, peer: str, payload: WireGuardPeerUpdate
    ) -> WireGuardInterfaceDetail:
        node = await self._require_interface(interface)
        peers = _dict(node.get("peer"))
        existing = peers.get(peer)
        if not isinstance(existing, dict):
            raise WireGuardPeerNotFoundError(
                f"Peer {peer} does not exist on WireGuard interface {interface}"
            )
        self._check_peer_conflicts(peers, payload, exclude=peer)
        ops = build_peer_update_ops(interface, peer, payload, existing)
        if ops:
            await self._driver.apply(ops)
        return await self.get(interface)

    async def delete_peer(self, interface: str, peer: str) -> None:
        node = await self._require_interface(interface)
        if peer not in _dict(node.get("peer")):
            raise WireGuardPeerNotFoundError(
                f"Peer {peer} does not exist on WireGuard interface {interface}"
            )
        await self._driver.apply(build_peer_delete_ops(interface, peer))

    # -- Status ------------------------------------------------------------

    @staticmethod
    def _status_with_error(
        name: str,
        interface: WireGuardInterfaceRead,
        message: str,
    ) -> WireGuardStatus:
        return WireGuardStatus(
            configured=True,
            name=name,
            public_key=interface.public_key,
            listening_port=interface.port,
            peers=[],
            collected_at=datetime.now(UTC),
            error=(message.strip() if message else "")
            or f"WireGuard interface {name} is configured but the device is not running it",
        )

    async def get_status(self, name: str) -> WireGuardStatus:
        """Read the configured interface and its operational summary.

        A configured but not-running interface yields ``configured=True`` with
        an ``error`` and no peers.  Device connection failures are deliberately
        not swallowed, so the API layer maps them to ``502``.
        """

        raw = await self._raw_root()
        if name not in raw:
            raise WireGuardInterfaceNotFoundError(f"WireGuard interface {name} does not exist")
        interface = parse_interface(name, raw[name])

        try:
            output = await self._driver.show([*WIREGUARD_ROOT, name, "summary"])
        except VyosConnectionError:
            raise
        except VyosCommandError as exc:
            message = str(exc)
            if isinstance(exc, VyosPathNotFound) or _looks_not_running(message):
                return self._status_with_error(name, interface, message)
            # Any other device command failure is a real 502, not a status hint.
            raise

        parsed_public_key, listening_port, peers = parse_wireguard_summary(output)
        if _looks_not_running(output) and not peers:
            return self._status_with_error(name, interface, output.strip())
        if not output.strip():
            return self._status_with_error(
                name,
                interface,
                f"WireGuard interface {name} did not return any status output",
            )

        return WireGuardStatus(
            configured=True,
            name=name,
            public_key=interface.public_key or parsed_public_key,
            listening_port=listening_port if listening_port is not None else interface.port,
            peers=peers,
            collected_at=datetime.now(UTC),
            error=None,
        )


# Naming aliases matching the other feature modules (for example
# ``parse_prefix_list``); the short names remain the primary API.
parse_wireguard_interface = parse_interface
parse_wireguard_peer = parse_peer
parse_wireguard_interfaces = parse_interfaces
parse_wireguard_interface_detail = parse_interface_detail
