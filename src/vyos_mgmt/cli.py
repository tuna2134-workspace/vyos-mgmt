"""Command-line interface: serve, migrate and create-admin."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from vyos_mgmt.config import PROJECT_ROOT, get_settings
from vyos_mgmt.core.security import hash_password
from vyos_mgmt.db.models import User, UserRole
from vyos_mgmt.db.session import (
    build_engine,
    dispose_engine,
    get_session_factory,
    set_engine,
)
from vyos_mgmt.schemas.user import normalise_username

ADMIN_PASSWORD_ENV = "VYOS_MGMT_ADMIN_PASSWORD"
FALLBACK_PASSWORD_ENV = "BOOTSTRAP_ADMIN_PASSWORD"
MIN_PASSWORD_LENGTH = 12


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vyos-mgmt",
        description="VyOS management console backend",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the API server with uvicorn")
    serve.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    serve.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload (development only)",
    )

    subparsers.add_parser("migrate", help="Apply database migrations (alembic upgrade head)")

    create_admin = subparsers.add_parser("create-admin", help="Create an administrator account")
    create_admin.add_argument("--username", default="admin", help="Username (default: admin)")
    create_admin.add_argument("--email", default=None, help="Optional email address")
    create_admin.add_argument(
        "--role",
        choices=[role.value for role in UserRole],
        default=UserRole.ADMIN.value,
        help="Role for the new account (default: admin)",
    )
    create_admin.add_argument(
        "--password",
        default=None,
        help=(
            "Password (prefer the interactive prompt or the "
            f"{ADMIN_PASSWORD_ENV} environment variable)"
        ),
    )
    return parser


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "vyos_mgmt.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )
    return 0


def _find_alembic_ini() -> Path:
    """Locate alembic.ini for editable and wheel/container installs alike."""

    candidates = [Path.cwd(), PROJECT_ROOT, *PROJECT_ROOT.parents]
    for base in candidates:
        candidate = base / "alembic.ini"
        if candidate.is_file():
            return candidate
    return PROJECT_ROOT / "alembic.ini"


def _migrate(_args: argparse.Namespace) -> int:
    config_path = _find_alembic_ini()
    config = Config(str(config_path))
    config.set_main_option("script_location", str(config_path.parent / "alembic"))
    command.upgrade(config, "head")
    print("Database is up to date")
    return 0


def _resolve_password(explicit: str | None) -> str:
    if explicit:
        return explicit
    for variable in (ADMIN_PASSWORD_ENV, FALLBACK_PASSWORD_ENV):
        value = os.environ.get(variable)
        if value:
            return value

    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match")
    return password


async def _create_admin(args: argparse.Namespace) -> int:
    try:
        username = normalise_username(args.username)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        password = _resolve_password(args.password)
    except (EOFError, KeyboardInterrupt):
        print("error: no password supplied", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if len(password) < MIN_PASSWORD_LENGTH:
        print(
            f"error: password must be at least {MIN_PASSWORD_LENGTH} characters",
            file=sys.stderr,
        )
        return 1

    settings = get_settings()
    set_engine(build_engine(settings))
    created = False
    try:
        factory = get_session_factory()
        async with factory() as session:
            existing = await session.scalar(select(User).where(User.username == username))
            if existing is not None:
                print(f"error: user '{username}' already exists", file=sys.stderr)
                return 1
            session.add(
                User(
                    username=username,
                    email=args.email,
                    password_hash=hash_password(password),
                    role=UserRole(args.role),
                    is_active=True,
                )
            )
            await session.commit()
            created = True
    except SQLAlchemyError as exc:
        print(
            f"error: database operation failed ({type(exc).__name__}); "
            "did you run 'vyos-mgmt migrate'?",
            file=sys.stderr,
        )
        return 1
    finally:
        await dispose_engine()

    if created:
        print(f"Created {args.role} user '{username}'")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        return _serve(args)
    if args.command == "migrate":
        return _migrate(args)
    if args.command == "create-admin":
        return asyncio.run(_create_admin(args))

    parser.error(f"unknown command: {args.command}")  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
