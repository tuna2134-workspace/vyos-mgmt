from __future__ import annotations

from vyos_mgmt.schemas.common import ApiModel


class FeatureRead(ApiModel):
    key: str
    title: str
    description: str
    status: str
    href: str
