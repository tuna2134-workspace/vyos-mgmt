"""Pytest fixtures.

The suite runs against a real PostgreSQL database (``vyos_mgmt_test``) but
never against a VyOS device: integration tests use the built-in mock driver.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from tests.helpers import (
    ADMIN_PASSWORD,
    OPERATOR_PASSWORD,
    VIEWER_PASSWORD,
    create_user,
    login,
)
from vyos_mgmt.config import Settings
from vyos_mgmt.core.rate_limit import rate_limiter
from vyos_mgmt.db import models  # noqa: F401  (registers all tables)
from vyos_mgmt.db.base import Base
from vyos_mgmt.db.models import User, UserRole
from vyos_mgmt.db.session import build_engine
from vyos_mgmt.main import create_app
from vyos_mgmt.services.vyos.mock_driver import MockDriver

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://vyos:vyos@localhost:55432/vyos_mgmt_test",
)
TEST_SECRET_KEY = "test-secret-key-for-vyos-mgmt-0123456789abcdef"


@pytest.fixture(autouse=True)
async def reset_runtime_state() -> AsyncIterator[None]:
    MockDriver.reset()
    await rate_limiter.clear()
    yield
    MockDriver.reset()
    await rate_limiter.clear()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url=TEST_DATABASE_URL,
        secret_key=TEST_SECRET_KEY,
        serve_frontend=False,
        enable_docs=True,
        cookie_secure=False,
        cookie_samesite="lax",
        cors_origins="http://localhost:3000",
        login_rate_limit_attempts=100,
        login_rate_limit_window_seconds=60,
        bootstrap_admin_username=None,
        bootstrap_admin_email=None,
        bootstrap_admin_password=None,
        database_pool_size=2,
        database_max_overflow=2,
        vyos_timeout_seconds=2,
    )


@pytest.fixture
async def app(settings: Settings):
    # Ensure the schema exists and each test starts from empty tables.
    engine = build_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())
    await engine.dispose()

    application = create_app(settings)
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest.fixture
async def admin_user(app) -> User:
    return await create_user("admin", ADMIN_PASSWORD, UserRole.ADMIN, email="admin@example.com")


@pytest.fixture
async def operator_user(app) -> User:
    return await create_user("operator", OPERATOR_PASSWORD, UserRole.OPERATOR)


@pytest.fixture
async def viewer_user(app) -> User:
    return await create_user("viewer", VIEWER_PASSWORD, UserRole.VIEWER)


@pytest.fixture
async def admin_token(admin_user: User, client: AsyncClient) -> str:
    payload = await login(client, admin_user.username, ADMIN_PASSWORD)
    return payload["access_token"]


@pytest.fixture
async def operator_token(operator_user: User, client: AsyncClient) -> str:
    payload = await login(client, operator_user.username, OPERATOR_PASSWORD)
    return payload["access_token"]


@pytest.fixture
async def viewer_token(viewer_user: User, client: AsyncClient) -> str:
    payload = await login(client, viewer_user.username, VIEWER_PASSWORD)
    return payload["access_token"]
