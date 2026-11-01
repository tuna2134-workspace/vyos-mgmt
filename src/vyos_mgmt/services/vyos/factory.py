"""Driver construction from stored router definitions."""

from __future__ import annotations

from vyos_mgmt.config import Settings
from vyos_mgmt.core.crypto import decrypt_secret
from vyos_mgmt.db.models import Router, RouterDriver
from vyos_mgmt.services.vyos.base import DeviceTarget, VyosConfigurationError, VyosDriver
from vyos_mgmt.services.vyos.mock_driver import MockDriver
from vyos_mgmt.services.vyos.pyvyos_driver import PyvyosDriver


def build_target(router: Router, settings: Settings) -> DeviceTarget:
    api_key = ""
    if router.api_key_encrypted:
        api_key = decrypt_secret(
            router.api_key_encrypted, secret=settings.secret_key.get_secret_value()
        )
    elif router.driver == RouterDriver.PYVYOS:
        raise VyosConfigurationError(
            f"Router '{router.name}' has no API key configured; edit the router to add one"
        )
    return DeviceTarget(
        id=router.id,
        name=router.name,
        host=router.host,
        port=router.port,
        protocol=router.protocol,
        api_key=api_key,
        verify_tls=router.verify_tls,
        driver=router.driver.value,
        timeout=settings.vyos_timeout_seconds,
    )


def build_driver(router: Router, settings: Settings) -> VyosDriver:
    target = build_target(router, settings)
    if router.driver == RouterDriver.MOCK:
        return MockDriver(target)
    try:
        return PyvyosDriver(target)
    except ValueError as exc:
        # pyvyos validates its constructor arguments (hostname length, port...).
        raise VyosConfigurationError(f"Invalid router configuration: {exc}") from exc
