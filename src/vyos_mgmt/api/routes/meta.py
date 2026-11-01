"""Feature discovery and health endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from vyos_mgmt.api.deps import CurrentUser, SettingsDep
from vyos_mgmt.db.session import get_engine
from vyos_mgmt.features.registry import FEATURES
from vyos_mgmt.schemas.common import HealthResponse
from vyos_mgmt.schemas.meta import FeatureRead

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse, response_model_exclude_none=True)
async def health(settings: SettingsDep, response: Response) -> HealthResponse:
    """Liveness/readiness probe; intentionally public.

    Returns 503 when the database is unreachable so container orchestrators and
    load balancers stop sending traffic to this instance.
    """

    database = "ok"
    try:
        engine = get_engine()
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        database = "error"
        response.status_code = 503

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        version=settings.app_version,
        environment=settings.environment,
        database=database,
    )


@router.get("/meta/features", response_model=list[FeatureRead])
async def list_features(_current_user: CurrentUser) -> list[FeatureRead]:
    return [FeatureRead(**feature.as_dict()) for feature in FEATURES]
