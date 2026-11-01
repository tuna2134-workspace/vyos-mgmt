"""Router (device) inventory endpoints."""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vyos_mgmt.api.deps import (
    AdminUser,
    CurrentUser,
    RouterDep,
    SessionDep,
    SettingsDep,
)
from vyos_mgmt.config import Settings
from vyos_mgmt.core.crypto import SecretDecryptionError, encrypt_secret
from vyos_mgmt.core.errors import AppError, conflict, not_found
from vyos_mgmt.db.models import Router, RouterDriver
from vyos_mgmt.schemas.router import (
    RouterCreate,
    RouterList,
    RouterRead,
    RouterUpdate,
    SystemInfo,
)
from vyos_mgmt.services.audit import record_audit
from vyos_mgmt.services.vyos.base import (
    VyosCommandError,
    VyosConfigurationError,
    VyosConnectionError,
    VyosError,
)
from vyos_mgmt.services.vyos.factory import build_driver

router = APIRouter(prefix="/routers", tags=["routers"])


def _read(device: Router) -> RouterRead:
    data = RouterRead.model_validate(device)
    return data.model_copy(update={"api_key_configured": bool(device.api_key_encrypted)})


async def _name_taken(
    session: AsyncSession, name: str, *, exclude_id: uuid.UUID | None = None
) -> bool:
    statement = select(Router.id).where(func.lower(Router.name) == name.lower())
    if exclude_id is not None:
        statement = statement.where(Router.id != exclude_id)
    return (await session.scalar(statement)) is not None


def _encrypt_api_key(api_key: str, settings: Settings) -> str:
    return encrypt_secret(api_key, secret=settings.secret_key.get_secret_value())


@router.get("", response_model=RouterList)
async def list_routers(_current_user: CurrentUser, session: SessionDep) -> RouterList:
    devices = list(await session.scalars(select(Router).order_by(func.lower(Router.name))))
    return RouterList(items=[_read(device) for device in devices], total=len(devices))


@router.post("", response_model=RouterRead, status_code=status.HTTP_201_CREATED)
async def create_router(
    payload: RouterCreate,
    request: Request,
    admin: AdminUser,
    session: SessionDep,
    settings: SettingsDep,
) -> RouterRead:
    if payload.driver == RouterDriver.PYVYOS and not payload.api_key:
        raise AppError(
            400,
            "api_key_required",
            "An API key is required for the pyvyos driver",
        )
    if await _name_taken(session, payload.name):
        raise conflict("router_exists", f"Router '{payload.name}' already exists")

    device = Router(
        name=payload.name,
        host=payload.host,
        port=payload.port,
        protocol=payload.protocol,
        api_key_encrypted=(
            _encrypt_api_key(payload.api_key, settings) if payload.api_key else None
        ),
        verify_tls=payload.verify_tls,
        driver=payload.driver,
        description=payload.description,
        created_by_id=admin.id,
    )
    session.add(device)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise conflict("router_exists", f"Router '{payload.name}' already exists") from exc
    await session.refresh(device)

    await record_audit(
        session,
        action="router.create",
        resource_type="router",
        actor=admin,
        request=request,
        router=device,
        resource_id=str(device.id),
        details={
            "name": device.name,
            "host": device.host,
            "port": device.port,
            "driver": device.driver.value,
        },
    )
    return _read(device)


@router.get("/{router_id}", response_model=RouterRead)
async def get_router_detail(
    router_id: uuid.UUID, _current_user: CurrentUser, session: SessionDep
) -> RouterRead:
    device = await session.get(Router, router_id)
    if device is None:
        raise not_found("router_not_found", f"Router {router_id} was not found")
    return _read(device)


