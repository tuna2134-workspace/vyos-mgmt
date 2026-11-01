from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Message(BaseModel):
    message: str


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    details: dict[str, Any] | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class TimestampedModel(ApiModel):
    created_at: datetime
    updated_at: datetime
