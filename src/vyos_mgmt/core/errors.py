"""Consistent API error envelope and exception handlers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Domain error rendered as ``{"error": {...}}`` with a stable code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers or {}


def bad_request(code: str, message: str, details: Any = None) -> AppError:
    return AppError(400, code, message, details=details)


def not_found(code: str, message: str) -> AppError:
    return AppError(404, code, message)


def conflict(code: str, message: str, details: Any = None) -> AppError:
    return AppError(409, code, message, details=details)


def forbidden(message: str = "You do not have permission to perform this action") -> AppError:
    return AppError(403, "forbidden", message)


def unauthorized(message: str = "Not authenticated") -> AppError:
    return AppError(
        401,
        "not_authenticated",
        message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": _request_id(request),
        }
    }
    merged_headers = {"Cache-Control": "no-store"}
    if headers:
        merged_headers.update(headers)
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body),
        headers=merged_headers,
    )


_SECRET_FIELD_NAMES = {
    "password",
    "current_password",
    "new_password",
    "api_key",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    # WireGuard key material is write-only and must never be echoed back.
    "private_key",
    "preshared_key",
}

REDACTED = "[redacted]"


def _redact_input(value: Any, loc: list[str]) -> Any:
    """Remove credentials from validation errors.

    Pydantic includes the offending input in validation errors.  Echoing that
    verbatim would leak passwords and API keys back to the caller, so values
    under sensitive field names are replaced.
    """

    if any(part.lower() in _SECRET_FIELD_NAMES for part in loc):
        return REDACTED
    if isinstance(value, dict):
        return {key: _redact_input(item, [*loc, str(key)]) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_input(item, loc) for item in value]
    return value


def _sanitise_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for error in errors:
        loc = [str(part) for part in error.get("loc", [])]
        cleaned.append(
            {
                "type": error.get("type"),
                "loc": loc,
                "msg": error.get("msg"),
                "input": _redact_input(error.get("input"), loc),
            }
        )
    return cleaned


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            request,
            status_code=422,
            code="validation_error",
            message="The request payload is invalid",
            details=_sanitise_validation_errors(exc.errors()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            code = str(exc.detail["code"])
            message = str(exc.detail.get("message", "Request failed"))
            details = exc.detail.get("details")
        else:
            code = f"http_{exc.status_code}"
            message = str(exc.detail) if exc.detail else "Request failed"
            details = None
        return error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=message,
            details=details,
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled exception handling %s %s",
            request.method,
            request.url.path,
            extra={"request_id": _request_id(request)},
        )
        return error_response(
            request,
            status_code=500,
            code="internal_error",
            message="An unexpected error occurred. Check the server logs for details.",
        )
