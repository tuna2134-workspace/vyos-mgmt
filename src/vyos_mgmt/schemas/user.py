from __future__ import annotations

import re

from pydantic import EmailStr, Field, field_validator

from vyos_mgmt.db.models import UserRole
from vyos_mgmt.schemas.common import ApiModel

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def normalise_username(value: str) -> str:
    value = value.strip().lower()
    if not USERNAME_RE.match(value):
        raise ValueError(
            "Username must be 3-64 characters, start with a letter or digit and "
            "contain only lowercase letters, digits, dot, underscore or hyphen"
        )
    return value


class UserCreate(ApiModel):
    username: str
    email: EmailStr | None = None
    password: str = Field(min_length=12, max_length=128)
    role: UserRole = UserRole.VIEWER

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        return normalise_username(value)


class UserUpdate(ApiModel):
    email: EmailStr | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=128)


class UserList(ApiModel):
    items: list[UserRead]
    total: int


# Imported late to keep the module dependency direction simple.
from vyos_mgmt.schemas.auth import UserRead  # noqa: E402

UserList.model_rebuild()
