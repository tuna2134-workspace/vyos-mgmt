"""Application configuration.

All settings are loaded from environment variables (and an optional ``.env``
file) using pydantic-settings.  The defaults are aimed at local development and
are deliberately *not* production safe; see ``.env.example`` and the README for
the production checklist.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DEV_SECRET = "dev-only-insecure-secret-change-me-please"
INSECURE_SECRET_PLACEHOLDERS = {
    DEFAULT_DEV_SECRET,
    "replace-me-with-a-long-random-string",
    "changeme",
    "change-me",
    "your-secret-key",
    "secret",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -----------------------------------------------------
    app_name: str = "VyOS Management"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    enable_docs: bool = True

    # --- Security --------------------------------------------------------
    secret_key: SecretStr = SecretStr(DEFAULT_DEV_SECRET)
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=24 * 3600)
    refresh_token_ttl_days: int = Field(default=7, ge=1, le=90)
    jwt_issuer: str = "vyos-mgmt"
    jwt_audience: str = "vyos-mgmt-api"
    jwt_algorithm: str = "HS256"

    # --- Refresh-token cookie -------------------------------------------
    refresh_cookie_name: str = "vyos_mgmt_refresh"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None

    # --- Database --------------------------------------------------------
    database_url: str = "postgresql+asyncpg://vyos:vyos@localhost:55432/vyos_mgmt"
    database_echo: bool = False
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # --- CORS ------------------------------------------------------------
    # Comma separated list.  Credentials are enabled, so "*" is not allowed.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Rate limiting ---------------------------------------------------
    login_rate_limit_attempts: int = Field(default=5, ge=1)
    login_rate_limit_window_seconds: int = Field(default=300, ge=1)
    trusted_proxy_headers: bool = False

    # --- Bootstrap -------------------------------------------------------
    bootstrap_admin_username: str | None = None
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr | None = None

    # --- VyOS ------------------------------------------------------------
    vyos_timeout_seconds: int = Field(default=10, ge=1, le=120)
    vyos_poll_interval_seconds: int = 15

    # --- Frontend --------------------------------------------------------
    serve_frontend: bool = True
    frontend_dir: Path = PROJECT_ROOT / "frontend" / "out"

    @field_validator("api_prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        value = "/" + value.strip("/")
        if value == "/":
            raise ValueError("api_prefix must not be empty")
        return value

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        value = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if value not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def refresh_cookie_path(self) -> str:
        return f"{self.api_prefix}/auth"

    @property
    def refresh_token_ttl_seconds(self) -> int:
        return self.refresh_token_ttl_days * 24 * 3600

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _production_guardrails(self) -> Settings:
        if self.is_production:
            secret = self.secret_key.get_secret_value()
            if len(secret) < 32 or secret.strip().lower() in INSECURE_SECRET_PLACEHOLDERS:
                raise ValueError(
                    "SECRET_KEY must be a random value of at least 32 characters in production "
                    "(the example placeholder is not acceptable)"
                )
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            if "*" in self.cors_origin_list:
                raise ValueError("Wildcard CORS origins are not allowed in production")
        if "*" in self.cors_origin_list:
            raise ValueError(
                "Wildcard CORS origins cannot be combined with credentialed requests; "
                "list explicit origins instead"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
