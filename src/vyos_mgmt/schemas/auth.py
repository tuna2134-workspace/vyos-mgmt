from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from vyos_mgmt.db.models import UserRole
from vyos_mgmt.schemas.common import ApiModel


class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    remember_me: bool = False

    @field_validator("username")
    @classmethod
    def _normalise_username(cls, value: str) -> str:
        return value.strip().lower()


class UserRead(ApiModel):
    id: uuid.UUID
    username: str
    email: str | None
    role: UserRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TokenResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead


class ChangePasswordRequest(ApiModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=128)