@router.patch("/{router_id}", response_model=RouterRead)
async def update_router(
    router_id: uuid.UUID,
    payload: RouterUpdate,
    request: Request,
    admin: AdminUser,
    session: SessionDep,
    settings: SettingsDep,
) -> RouterRead:
    device = await session.get(Router, router_id)
    if device is None:
        raise not_found("router_not_found", f"Router {router_id} was not found")

    fields = payload.model_fields_set
    effective_name = device.name
    if "name" in fields and payload.name is not None:
        if payload.name.lower() != device.name.lower() and await _name_taken(
            session, payload.name, exclude_id=device.id
        ):
            raise conflict("router_exists", f"Router '{payload.name}' already exists")
        device.name = payload.name
        effective_name = payload.name
    if "host" in fields and payload.host is not None:
        device.host = payload.host
    if "port" in fields and payload.port is not None:
        device.port = payload.port
    if "protocol" in fields and payload.protocol is not None:
        device.protocol = payload.protocol
    if "verify_tls" in fields and payload.verify_tls is not None:
        device.verify_tls = payload.verify_tls
    if "driver" in fields and payload.driver is not None:
        device.driver = payload.driver
    if "description" in fields:
        device.description = payload.description
    if "api_key" in fields:
        # ``api_key: ""`` (or null) clears the stored credential.
        device.api_key_encrypted = (
            _encrypt_api_key(payload.api_key, settings) if payload.api_key else None
        )

    # Clearing an existing key is allowed (the contract's ``api_key: ""``
    # semantics); switching *to* pyvyos without a key is not.
    if "driver" in fields and device.driver == RouterDriver.PYVYOS and not device.api_key_encrypted:
        raise AppError(
            400,
            "api_key_required",
            "An API key is required for the pyvyos driver",
        )

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise conflict("router_exists", f"Router '{effective_name}' already exists") from exc
    await session.refresh(device)

    details: dict[str, Any] = {
        "name": device.name,
        "fields": sorted(fields),
        "api_key_changed": "api_key" in fields,
    }
    await record_audit(
        session,
        action="router.update",
        resource_type="router",
        actor=admin,
        request=request,
        router=device,
        resource_id=str(device.id),
        details=details,
    )
    return _read(device)


@router.delete("/{router_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_router(
    router_id: uuid.UUID,
    request: Request,
    admin: AdminUser,
    session: SessionDep,
) -> Response:
    device = await session.get(Router, router_id)
    if device is None:
        raise not_found("router_not_found", f"Router {router_id} was not found")

    await record_audit(
        session,
        action="router.delete",
        resource_type="router",
        actor=admin,
        request=request,
        router=device,
        resource_id=str(device.id),
        details={"name": device.name, "host": device.host},
    )
    await session.delete(device)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{router_id}/test", response_model=SystemInfo)
async def test_router(
    router: RouterDep,
    settings: SettingsDep,
    _current_user: CurrentUser,
) -> SystemInfo:
    """Probe a device without failing the request when it is unreachable."""

    started = time.perf_counter()
    try:
        driver = build_driver(router, settings)
        try:
            return await driver.get_system_info()
        finally:
            await driver.close()
    except SecretDecryptionError:
        return SystemInfo(
            driver=router.driver,
            reachable=False,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            error="The stored API key could not be decrypted",
        )
    except VyosError as exc:
        return SystemInfo(
            driver=router.driver,
            reachable=False,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            error=str(exc),
        )


@router.get("/{router_id}/system", response_model=SystemInfo)
async def get_router_system(
    router: RouterDep,
    settings: SettingsDep,
    _current_user: CurrentUser,
) -> SystemInfo:
    driver = None
    try:
        driver = build_driver(router, settings)
        return await driver.get_system_info()
    except VyosConfigurationError as exc:
        raise AppError(502, "router_unreachable", str(exc)) from exc
    except VyosConnectionError as exc:
        raise AppError(502, "router_unreachable", str(exc)) from exc
    except VyosCommandError as exc:
        raise AppError(502, "router_command_failed", str(exc)) from exc
    finally:
        if driver is not None:
            await driver.close()
