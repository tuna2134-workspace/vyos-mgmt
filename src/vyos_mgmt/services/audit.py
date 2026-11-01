"""Audit-trail helpers.

Audit rows are written inside the request transaction: a failed mutation is
rolled back together with its audit entry, so ``status`` currently records
successful state changes.  Callers must only pass redacted details (never
passwords, API keys or tokens).
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from vyos_mgmt.db.models import AuditLog, Router, User


async def record_audit(
    session: AsyncSession,
    *,
    action: str,
    resource_type: str,
    actor: User | None = None,
    request: Request | None = None,
    router: Router | None = None,
    resource_id: str | None = None,
    status: str = "success",
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an audit entry to the current session.

    ``router_name`` and ``actor_username`` are denormalised on purpose so the
    trail remains readable after a router or user is deleted.
    """

    entry = AuditLog(
        user_id=actor.id if actor is not None else None,
        actor_username=actor.username if actor is not None else "system",
        router_id=router.id if router is not None else None,
        router_name=router.name if router is not None else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        status=status,
        details=jsonable_encoder(details) if details is not None else None,
        request_id=getattr(request.state, "request_id", None) if request is not None else None,
    )
    session.add(entry)
    await session.flush()
    return entry
