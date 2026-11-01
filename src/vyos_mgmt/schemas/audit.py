from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from vyos_mgmt.schemas.common import ApiModel


class AuditLogRead(ApiModel):
    id: uuid.UUID
    actor_username: str
    router_id: uuid.UUID | None = None
    router_name: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    status: str
    details: dict[str, Any] | None = None
    request_id: str | None = None
    created_at: datetime


class AuditLogList(ApiModel):
    items: list[AuditLogRead]
    total: int
