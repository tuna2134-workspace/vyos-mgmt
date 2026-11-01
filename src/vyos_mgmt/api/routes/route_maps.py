"""Route-map management endpoints.

Route maps are policy objects that BGP neighbors and peer groups reference for
import/export filtering.  Reads are available to every authenticated role;
mutations require operator or admin.  Domain failures are translated into the
stable error codes from the API contract.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Request, Response, status

from vyos_mgmt.api.deps import (
    CurrentUser,
    OperatorUser,
    RouteMapServiceDep,
    RouterDep,
    SessionDep,
)
from vyos_mgmt.core.errors import AppError, conflict, not_found
from vyos_mgmt.db.models import Router, User
from vyos_mgmt.schemas.route_map import (
    RouteMapCreate,
    RouteMapList,
    RouteMapRead,
    RouteMapRuleCreate,
    RouteMapRuleUpdate,
    RouteMapUpdate,
)
from vyos_mgmt.services.audit import record_audit
from vyos_mgmt.services.route_map_service import (
    RouteMapExistsError,
    RouteMapInUseError,
    RouteMapNotFoundError,
    RouteMapPrefixListNotFoundError,
    RouteMapRuleExistsError,
    RouteMapRuleNotFoundError,
    RouteMapValidationError,
)

router = APIRouter(prefix="/routers/{router_id}/route-maps", tags=["route-maps"])

RuleNumber = Annotated[int, Path(ge=1, le=65_535)]


def _translate(exc: Exception) -> AppError:
    if isinstance(exc, RouteMapInUseError):
        return conflict(
            "route_map_in_use",
            str(exc),
            details={"used_by": exc.used_by},
        )
    if isinstance(exc, RouteMapRuleExistsError):
        return conflict("rule_exists", str(exc))
    if isinstance(exc, RouteMapExistsError):
        return conflict("route_map_exists", str(exc))
    if isinstance(exc, RouteMapRuleNotFoundError):
        return not_found("rule_not_found", str(exc))
    if isinstance(exc, RouteMapNotFoundError):
        return not_found("route_map_not_found", str(exc))
    if isinstance(exc, RouteMapPrefixListNotFoundError):
        return AppError(
            422,
            "prefix_list_not_found",
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
    if isinstance(exc, RouteMapValidationError):
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


def _rule_details(
    name: str, number: int, payload: RouteMapRuleCreate | RouteMapRuleUpdate
) -> dict[str, Any]:
    details = {
        "name": name,
        **payload.model_dump(mode="json"),
    }
    details["number"] = number
    return details


# ---------------------------------------------------------------------------
# Route maps
# ---------------------------------------------------------------------------


@router.get("", response_model=RouteMapList)
async def list_route_maps(service: RouteMapServiceDep, _current_user: CurrentUser) -> RouteMapList:
    return await service.list()


@router.post("", response_model=RouteMapRead, status_code=status.HTTP_201_CREATED)
async def create_route_map(
    payload: RouteMapCreate,
    request: Request,
    service: RouteMapServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> RouteMapRead:
    try:
        route_map = await service.create(payload)
    except (RouteMapExistsError, RouteMapNotFoundError) as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="route_map.create",
        resource_type="route_map",
        resource_id=payload.name,
        details={"name": payload.name, "description": payload.description},
    )
    return route_map


@router.get("/{name}", response_model=RouteMapRead)
async def get_route_map(
    name: str, service: RouteMapServiceDep, _current_user: CurrentUser
) -> RouteMapRead:
    try:
        return await service.get(name)
    except RouteMapNotFoundError as exc:
        raise _translate(exc) from exc


@router.put("/{name}", response_model=RouteMapRead)
async def update_route_map(
    name: str,
    payload: RouteMapUpdate,
    request: Request,
    service: RouteMapServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> RouteMapRead:
    try:
        route_map = await service.update(name, payload)
    except (RouteMapNotFoundError, RouteMapValidationError) as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="route_map.update",
        resource_type="route_map",
        resource_id=name,
        details={"name": name, "description": payload.description},
    )
    return route_map


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route_map(
    name: str,
    request: Request,
    service: RouteMapServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> Response:
    try:
        await service.delete(name)
    except (RouteMapNotFoundError, RouteMapInUseError) as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="route_map.delete",
        resource_type="route_map",
        resource_id=name,
        details={"name": name},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


@router.post("/{name}/rules", response_model=RouteMapRead)
async def create_rule(
    name: str,
    payload: RouteMapRuleCreate,
    request: Request,
    service: RouteMapServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> RouteMapRead:
    try:
        route_map = await service.create_rule(name, payload)
    except (
        RouteMapNotFoundError,
        RouteMapRuleExistsError,
        RouteMapValidationError,
    ) as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="route_map.rule.create",
        resource_type="route_map_rule",
        resource_id=f"{name}:{payload.number}",
        details=_rule_details(name, payload.number, payload),
    )
    return route_map


@router.put("/{name}/rules/{number}", response_model=RouteMapRead)
async def update_rule(
    name: str,
    number: RuleNumber,
    payload: RouteMapRuleUpdate,
    request: Request,
    service: RouteMapServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> RouteMapRead:
    try:
        route_map = await service.update_rule(name, number, payload)
    except (
        RouteMapNotFoundError,
        RouteMapRuleNotFoundError,
        RouteMapValidationError,
    ) as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="route_map.rule.update",
        resource_type="route_map_rule",
        resource_id=f"{name}:{number}",
        details=_rule_details(name, number, payload),
    )
    return route_map


@router.delete("/{name}/rules/{number}", response_model=RouteMapRead)
async def delete_rule(
    name: str,
    number: RuleNumber,
    request: Request,
    service: RouteMapServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> RouteMapRead:
    try:
        route_map = await service.delete_rule(name, number)
    except (
        RouteMapNotFoundError,
        RouteMapRuleNotFoundError,
    ) as exc:
        raise _translate(exc) from exc

    await _audit(
        session,
        request,
        actor,
        device,
        action="route_map.rule.delete",
        resource_type="route_map_rule",
        resource_id=f"{name}:{number}",
        details={"name": name, "number": number},
    )
    return route_map
