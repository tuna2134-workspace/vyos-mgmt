"""FastAPI dependencies shared by all routes.

Authentication is bearer-token based; roles are hierarchical and checked with
:func:`require_min_role`.  Device drivers are request-scoped: one driver per
request, always closed by the generator dependency.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from vyos_mgmt.config import Settings
from vyos_mgmt.config import get_settings as _get_settings
from vyos_mgmt.core.errors import AppError, forbidden, not_found, unauthorized
from vyos_mgmt.core.security import CSRF_HEADER, CSRF_VALUE, TokenError, decode_access_token
from vyos_mgmt.db.models import Router, User, UserRole
from vyos_mgmt.db.session import get_db
from vyos_mgmt.services.bgp_service import BgpService
from vyos_mgmt.services.ospf_service import OspfService
from vyos_mgmt.services.prefix_list_service import PrefixListService
from vyos_mgmt.services.route_map_service import RouteMapService
from vyos_mgmt.services.static_route_service import StaticRouteService
from vyos_mgmt.services.vyos.base import VyosDriver
from vyos_mgmt.services.vyos.factory import build_driver
from vyos_mgmt.services.wireguard_service import WireGuardService

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="Bearer")


def get_settings(request: Request) -> Settings:
    """Return the settings bound to the running application.

    Using ``app.state`` (rather than the process-wide cached settings) keeps
    ``create_app(settings=...)`` fully self-contained, which tests and
    multi-app deployments rely on.
    """

    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings
    return _get_settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Authentication / authorization
# ---------------------------------------------------------------------------


async def get_current_user(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    try:
        user_id, _claims = decode_access_token(credentials.credentials, settings)
    except TokenError as exc:
        raise unauthorized("Invalid or expired access token") from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized("User account is missing or inactive")
    request.state.user = user
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_min_role(minimum: UserRole) -> Callable[..., User]:
    """Build a dependency enforcing a minimum hierarchical role."""

    async def _dependency(current_user: CurrentUser) -> User:
        if current_user.role.level < minimum.level:
            raise forbidden(f"This action requires the {minimum.value} role or higher")
        return current_user

    return _dependency


ViewerUser = Annotated[User, Depends(require_min_role(UserRole.VIEWER))]
OperatorUser = Annotated[User, Depends(require_min_role(UserRole.OPERATOR))]
AdminUser = Annotated[User, Depends(require_min_role(UserRole.ADMIN))]


def require_csrf(request: Request) -> None:
    """Validate the double-submit style CSRF header on refresh/logout."""

    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise AppError(
            403,
            "csrf_failed",
            "Missing or invalid X-Requested-With header",
        )


CsrfProtected = Annotated[None, Depends(require_csrf)]


# ---------------------------------------------------------------------------
# Client address (rate limiting, refresh-token bookkeeping)
# ---------------------------------------------------------------------------


def get_client_ip(request: Request, settings: SettingsDep) -> str:
    """Best-effort client IP, honouring proxy headers only when configured.

    ``X-Forwarded-For`` is only trusted when ``TRUSTED_PROXY_HEADERS`` is true;
    the left-most entry is the original client when the proxy appends values.
    """

    if settings.trusted_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            candidate = forwarded.split(",")[0].strip()
            if candidate:
                return candidate
        real_ip = request.headers.get("x-real-ip")
        if real_ip and real_ip.strip():
            return real_ip.strip()
    return request.client.host if request.client else "unknown"


ClientIP = Annotated[str, Depends(get_client_ip)]


# ---------------------------------------------------------------------------
# Routers / drivers / services
# ---------------------------------------------------------------------------


async def get_router(router_id: uuid.UUID, session: SessionDep) -> Router:
    router = await session.get(Router, router_id)
    if router is None:
        raise not_found("router_not_found", f"Router {router_id} was not found")
    return router


RouterDep = Annotated[Router, Depends(get_router)]


async def get_driver(router: RouterDep, settings: SettingsDep) -> AsyncIterator[VyosDriver]:
    driver = build_driver(router, settings)
    try:
        yield driver
    finally:
        await driver.close()


DriverDep = Annotated[VyosDriver, Depends(get_driver)]


async def get_bgp_service(router: RouterDep, driver: DriverDep) -> BgpService:
    return BgpService(driver, router)


BgpServiceDep = Annotated[BgpService, Depends(get_bgp_service)]


async def get_route_map_service(router: RouterDep, driver: DriverDep) -> RouteMapService:
    return RouteMapService(driver, router)


RouteMapServiceDep = Annotated[RouteMapService, Depends(get_route_map_service)]


async def get_prefix_list_service(router: RouterDep, driver: DriverDep) -> PrefixListService:
    return PrefixListService(driver, router)


PrefixListServiceDep = Annotated[PrefixListService, Depends(get_prefix_list_service)]


async def get_ospf_service(router: RouterDep, driver: DriverDep) -> OspfService:
    return OspfService(driver, router)


OspfServiceDep = Annotated[OspfService, Depends(get_ospf_service)]


async def get_static_route_service(router: RouterDep, driver: DriverDep) -> StaticRouteService:
    return StaticRouteService(driver, router)


StaticRouteServiceDep = Annotated[StaticRouteService, Depends(get_static_route_service)]


async def get_wireguard_service(router: RouterDep, driver: DriverDep) -> WireGuardService:
    return WireGuardService(driver, router)


WireGuardServiceDep = Annotated[WireGuardService, Depends(get_wireguard_service)]
