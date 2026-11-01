"""Feature registry.

Every VyOS feature module (BGP, route maps, prefix lists, OSPF, static routes
and WireGuard today; interfaces, firewall later) publishes a small descriptor here.  The
registry is the single extension point used by the ``GET /meta/features``
endpoint, so adding a feature never requires touching the meta route or the
frontend navigation contract.

To add a feature:

1. Implement the service, schemas and routes.
2. Create a :class:`FeatureDescriptor` and append it to :data:`FEATURES`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

FeatureStatus = Literal["available", "beta", "planned", "disabled"]


@dataclass(frozen=True, slots=True)
class FeatureDescriptor:
    """Public description of a feature shown by the UI."""

    key: str
    title: str
    description: str
    status: FeatureStatus
    href: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


BGP_FEATURE = FeatureDescriptor(
    key="bgp",
    title="BGP",
    description="Border Gateway Protocol configuration and session health",
    status="available",
    href="/bgp/",
)

ROUTE_MAP_FEATURE = FeatureDescriptor(
    key="route-maps",
    title="Route maps",
    description=("Policy route-map rules for BGP import/export filtering and attribute changes"),
    status="available",
    href="/route-maps/",
)

PREFIX_LIST_FEATURE = FeatureDescriptor(
    key="prefix-lists",
    title="Prefix lists",
    description="IPv4 and IPv6 prefix-list policy objects used by route-map and BGP filters",
    status="available",
    href="/prefix-lists/",
)

OSPF_FEATURE = FeatureDescriptor(
    key="ospf",
    title="OSPF",
    description="OSPFv2 (IPv4) and OSPFv3 (IPv6) routing",
    status="available",
    href="/ospf/",
)

STATIC_ROUTE_FEATURE = FeatureDescriptor(
    key="static-routes",
    title="Static routes",
    description="IPv4/IPv6 static routes with next hops, blackhole and reject",
    status="available",
    href="/static-routes/",
)

VPN_FEATURE = FeatureDescriptor(
    key="vpn",
    title="VPN",
    description="WireGuard tunnels and peers",
    status="available",
    href="/vpn/",
)

# Ordered as they should appear in navigation.
FEATURES: tuple[FeatureDescriptor, ...] = (
    BGP_FEATURE,
    ROUTE_MAP_FEATURE,
    PREFIX_LIST_FEATURE,
    OSPF_FEATURE,
    STATIC_ROUTE_FEATURE,
    VPN_FEATURE,
)


def get_features() -> list[dict[str, str]]:
    """Return plain dictionaries ready for the API response."""

    return [feature.as_dict() for feature in FEATURES]


def get_feature(key: str) -> FeatureDescriptor | None:
    return next((feature for feature in FEATURES if feature.key == key), None)
