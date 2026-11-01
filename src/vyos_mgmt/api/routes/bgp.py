"""BGP configuration and operational status endpoints.

The route module stays thin: validation lives in the Pydantic schemas, the
configuration mapping in :mod:`vyos_mgmt.services.bgp_service`, and device
access behind the driver protocol.  Adding another VyOS feature follows the
same shape.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response, status

from vyos_mgmt.api.deps import (
    AdminUser,
    BgpServiceDep,
    CurrentUser,
    OperatorUser,
    RouterDep,
    SessionDep,
)
from vyos_mgmt.core.errors import AppError, conflict, not_found
from vyos_mgmt.db.models import Router, User
from vyos_mgmt.schemas.bgp import (
    BgpConfigRead,
    BgpGlobalUpdate,
    BgpNeighborCreate,
    BgpNeighborUpdate,
    BgpNetworkCreate,
    BgpPeerGroupCreate,
    BgpPeerGroupUpdate,
    BgpStatus,
)
from vyos_mgmt.services.audit import record_audit
from vyos_mgmt.services.bgp_service import BgpConflictError, BgpNotFoundError

router = APIRouter(prefix="/routers/{router_id}/bgp", tags=["bgp"])


def _translate(exc: Exception, resource: str) -> AppError:
    if isinstance(exc, BgpConflictError):
        return conflict(f"{resource}_exists", str(exc))
    if isinstance(exc, BgpNotFoundError):
        return not_found(f"{resource}_not_found", str(exc))
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


@router.get("", response_model=BgpConfigRead)
async def get_bgp_config(service: BgpServiceDep, _current_user: CurrentUser) -> BgpConfigRead:
    return await service.get_config()


@router.put("/global", response_model=BgpConfigRead)
async def update_bgp_global(
    payload: BgpGlobalUpdate,
    request: Request,
    service: BgpServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> BgpConfigRead:
    config = await service.update_global(payload)
    await _audit(
        session,
        request,
        actor,
        device,
        action="bgp.global.update",
        resource_type="bgp_global",
        resource_id=str(device.id),
        details={
            "system_as": payload.system_as,
            "router_id": payload.router_id,
            "log_neighbor_changes": payload.log_neighbor_changes,
        },
    )
    return config


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bgp(
    request: Request,
    service: BgpServiceDep,
    device: RouterDep,
    actor: AdminUser,
    session: SessionDep,
) -> Response:
    await service.delete_bgp()
    await _audit(
        session,
        request,
        actor,
        device,
        action="bgp.delete",
        resource_type="bgp_config",
        resource_id=str(device.id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Neighbors
# ---------------------------------------------------------------------------


@router.post("/neighbors", response_model=BgpConfigRead)
async def create_neighbor(
    payload: BgpNeighborCreate,
    request: Request,
    service: BgpServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> BgpConfigRead:
    try:
        config = await service.create_neighbor(payload)
    except (BgpConflictError, BgpNotFoundError) as exc:
        raise _translate(exc, "neighbor") from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="bgp.neighbor.create",
        resource_type="bgp_neighbor",
        resource_id=payload.address,
        details={
            "address": payload.address,
            "remote_as": payload.remote_as,
            "description": payload.description,
            "password_set": bool(payload.password),
            "address_families": sorted(payload.address_families),
        },
    )
    return config


@router.patch("/neighbors/{address}", response_model=BgpConfigRead)
async def update_neighbor(
    address: str,
    payload: BgpNeighborUpdate,
    request: Request,
    service: BgpServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> BgpConfigRead:
    try:
        config = await service.update_neighbor(address, payload)
    except (BgpConflictError, BgpNotFoundError) as exc:
        raise _translate(exc, "neighbor") from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="bgp.neighbor.update",
        resource_type="bgp_neighbor",
        resource_id=address,
        details={
            "address": address,
            "fields": sorted(payload.model_fields_set),
            "password_set": bool("password" in payload.model_fields_set and payload.password),
        },
    )
    return config


@router.delete("/neighbors/{address}", response_model=BgpConfigRead)
async def delete_neighbor(
    address: str,
    request: Request,
    service: BgpServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> BgpConfigRead:
    try:
        config = await service.delete_neighbor(address)
    except (BgpConflictError, BgpNotFoundError) as exc:
        raise _translate(exc, "neighbor") from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="bgp.neighbor.delete",
        resource_type="bgp_neighbor",
        resource_id=address,
        details={"address": address},
    )
    return config


# ---------------------------------------------------------------------------
# Advertised networks
# ---------------------------------------------------------------------------


@router.post("/networks", response_model=BgpConfigRead)
async def create_network(
    payload: BgpNetworkCreate,
    request: Request,
    service: BgpServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> BgpConfigRead:
    try:
        config = await service.add_network(payload)
    except (BgpConflictError, BgpNotFoundError) as exc:
        raise _translate(exc, "network") from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="bgp.network.create",
        resource_type="bgp_network",
        resource_id=payload.prefix,
        details={"af": payload.af, "prefix": payload.prefix},
    )
    return config


@router.delete("/networks", response_model=BgpConfigRead)
async def delete_network(
    network: Annotated[BgpNetworkCreate, Query()],
    request: Request,
    service: BgpServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> BgpConfigRead:
    try:
        config = await service.delete_network(network.af, network.prefix)
    except (BgpConflictError, BgpNotFoundError) as exc:
        raise _translate(exc, "network") from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="bgp.network.delete",
        resource_type="bgp_network",
        resource_id=network.prefix,
        details={"af": network.af, "prefix": network.prefix},
    )
    return config


# ---------------------------------------------------------------------------
# Peer groups
# ---------------------------------------------------------------------------


@router.post("/peer-groups", response_model=BgpConfigRead)
async def create_peer_group(
    payload: BgpPeerGroupCreate,
    request: Request,
    service: BgpServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> BgpConfigRead:
    try:
        config = await service.create_peer_group(payload)
    except (BgpConflictError, BgpNotFoundError) as exc:
        raise _translate(exc, "peer_group") from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="bgp.peer_group.create",
        resource_type="bgp_peer_group",
        resource_id=payload.name,
        details={
            "name": payload.name,
            "remote_as": payload.remote_as,
            "password_set": bool(payload.password),
        },
    )
    return config


@router.patch("/peer-groups/{name}", response_model=BgpConfigRead)
async def update_peer_group(
    name: str,
    payload: BgpPeerGroupUpdate,
    request: Request,
    service: BgpServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> BgpConfigRead:
    try:
        config = await service.update_peer_group(name, payload)
    except (BgpConflictError, BgpNotFoundError) as exc:
        raise _translate(exc, "peer_group") from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="bgp.peer_group.update",
        resource_type="bgp_peer_group",
        resource_id=name,
        details={
            "name": name,
            "fields": sorted(payload.model_fields_set),
            "password_set": bool("password" in payload.model_fields_set and payload.password),
        },
    )
    return config


@router.delete("/peer-groups/{name}", response_model=BgpConfigRead)
async def delete_peer_group(
    name: str,
    request: Request,
    service: BgpServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> BgpConfigRead:
    try:
        config = await service.delete_peer_group(name)
    except (BgpConflictError, BgpNotFoundError) as exc:
        raise _translate(exc, "peer_group") from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="bgp.peer_group.delete",
        resource_type="bgp_peer_group",
        resource_id=name,
        details={"name": name},
    )
    return config


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@router.get("/status", response_model=BgpStatus)
async def get_bgp_status(service: BgpServiceDep, _current_user: CurrentUser) -> BgpStatus:
    return await service.get_status()
