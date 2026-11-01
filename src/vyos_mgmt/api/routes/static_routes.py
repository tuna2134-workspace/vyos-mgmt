"""IPv4/IPv6 static-route endpoints.

One module manages both VyOS trees (``protocols static route`` and ``route6``).
Reads are available to every authenticated role; mutations require operator or
admin.  Domain failures are translated into the stable error codes from the API
contract, and every mutation writes an audit entry without secrets.

The prefix path parameter uses Starlette's ``path`` converter so a literal
``10.0.0.0/8`` and its URL-encoded form resolve to the same route; the prefix is
canonicalised and family-checked before it reaches the service.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response, status

from vyos_mgmt.api.deps import (
    CurrentUser,
    OperatorUser,
    RouterDep,
    SessionDep,
    StaticRouteServiceDep,
)
from vyos_mgmt.core.errors import AppError, conflict, not_found
from vyos_mgmt.db.models import Router, User
from vyos_mgmt.schemas.static_route import (
    StaticRouteCreate,
    StaticRouteFamily,
    StaticRouteList,
    StaticRouteRead,
    StaticRouteUpdate,
    canonical_route_prefix,
    route_type,
)
from vyos_mgmt.services.audit import record_audit
from vyos_mgmt.services.static_route_service import (
    StaticRouteExistsError,
    StaticRouteNotFoundError,
    StaticRouteValidationError,
)

router = APIRouter(prefix="/routers/{router_id}/static-routes", tags=["static-routes"])

FamilyPath = Annotated[StaticRouteFamily, Path(description="Address family (ipv4 or ipv6)")]
FamilyFilter = Annotated[StaticRouteFamily | None, Query(description="Filter by address family")]
PrefixPath = Annotated[str, Path(description="Static route prefix in CIDR notation")]


def _validation_error(loc: list[str], message: str, value: Any) -> AppError:
    return AppError(
        422,
        "validation_error",
        "The request payload is invalid",
        details=[
            {
                "loc": loc,
                "msg": message,
                "type": "value_error",
                "input": value,
            }
        ],
    )


def _validated_prefix(family: StaticRouteFamily, prefix: str) -> str:
    """Canonicalise a path prefix, returning 422 with a field loc on failure."""

    try:
        return canonical_route_prefix(prefix, family)
    except ValueError as exc:
        raise _validation_error(["path", "prefix"], str(exc), prefix) from exc


def _translate(exc: Exception) -> AppError:
    if isinstance(exc, StaticRouteExistsError):
        return conflict("static_route_exists", str(exc))
    if isinstance(exc, StaticRouteNotFoundError):
        return not_found("static_route_not_found", str(exc))
    if isinstance(exc, StaticRouteValidationError):
        # Dotted field names match the other modules (for example
        # ``match.ipv4_prefix_list``) so the frontend can map them to forms.
        return _validation_error(["body", exc.field], str(exc), exc.value)
    raise exc


async def _audit(
    session: SessionDep,
    request: Request,
    actor: User,
    device: Router,
    *,
    action: str,
    route: StaticRouteRead,
) -> None:
    """Record a mutation; details stay free of secrets and large payloads."""

    await record_audit(
        session,
        action=action,
        resource_type="static_route",
        actor=actor,
        request=request,
        router=device,
        resource_id=f"{route.family}:{route.prefix}",
        details={
            "family": route.family,
            "prefix": route.prefix,
            "type": route_type(route.blackhole, route.reject),
            "next_hop_count": len(route.next_hops),
        },
    )


@router.get("", response_model=StaticRouteList)
async def list_static_routes(
    service: StaticRouteServiceDep,
    _current_user: CurrentUser,
    family: FamilyFilter = None,
) -> StaticRouteList:
    """List static routes, optionally filtered by family, sorted by family+prefix."""

    return await service.list(family)


@router.post("", response_model=StaticRouteRead, status_code=status.HTTP_201_CREATED)
async def create_static_route(
    payload: StaticRouteCreate,
    request: Request,
    service: StaticRouteServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> StaticRouteRead:
    """Create one static route (409 when family+prefix already exists)."""

    try:
        route = await service.create(payload)
    except (StaticRouteExistsError, StaticRouteValidationError) as exc:
        raise _translate(exc) from exc

    await _audit(session, request, actor, device, action="static_route.create", route=route)
    return route


@router.get("/{family}/{prefix:path}", response_model=StaticRouteRead)
async def get_static_route(
    family: FamilyPath,
    prefix: PrefixPath,
    service: StaticRouteServiceDep,
    _current_user: CurrentUser,
) -> StaticRouteRead:
    """Return one static route; accepts literal and URL-encoded prefixes."""

    canonical = _validated_prefix(family, prefix)
    try:
        return await service.get(family, canonical)
    except StaticRouteNotFoundError as exc:
        raise _translate(exc) from exc


@router.put("/{family}/{prefix:path}", response_model=StaticRouteRead)
async def update_static_route(
    family: FamilyPath,
    prefix: PrefixPath,
    payload: StaticRouteUpdate,
    request: Request,
    service: StaticRouteServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> StaticRouteRead:
    """Replace the managed fields of one static route (family/prefix immutable)."""

    canonical = _validated_prefix(family, prefix)
    try:
        route = await service.update(family, canonical, payload)
    except (StaticRouteNotFoundError, StaticRouteValidationError) as exc:
        raise _translate(exc) from exc

    await _audit(session, request, actor, device, action="static_route.update", route=route)
    return route


@router.delete("/{family}/{prefix:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_static_route(
    family: FamilyPath,
    prefix: PrefixPath,
    request: Request,
    service: StaticRouteServiceDep,
    device: RouterDep,
    actor: OperatorUser,
    session: SessionDep,
) -> Response:
    """Delete one static route (204; 404 when it does not exist)."""

    canonical = _validated_prefix(family, prefix)
    try:
        existing = await service.get(family, canonical)
    except StaticRouteNotFoundError as exc:
        raise _translate(exc) from exc
    try:
        await service.delete(family, canonical)
    except StaticRouteNotFoundError as exc:
        raise _translate(exc) from exc

    await _audit(session, request, actor, device, action="static_route.delete", route=existing)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
