"""OSPFv2/OSPFv3 management endpoints.

The feature is selected by the ``v2``/``v3`` path segment.  Reads are available
to every authenticated role; area/interface/redistribution mutations require
operator or admin, while deleting a whole OSPF process requires admin.
Domain failures are translated into the stable error codes from the contract.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Path, Request, Response, status

from vyos_mgmt.api.deps import (
    AdminUser,
    CurrentUser,
    OperatorUser,
    OspfServiceDep,
    RouterDep,
    SessionDep,
)
from vyos_mgmt.core.errors import AppError, conflict, not_found
from vyos_mgmt.db.models import Router, User
from vyos_mgmt.schemas.ospf import (
    OSPF_VERSIONS,
    OspfAreaCreate,
    OspfAreaUpdate,
    OspfConfigRead,
    OspfGlobal,
    OspfInterfaceCreate,
    OspfInterfaceUpdate,
    OspfRedistributeCreate,
    OspfRedistributeUpdate,
    OspfStatus,
    OspfVersion,
    canonicalize_area_id,
    validate_interface_name,
)
from vyos_mgmt.services.audit import record_audit
from vyos_mgmt.services.ospf_service import (
    OspfAreaExistsError,
    OspfAreaInUseError,
    OspfAreaNotFoundError,
    OspfAreaReferenceError,
    OspfError,
    OspfInterfaceExistsError,
    OspfInterfaceNotFoundError,
    OspfRedistributeExistsError,
    OspfRedistributeNotFoundError,
    OspfRouteMapNotFoundError,
    OspfValidationError,
)

router = APIRouter(prefix="/routers/{router_id}/ospf", tags=["ospf"])


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------


def _version_path(version: Annotated[str, Path(description="OSPF version")]) -> OspfVersion:
    """Narrow the path segment to ``v2``/``v3``, returning 404 otherwise."""

    if version not in OSPF_VERSIONS:
        raise not_found(
            "version_not_found",
            f"OSPF version '{version}' is not supported; use v2 or v3",
        )
    return cast(OspfVersion, version)


OspfVersionPath = Annotated[OspfVersion, Depends(_version_path)]


def _area_id_path(area_id: Annotated[str, Path(description="OSPF area ID")]) -> str:
    """Canonicalise the area path parameter, returning a 422 envelope on bad input."""

    try:
        return canonicalize_area_id(area_id)
    except ValueError as exc:
        raise AppError(
            422,
            "validation_error",
            "The request payload is invalid",
            details=[
                {
                    "loc": ["path", "area_id"],
                    "msg": str(exc),
                    "type": "value_error",
                    "input": area_id,
                }
            ],
        ) from exc


OspfAreaIdPath = Annotated[str, Depends(_area_id_path)]


def _interface_name_path(name: Annotated[str, Path(description="Interface name")]) -> str:
    try:
        return validate_interface_name(name)
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


OspfInterfaceNamePath = Annotated[str, Depends(_interface_name_path)]


# ---------------------------------------------------------------------------
# Error / audit helpers
# ---------------------------------------------------------------------------


def _translate(exc: Exception) -> AppError:
    if isinstance(exc, OspfAreaInUseError):
        return conflict("ospf_area_in_use", str(exc), details={"used_by": exc.used_by})
    if isinstance(exc, OspfAreaExistsError):
        return conflict("ospf_area_exists", str(exc))
    if isinstance(exc, OspfInterfaceExistsError):
        return conflict("ospf_interface_exists", str(exc))
    if isinstance(exc, OspfRedistributeExistsError):
        return conflict("ospf_redistribute_exists", str(exc))
    if isinstance(exc, OspfAreaNotFoundError):
        return not_found("ospf_area_not_found", str(exc))
    if isinstance(exc, OspfInterfaceNotFoundError):
        return not_found("ospf_interface_not_found", str(exc))
    if isinstance(exc, OspfRedistributeNotFoundError):
        return not_found("ospf_redistribute_not_found", str(exc))
    if isinstance(exc, OspfAreaReferenceError):
        return AppError(
            422,
            "ospf_area_not_found",
            str(exc),
            details=[
                {
                    "loc": ["body", exc.field],
                    "msg": str(exc),
                    "type": "value_error",
                    "input": exc.value,
                }
            ],
        )
    if isinstance(exc, OspfRouteMapNotFoundError):
        return AppError(
            422,
            "route_map_not_found",
            str(exc),
            details=[
                {
                    "loc": ["body", exc.field],
                    "msg": str(exc),
                    "type": "value_error",
                    "input": exc.value,
                }
            ],
        )
    if isinstance(exc, OspfValidationError):
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


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@router.get("/{version}", response_model=OspfConfigRead)
async def get_ospf_config(
    version: OspfVersionPath,
    service: OspfServiceDep,
    _current_user: CurrentUser,
) -> OspfConfigRead:
    return await service.get_config(version)


@router.put("/{version}/global", response_model=OspfConfigRead)
async def update_ospf_global(
    version: OspfVersionPath,
    payload: OspfGlobal,
    request: Request,
    service: OspfServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> OspfConfigRead:
    try:
        config = await service.update_global(version, payload)
    except OspfError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="ospf.global.update",
        resource_type="ospf_process",
        resource_id=version,
        details={"version": version, **payload.model_dump(mode="json")},
    )
    return config


@router.delete("/{version}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ospf_process(
    version: OspfVersionPath,
    request: Request,
    service: OspfServiceDep,
    device: RouterDep,
    actor: AdminUser,
    session: SessionDep,
) -> Response:
    await service.delete_process(version)

    await _audit(
        session,
        request,
        actor,
        device,
        action="ospf.delete",
        resource_type="ospf_process",
        resource_id=version,
        details={"version": version},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Areas
# ---------------------------------------------------------------------------


@router.post("/{version}/areas", response_model=OspfConfigRead, status_code=201)
async def create_ospf_area(
    version: OspfVersionPath,
    payload: OspfAreaCreate,
    request: Request,
    service: OspfServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> OspfConfigRead:
    try:
        config = await service.create_area(version, payload)
    except OspfError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="ospf.area.create",
        resource_type="ospf_area",
        resource_id=payload.area_id,
        details={"version": version, **payload.model_dump(mode="json")},
    )
    return config


@router.put("/{version}/areas/{area_id}", response_model=OspfConfigRead)
async def update_ospf_area(
    version: OspfVersionPath,
    area_id: OspfAreaIdPath,
    payload: OspfAreaUpdate,
    request: Request,
    service: OspfServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> OspfConfigRead:
    try:
        config = await service.update_area(version, area_id, payload)
    except OspfError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="ospf.area.update",
        resource_type="ospf_area",
        resource_id=area_id,
        details={"version": version, "area_id": area_id, **payload.model_dump(mode="json")},
    )
    return config


@router.delete("/{version}/areas/{area_id}", response_model=OspfConfigRead)
async def delete_ospf_area(
    version: OspfVersionPath,
    area_id: OspfAreaIdPath,
    request: Request,
    service: OspfServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> OspfConfigRead:
    try:
        config = await service.delete_area(version, area_id)
    except OspfError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="ospf.area.delete",
        resource_type="ospf_area",
        resource_id=area_id,
        details={"version": version, "area_id": area_id},
    )
    return config


# ---------------------------------------------------------------------------
# Interfaces
# ---------------------------------------------------------------------------


@router.post("/{version}/interfaces", response_model=OspfConfigRead, status_code=201)
async def create_ospf_interface(
    version: OspfVersionPath,
    payload: OspfInterfaceCreate,
    request: Request,
    service: OspfServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> OspfConfigRead:
    try:
        config = await service.create_interface(version, payload)
    except OspfError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="ospf.interface.create",
        resource_type="ospf_interface",
        resource_id=payload.name,
        details={"version": version, **payload.model_dump(mode="json")},
    )
    return config


@router.put("/{version}/interfaces/{name}", response_model=OspfConfigRead)
async def update_ospf_interface(
    version: OspfVersionPath,
    name: OspfInterfaceNamePath,
    payload: OspfInterfaceUpdate,
    request: Request,
    service: OspfServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> OspfConfigRead:
    try:
        config = await service.update_interface(version, name, payload)
    except OspfError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="ospf.interface.update",
        resource_type="ospf_interface",
        resource_id=name,
        details={"version": version, "name": name, **payload.model_dump(mode="json")},
    )
    return config


@router.delete("/{version}/interfaces/{name}", response_model=OspfConfigRead)
async def delete_ospf_interface(
    version: OspfVersionPath,
    name: OspfInterfaceNamePath,
    request: Request,
    service: OspfServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> OspfConfigRead:
    try:
        config = await service.delete_interface(version, name)
    except OspfError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="ospf.interface.delete",
        resource_type="ospf_interface",
        resource_id=name,
        details={"version": version, "name": name},
    )
    return config


# ---------------------------------------------------------------------------
# Redistribution
# ---------------------------------------------------------------------------


@router.post("/{version}/redistribute", response_model=OspfConfigRead, status_code=201)
async def create_ospf_redistribute(
    version: OspfVersionPath,
    payload: OspfRedistributeCreate,
    request: Request,
    service: OspfServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> OspfConfigRead:
    try:
        config = await service.create_redistribute(version, payload)
    except OspfError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="ospf.redistribute.create",
        resource_type="ospf_redistribute",
        resource_id=payload.source,
        details={"version": version, **payload.model_dump(mode="json")},
    )
    return config


@router.put("/{version}/redistribute/{source}", response_model=OspfConfigRead)
async def update_ospf_redistribute(
    version: OspfVersionPath,
    source: str,
    payload: OspfRedistributeUpdate,
    request: Request,
    service: OspfServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> OspfConfigRead:
    try:
        config = await service.update_redistribute(version, source, payload)
    except OspfError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="ospf.redistribute.update",
        resource_type="ospf_redistribute",
        resource_id=source,
        details={"version": version, "source": source, **payload.model_dump(mode="json")},
    )
    return config


@router.delete("/{version}/redistribute/{source}", response_model=OspfConfigRead)
async def delete_ospf_redistribute(
    version: OspfVersionPath,
    source: str,
    request: Request,
    service: OspfServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> OspfConfigRead:
    try:
        config = await service.delete_redistribute(version, source)
    except OspfError as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="ospf.redistribute.delete",
        resource_type="ospf_redistribute",
        resource_id=source,
        details={"version": version, "source": source},
    )
    return config


# ---------------------------------------------------------------------------
# Operational status
# ---------------------------------------------------------------------------


@router.get("/{version}/status", response_model=OspfStatus)
async def get_ospf_status(
    version: OspfVersionPath,
    service: OspfServiceDep,
    _current_user: CurrentUser,
) -> OspfStatus:
    return await service.get_status(version)
