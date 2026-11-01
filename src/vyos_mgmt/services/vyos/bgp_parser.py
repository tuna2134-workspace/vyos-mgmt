"""Parsers for VyOS/FRR operational output.

``/show`` on the VyOS HTTPS API returns text (unlike ``/retrieve`` which
returns structured configuration), so BGP session state is parsed from the
familiar ``show bgp summary`` table.  The parser tolerates the small
differences between FRR releases and is covered by unit tests.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from vyos_mgmt.schemas.bgp import BgpPeerStatus, BgpStatus

_ROUTER_ID_RE = re.compile(
    r"BGP router identifier\s+(?P<router_id>\d{1,3}(?:\.\d{1,3}){3}),\s*"
    r"local AS number\s+(?P<local_as>\d+)",
    re.IGNORECASE,
)
_AF_RE = re.compile(r"(?:For address family:\s*|^)(?P<af>IPv4|IPv6)\s+Unicast", re.IGNORECASE)
_NOT_CONFIGURED_MARKERS = (
    "bgp is not configured",
    "no bgp instance",
    "% bgp not configured",
    "bgp not running",
)


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _parse_peer_line(tokens: list[str], af: str | None) -> BgpPeerStatus | None:
    if len(tokens) < 10:
        return None
    try:
        ipaddress.ip_address(tokens[0])
    except ValueError:
        return None

    remote_as = _as_int(tokens[2])
    msg_received = _as_int(tokens[3])
    msg_sent = _as_int(tokens[4])
    uptime = tokens[8]

    index = 9
    prefixes_received: int | None = None
    if tokens[index].isdigit():
        state = "Established"
        prefixes_received = int(tokens[index])
        established = True
        index += 1
    else:
        state = tokens[index]
        established = False
        index += 1
        if index < len(tokens) and tokens[index].startswith("("):
            state = f"{state} {tokens[index]}"
            index += 1

    prefixes_sent: int | None = None
    if index < len(tokens) and tokens[index].isdigit():
        prefixes_sent = int(tokens[index])
        index += 1

    description = " ".join(tokens[index:]).strip() or None
    return BgpPeerStatus(
        address=tokens[0],
        remote_as=remote_as,
        state=state,
        established=established,
        uptime=uptime if uptime not in {"never", "-"} else None,
        prefixes_received=prefixes_received,
        prefixes_sent=prefixes_sent,
        msg_received=msg_received,
        msg_sent=msg_sent,
        description=description,
        address_family=af,
    )


def _parse_text(text: str) -> BgpStatus:
    if not text.strip():
        return BgpStatus(configured=False, error="No BGP summary output was returned")

    lowered = text.lower()
    configured = not any(marker in lowered for marker in _NOT_CONFIGURED_MARKERS)

    router_id: str | None = None
    local_as: int | None = None
    match = _ROUTER_ID_RE.search(text)
    if match:
        router_id = match.group("router_id")
        local_as = _as_int(match.group("local_as"))

    peers: list[BgpPeerStatus] = []
    current_af: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        af_match = _AF_RE.search(line)
        if af_match and "summary" in line.lower():
            current_af = f"{af_match.group('af').lower()}-unicast"
            continue
        if af_match and line.lower().startswith("for address family"):
            current_af = f"{af_match.group('af').lower()}-unicast"
            continue
        if line.lower().startswith("neighbor"):
            continue
        if "router identifier" in line.lower() or line.lower().startswith("total number"):
            continue
        if line.startswith("BGP table version") or line.startswith("RIB entries"):
            continue

        peer = _parse_peer_line(line.split(), current_af)
        if peer is not None:
            peers.append(peer)

    return BgpStatus(
        configured=configured,
        router_id=router_id,
        local_as=local_as,
        peers=peers,
        total_peers=len(peers),
        established_peers=sum(1 for peer in peers if peer.established),
        error=None if configured else "BGP is not configured on this router",
    )


def _parse_json(payload: dict[str, Any]) -> BgpStatus:
    if not payload:
        return BgpStatus(configured=False, error="BGP is not configured on this router")

    peers: list[BgpPeerStatus] = []
    router_id: str | None = None
    local_as: int | None = None

    for key, af in (("ipv4Unicast", "ipv4-unicast"), ("ipv6Unicast", "ipv6-unicast")):
        section = payload.get(key)
        if not isinstance(section, dict):
            continue
        router_id = router_id or section.get("routerId")
        local_as = local_as or _as_int(section.get("as"))
        section_peers = section.get("peers")
        if not isinstance(section_peers, dict):
            continue
        for address, data in section_peers.items():
            if not isinstance(data, dict):
                continue
            state = str(data.get("state") or data.get("peerState") or "Unknown").strip()
            # FRR JSON reports prefix counts even while down; "pfxRcd" is only
            # meaningful once the session is established.
            established = state.lower() == "established"
            uptime = data.get("uptime")
            peers.append(
                BgpPeerStatus(
                    address=str(address),
                    remote_as=_as_int(data.get("remoteAs")),
                    state=state,
                    established=established,
                    uptime=str(uptime) if uptime else None,
                    prefixes_received=_as_int(data.get("pfxRcd")),
                    prefixes_sent=_as_int(data.get("pfxSnt")),
                    msg_received=_as_int(data.get("msgRcvd")),
                    msg_sent=_as_int(data.get("msgSent")),
                    description=data.get("desc"),
                    address_family=af,
                )
            )

    return BgpStatus(
        configured=True,
        router_id=str(router_id) if router_id else None,
        local_as=local_as,
        peers=peers,
        total_peers=len(peers),
        established_peers=sum(1 for peer in peers if peer.established),
    )


def parse_bgp_summary(payload: str | dict[str, Any]) -> BgpStatus:
    if isinstance(payload, dict):
        return _parse_json(payload)
    return _parse_text(payload)


def parse_version(text: str) -> tuple[str | None, str | None]:
    """Extract (version, uptime) from ``show version`` output."""

    version = None
    uptime = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("version:") and version is None:
            version = stripped.split(":", 1)[1].strip() or None
        elif stripped.lower().startswith("uptime:") and uptime is None:
            uptime = stripped.split(":", 1)[1].strip() or None
    return version, uptime
