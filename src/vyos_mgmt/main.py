"""FastAPI application factory and ASGI entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from vyos_mgmt.api.routes import (
    audit,
    auth,
    bgp,
    meta,
    ospf,
    prefix_lists,
    route_maps,
    routers,
    static_routes,
    users,
    wireguard,
)
from vyos_mgmt.config import Settings, get_settings
from vyos_mgmt.core.crypto import SecretDecryptionError
from vyos_mgmt.core.errors import error_response, install_error_handlers
from vyos_mgmt.core.middleware import RequestContextMiddleware
from vyos_mgmt.core.security import hash_password
from vyos_mgmt.db.models import User, UserRole
from vyos_mgmt.db.session import (
    build_engine,
    dispose_engine,
    get_session_factory,
    set_engine,
)
from vyos_mgmt.schemas.user import normalise_username
from vyos_mgmt.services.vyos.base import (
    VyosCommandError,
    VyosConfigurationError,
    VyosConnectionError,
    VyosError,
    VyosPathNotFound,
)

logger = logging.getLogger("vyos_mgmt")


# ---------------------------------------------------------------------------
# Logging / bootstrap
# ---------------------------------------------------------------------------


def _configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("vyos_mgmt").setLevel(level)
    # pyvyos logs every request at INFO; keep it out of the way unless debugging.
    logging.getLogger("pyvyos").setLevel(max(level, logging.WARNING))


async def _bootstrap_admin(settings: Settings) -> None:
    """Create the first administrator when explicitly configured and no users exist."""

    username = settings.bootstrap_admin_username
    password = settings.bootstrap_admin_password
    if not username or password is None:
        return

    raw_password = password.get_secret_value()
    if len(raw_password) < 12:
        logger.error("BOOTSTRAP_ADMIN_PASSWORD is shorter than 12 characters; skipping")
        return
    try:
        username = normalise_username(username)
    except ValueError as exc:
        logger.error("BOOTSTRAP_ADMIN_USERNAME is invalid (%s); skipping", exc)
        return

    factory = get_session_factory()
    async with factory() as session:
        user_count = await session.scalar(select(func.count()).select_from(User))
        if user_count:
            return
        session.add(
            User(
                username=username,
                email=settings.bootstrap_admin_email,
                password_hash=hash_password(raw_password),
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.info("Bootstrap admin already exists; nothing to do")
            return
        logger.info("Created bootstrap administrator '%s'", username)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    _configure_logging(settings)
    set_engine(build_engine(settings))
    try:
        await _bootstrap_admin(settings)
        yield
    finally:
        await dispose_engine()


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------


class NextStaticFiles(StaticFiles):
    """Serve a Next.js static export.

    The export uses ``trailingSlash: true`` (directory + ``index.html``) and
    ships ``404.html``.  Unknown client-side routes therefore render the custom
    404 page with an HTTP 404 status instead of leaking a JSON error.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            not_found_page = Path(str(self.directory)) / "404.html"
            if not not_found_page.is_file():
                raise
            response = await super().get_response("404.html", scope)
            response.status_code = 404
        return response


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


def install_vyos_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(VyosError)
    async def _vyos_error(request: Request, exc: VyosError) -> JSONResponse:
        if isinstance(exc, VyosPathNotFound):
            status_code, code = 404, "not_found"
        elif isinstance(exc, VyosConfigurationError):
            status_code, code = 400, "router_configuration_invalid"
        elif isinstance(exc, VyosConnectionError):
            status_code, code = 502, "router_unreachable"
        elif isinstance(exc, VyosCommandError):
            status_code, code = 502, "router_command_failed"
        else:  # pragma: no cover - defensive for future error types
            status_code, code = 502, "router_unreachable"
        return error_response(request, status_code=status_code, code=code, message=str(exc))

    @app.exception_handler(SecretDecryptionError)
    async def _secret_error(request: Request, exc: SecretDecryptionError) -> JSONResponse:
        logger.error(
            "Credential decryption failed for %s %s",
            request.method,
            request.url.path,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return error_response(
            request,
            status_code=500,
            code="internal_error",
            message="The stored router credential could not be decrypted",
        )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.enable_docs else None,
        swagger_ui_oauth2_redirect_url=None,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Response-Time-Ms"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)

    install_error_handlers(app)
    install_vyos_error_handlers(app)

    prefix = settings.api_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(users.router, prefix=prefix)
    app.include_router(routers.router, prefix=prefix)
    app.include_router(bgp.router, prefix=prefix)
    app.include_router(route_maps.router, prefix=prefix)
    app.include_router(prefix_lists.router, prefix=prefix)
    app.include_router(ospf.router, prefix=prefix)
    app.include_router(static_routes.router, prefix=prefix)
    app.include_router(wireguard.router, prefix=prefix)
    app.include_router(audit.router, prefix=prefix)
    app.include_router(meta.router, prefix=prefix)

    api_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

    @app.api_route("/api", methods=api_methods, include_in_schema=False)
    @app.api_route("/api/{full_path:path}", methods=api_methods, include_in_schema=False)
    async def api_not_found(request: Request, full_path: str = "") -> JSONResponse:
        return error_response(
            request,
            status_code=404,
            code="not_found",
            message="API endpoint not found",
        )

    frontend_dir: Path = settings.frontend_dir
    if settings.serve_frontend and frontend_dir.is_dir():
        logger.info("Serving static frontend from %s", frontend_dir)
        app.mount(
            "/",
            NextStaticFiles(directory=str(frontend_dir), html=True),
            name="frontend",
        )

    return app


app = create_app()
