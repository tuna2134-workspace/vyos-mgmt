"""WireGuard management endpoints.

The module manages only the ``interfaces wireguard wgN`` tree.  Reads are
available to every authenticated role; every mutation and key-generation
endpoint requires operator or admin.  Domain failures are translated into the
stable error codes from the API contract.

Key-generation routes are declared before ``/{name}`` so that ``keypair`` and
``preshared-key`` are never captured as interface names.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, Response, status

from vyos_mgmt.api.deps import (
    CurrentUser,
    OperatorUser,
    RouterDep,
    SessionDep,
    WireGuardServiceDep,
)
from vyos_mgmt.core.errors import AppError, conflict, not_found
from vyos_mgmt.db.models import Router, User
from vyos_mgmt.schemas.wireguard import (
    WireGuardInterfaceCreate,
    WireGuardInterfaceDetail,
    WireGuardInterfaceUpdate,
    WireGuardKeypair,
    WireGuardList,
    WireGuardPeerCreate,
    WireGuardPeerRead,
    WireGuardPeerUpdate,
    WireGuardPresharedKey,
    WireGuardPrivateKeyUpdate,
    WireGuardStatus,
    validate_wireguard_interface_name,
    validate_wireguard_peer_name,
)
from vyos_mgmt.services.audit import record_audit
from vyos_mgmt.services.wireguard_service import (
    WireGuardAllowedIpsConflictError,
    WireGuardError,
    WireGuardInterfaceExistsError,
    WireGuardInterfaceNotFoundError,
    WireGuardPeerExistsError,
    WireGuardPeerNotFoundError,
    WireGuardPublicKeyConflictError,
    WireGuardService,
    WireGuardValidationError,
    generate_keypair,
    generate_preshared_key,
)

router = APIRouter(prefix="/routers/{router_id}/wireguard", tags=["wireguard"])


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------


def _interface_name_path(name: Annotated[str, Path(description="WireGuard interface name")]) -> str:
    """Validate ``{name}`` and return a 422 validation_error envelope on failure."""

    try:
        return validate_wireguard_interface_name(name)
    except ValueError as exc:
        raise AppError(
            422,
            "validation_error",
            "The request payload is invalid",
            details=[
                {
                    "loc": ["path", "name"],
                    "msg": str(exc),
                    "type": "value_error",
                    "input": name,
                }
            ],
        ) from exc


WireGuardNamePath = Annotated[str, Depends(_interface_name_path)]


def _peer_name_path(peer: Annotated[str, Path(description="WireGuard peer alias")]) -> str:
    """Validate ``{peer}`` and return a 422 validation_error envelope on failure."""

    try:
        return validate_wireguard_peer_name(peer)
    except ValueError as exc:
        raise AppError(
            422,
            "validation_error",
            "The request payload is invalid",
            details=[
                {
                    "loc": ["path", "peer"],
                    "msg": str(exc),
                    "type": "value_error",
                    "input": peer,
                }
            ],
        ) from exc


WireGuardPeerPath = Annotated[str, Depends(_peer_name_path)]


# ---------------------------------------------------------------------------
# Error / audit helpers
# ---------------------------------------------------------------------------


def _translate(exc: Exception) -> AppError:
    if isinstance(exc, WireGuardInterfaceExistsError):
        return conflict("wireguard_interface_exists", str(exc))
    if isinstance(exc, WireGuardPeerExistsError):
        return conflict("wireguard_peer_exists", str(exc))
    if isinstance(exc, WireGuardPublicKeyConflictError):
        return AppError(
            422,
            "wireguard_public_key_conflict",
            str(exc),
            details={"public_key": exc.public_key, "peer": exc.peer},
        )
    if isinstance(exc, WireGuardAllowedIpsConflictError):
        return AppError(
            422,
            "wireguard_allowed_ips_conflict",
            str(exc),
            details={
                "allowed_ips": exc.allowed_ips,
                "peers": exc.peers,
                "conflicts": exc.conflicts,
            },
        )
    if isinstance(exc, WireGuardPeerNotFoundError):
        return not_found("wireguard_peer_not_found", str(exc))
    if isinstance(exc, WireGuardInterfaceNotFoundError):
        return not_found("wireguard_interface_not_found", str(exc))
    if isinstance(exc, WireGuardValidationError):
        return AppError(
            422,
            "validation_error",
            "The request payload is invalid",
            details=[
                {
                    "loc": ["body", exc.field],
                    "msg": str(exc),
                    "type": "value_error",
                    "input": exc.value,
                }
            ],
        )
    raise exc


async def _audit(
    session: SessionDep,
    request: Request,
    actor: User,
    device: Router,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    await record_audit(
        session,
        action=action,
        resource_type=resource_type,
        actor=actor,
        request=request,
        router=device,
        resource_id=resource_id,
        details=details,
    )


def _interface_details(interface: WireGuardInterfaceDetail) -> dict[str, Any]:
    """Audit-safe interface metadata (never key material)."""

    return {
        "name": interface.name,
        "description": interface.description,
        "addresses": interface.addresses,
        "port": interface.port,
        "mtu": interface.mtu,
        "enabled": interface.enabled,
    }


def _peer_details(interface: WireGuardInterfaceDetail, peer: WireGuardPeerRead) -> dict[str, Any]:
    """Audit-safe peer metadata (never public/preshared keys)."""

    return {
        "interface": interface.name,
        "name": peer.name,
        "description": peer.description,
        "allowed_ips": peer.allowed_ips,
        "endpoint": peer.endpoint,
        "endpoint_port": peer.endpoint_port,
        "persistent_keepalive": peer.persistent_keepalive,
        "has_preshared_key": peer.has_preshared_key,
        "enabled": peer.enabled,
    }


def _find_peer(interface: WireGuardInterfaceDetail, name: str) -> WireGuardPeerRead:
    peer = next((item for item in interface.peers if item.name == name), None)
    if peer is None:  # pragma: no cover - the service guarantees the write succeeded
        raise not_found(
            "wireguard_peer_not_found",
            f"Peer {name} does not exist on WireGuard interface {interface.name}",
        )
    return peer


# ---------------------------------------------------------------------------
# Key generation (must be declared before /{name})
# ---------------------------------------------------------------------------


@router.post("/keypair", response_model=WireGuardKeypair)
async def create_keypair(_actor: OperatorUser, _device: RouterDep) -> WireGuardKeypair:
    """Generate a one-time X25519 keypair; nothing is written to the device."""

    private_key, public_key = generate_keypair()
    return WireGuardKeypair(private_key=private_key, public_key=public_key)


@router.post("/preshared-key", response_model=WireGuardPresharedKey)
async def create_preshared_key(_actor: OperatorUser, _device: RouterDep) -> WireGuardPresharedKey:
    """Generate a one-time 32-byte preshared key; not audited with key material."""

    return WireGuardPresharedKey(preshared_key=generate_preshared_key())


# ---------------------------------------------------------------------------
# Interfaces
# ---------------------------------------------------------------------------


@router.get("", response_model=WireGuardList)
async def list_wireguard_interfaces(
    service: WireGuardServiceDep,
    _current_user: CurrentUser,
) -> WireGuardList:
    return await service.list()


@router.post("", response_model=WireGuardInterfaceDetail, status_code=status.HTTP_201_CREATED)
async def create_wireguard_interface(
    payload: WireGuardInterfaceCreate,
    request: Request,
    service: WireGuardServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> WireGuardInterfaceDetail:
    try:
        interface = await service.create(payload)
    except WireGuardError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="wireguard.interface.create",
        resource_type="wireguard_interface",
        resource_id=interface.name,
        details=_interface_details(interface),
    )
    return interface


@router.get("/{name}", response_model=WireGuardInterfaceDetail)
async def get_wireguard_interface(
    name: WireGuardNamePath,
    service: WireGuardServiceDep,
    _current_user: CurrentUser,
) -> WireGuardInterfaceDetail:
    try:
        return await service.get(name)
    except WireGuardInterfaceNotFoundError as exc:
        raise _translate(exc) from exc


@router.put("/{name}", response_model=WireGuardInterfaceDetail)
async def update_wireguard_interface(
    name: WireGuardNamePath,
    payload: WireGuardInterfaceUpdate,
    request: Request,
    service: WireGuardServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> WireGuardInterfaceDetail:
    try:
        interface = await service.update(name, payload)
    except WireGuardError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="wireguard.interface.update",
        resource_type="wireguard_interface",
        resource_id=interface.name,
        details=_interface_details(interface),
    )
    return interface


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wireguard_interface(
    name: WireGuardNamePath,
    request: Request,
    service: WireGuardServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> Response:
    try:
        await service.delete(name)
    except WireGuardInterfaceNotFoundError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="wireguard.interface.delete",
        resource_type="wireguard_interface",
        resource_id=name,
        details={"name": name},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{name}/private-key", response_model=WireGuardInterfaceDetail)
async def rotate_wireguard_private_key(
    name: WireGuardNamePath,
    payload: WireGuardPrivateKeyUpdate,
    request: Request,
    service: WireGuardServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> WireGuardInterfaceDetail:
    try:
        interface = await service.rotate_private_key(name, payload)
    except WireGuardError as exc:
        raise _translate(exc) from exc

    # Never include the private key (or any key material) in the audit trail.
    await _audit(
        session,
        request,
        actor,
        device,
        action="wireguard.private_key.update",
        resource_type="wireguard_interface",
        resource_id=interface.name,
        details={"name": interface.name},
    )
    return interface


@router.get("/{name}/status", response_model=WireGuardStatus)
async def get_wireguard_status(
    name: WireGuardNamePath,
    service: WireGuardServiceDep,
    _current_user: CurrentUser,
) -> WireGuardStatus:
    try:
        return await service.get_status(name)
    except WireGuardInterfaceNotFoundError as exc:
        raise _translate(exc) from exc


# ---------------------------------------------------------------------------
# Peers
# ---------------------------------------------------------------------------


@router.post(
    "/{name}/peers",
    response_model=WireGuardInterfaceDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_wireguard_peer(
    name: WireGuardNamePath,
    payload: WireGuardPeerCreate,
    request: Request,
    service: WireGuardServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> WireGuardInterfaceDetail:
    try:
        interface = await service.create_peer(name, payload)
    except WireGuardError as exc:
        raise _translate(exc) from exc

    peer = _find_peer(interface, payload.name)
    await _audit(
        session,
        request,
        actor,
        device,
        action="wireguard.peer.create",
        resource_type="wireguard_peer",
        resource_id=f"{interface.name}:{peer.name}",
        details=_peer_details(interface, peer),
    )
    return interface


@router.put("/{name}/peers/{peer}", response_model=WireGuardInterfaceDetail)
async def update_wireguard_peer(
    name: WireGuardNamePath,
    peer: WireGuardPeerPath,
    payload: WireGuardPeerUpdate,
    request: Request,
    service: WireGuardServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> WireGuardInterfaceDetail:
    try:
        interface = await service.update_peer(name, peer, payload)
    except WireGuardError as exc:
        raise _translate(exc) from exc

    updated = _find_peer(interface, peer)
    await _audit(
        session,
        request,
        actor,
        device,
        action="wireguard.peer.update",
        resource_type="wireguard_peer",
        resource_id=f"{interface.name}:{updated.name}",
        details=_peer_details(interface, updated),
    )
    return interface


@router.delete("/{name}/peers/{peer}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wireguard_peer(
    name: WireGuardNamePath,
    peer: WireGuardPeerPath,
    request: Request,
    service: WireGuardServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> Response:
    try:
        await service.delete_peer(name, peer)
    except WireGuardError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="wireguard.peer.delete",
        resource_type="wireguard_peer",
        resource_id=f"{name}:{peer}",
        details={"interface": name, "peer": peer},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Re-exported for tests and future modules that build the service directly.
__all__ = ["WireGuardService", "router"]
