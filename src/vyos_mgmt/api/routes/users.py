"""User administration (admin only)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vyos_mgmt.api.deps import AdminUser, SessionDep
from vyos_mgmt.core.errors import conflict, not_found
from vyos_mgmt.core.security import hash_password
from vyos_mgmt.db.models import RefreshToken, User, UserRole
from vyos_mgmt.schemas.auth import UserRead
from vyos_mgmt.schemas.user import UserCreate, UserList, UserUpdate
from vyos_mgmt.services.audit import record_audit

router = APIRouter(prefix="/users", tags=["users"])


async def _active_admin_count(session: AsyncSession) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
    )
    return int(count or 0)


async def _get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise not_found("user_not_found", f"User {user_id} was not found")
    return user


async def _revoke_tokens(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


@router.get("", response_model=UserList)
async def list_users(_admin: AdminUser, session: SessionDep) -> UserList:
    result = await session.scalars(select(User).order_by(User.username))
    users = list(result)
    return UserList(items=[UserRead.model_validate(user) for user in users], total=len(users))


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    request: Request,
    admin: AdminUser,
    session: SessionDep,
) -> UserRead:
    existing = await session.scalar(select(User).where(User.username == payload.username))
    if existing is not None:
        raise conflict("user_exists", f"User '{payload.username}' already exists")

    user = User(
        username=payload.username,
        email=str(payload.email) if payload.email else None,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise conflict("user_exists", f"User '{payload.username}' already exists") from exc
    await session.refresh(user)

    await record_audit(
        session,
        action="user.create",
        resource_type="user",
        actor=admin,
        request=request,
        resource_id=str(user.id),
        details={"username": user.username, "role": user.role.value},
    )
    return UserRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    request: Request,
    admin: AdminUser,
    session: SessionDep,
) -> UserRead:
    user = await _get_user(session, user_id)
    fields = payload.model_fields_set

    new_role = payload.role if "role" in fields and payload.role is not None else user.role
    new_active = (
        payload.is_active
        if "is_active" in fields and payload.is_active is not None
        else user.is_active
    )
    if (
        user.role == UserRole.ADMIN
        and user.is_active
        and not (new_role == UserRole.ADMIN and new_active)
    ):
        if await _active_admin_count(session) <= 1:
            raise conflict(
                "last_admin",
                "Cannot demote or deactivate the last active administrator",
            )

    if "email" in fields:
        user.email = str(payload.email) if payload.email else None
    if "role" in fields and payload.role is not None:
        user.role = payload.role
    if "is_active" in fields and payload.is_active is not None:
        user.is_active = payload.is_active
    if "password" in fields and payload.password:
        user.password_hash = hash_password(payload.password)
        await _revoke_tokens(session, user.id)

    await session.flush()
    await session.refresh(user)

    details: dict[str, Any] = {
        "username": user.username,
        "fields": sorted(fields),
        "password_set": bool("password" in fields and payload.password),
    }
    await record_audit(
        session,
        action="user.update",
        resource_type="user",
        actor=admin,
        request=request,
        resource_id=str(user.id),
        details=details,
    )
    return UserRead.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    request: Request,
    admin: AdminUser,
    session: SessionDep,
) -> Response:
    user = await _get_user(session, user_id)
    if user.id == admin.id:
        raise conflict("cannot_delete_self", "You cannot delete your own account")
    if user.role == UserRole.ADMIN and user.is_active:
        if await _active_admin_count(session) <= 1:
            raise conflict("last_admin", "Cannot delete the last active administrator")

    await record_audit(
        session,
        action="user.delete",
        resource_type="user",
        actor=admin,
        request=request,
        resource_id=str(user.id),
        details={"username": user.username, "role": user.role.value},
    )
    await session.delete(user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
