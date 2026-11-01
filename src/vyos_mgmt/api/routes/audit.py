"""Audit-log read endpoint (admin only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from vyos_mgmt.api.deps import AdminUser, SessionDep
from vyos_mgmt.db.models import AuditLog
from vyos_mgmt.schemas.audit import AuditLogList, AuditLogRead

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditLogList)
async def list_audit_logs(
    _admin: AdminUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditLogList:
    total = await session.scalar(select(func.count()).select_from(AuditLog))
    rows = list(
        await session.scalars(
            select(AuditLog)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return AuditLogList(
        items=[AuditLogRead.model_validate(row) for row in rows],
        total=int(total or 0),
    )
