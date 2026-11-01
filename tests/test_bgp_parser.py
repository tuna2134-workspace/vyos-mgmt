"""Unit tests for ``show bgp summary`` / ``show version`` parsing."""

from __future__ import annotations

from vyos_mgmt.services.vyos.bgp_parser import parse_bgp_summary, parse_version

ESTABLISHED_SUMMARY = (
    "\nIPv4 Unicast Summary:\n"
    "BGP router identifier 10.255.0.1, local AS number 64512\n"
    "BGP table version 42\n"
    "RIB entries 48, using 9216 bytes of memory\n"
    "Peers 3, using 63 KiB of memory\n"
    "\n"
    "Neighbor          V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ  "
    "Up/Down State/PfxRcd   PfxSnt Desc\n"
    "192.0.2.1         4      65001      120       118       0     0    0  "
    "3d04h22m           12        3 Transit A\n"
    "198.51.100.1      4      65002        0         0       0     0    0      "
    "never      Active        0 Down peer\n"
    "2001:db8::1       4      65003       10        12       0     0    0  "
    "1d02h03m            5        1 IPv6 peer\n"
    "\n"
    "Total number of neighbors 3\n"
)

ACTIVE_AND_DOWN_SUMMARY = """
IPv4 Unicast Summary:
BGP router identifier 10.0.0.1, local AS number 64500
Neighbor          V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ  Up/Down State/PfxRcd
192.0.2.1         4      65001        5         6       0     0    0  00:01:02      Active
192.0.2.2         4      65002        0         0       0     0    0      never      Idle (Admin)
"""

NOT_CONFIGURED = "BGP is not configured\n"

JSON_SUMMARY = {
    "ipv4Unicast": {
        "routerId": "10.255.0.1",
        "as": 64512,
        "peers": {
            "192.0.2.1": {
                "remoteAs": 65001,
                "state": "Established",
                "pfxRcd": 12,
                "pfxSnt": 3,
                "msgRcvd": 120,
                "msgSent": 118,
                "uptime": "3d04h22m",
                "desc": "Transit A",
            }
        },
    },
    "ipv6Unicast": {
        "routerId": "10.255.0.1",
        "as": 64512,
        "peers": {
            "2001:db8::1": {
                "remoteAs": 65003,
                "state": "Active",
                "pfxRcd": 0,
                "pfxSnt": 0,
            }
        },
    },
}


def test_parse_established_peers() -> None:
    status = parse_bgp_summary(ESTABLISHED_SUMMARY)
    assert status.configured is True
    assert status.router_id == "10.255.0.1"
    assert status.local_as == 64512
    assert status.total_peers == 3
    assert status.established_peers == 2

    peer = status.peers[0]
    assert peer.address == "192.0.2.1"
    assert peer.remote_as == 65001
    assert peer.state == "Established"
    assert peer.established is True
    assert peer.uptime == "3d04h22m"
    assert peer.prefixes_received == 12
    assert peer.prefixes_sent == 3
    assert peer.msg_received == 120
    assert peer.msg_sent == 118
    assert peer.description == "Transit A"
    assert peer.address_family == "ipv4-unicast"


def test_parse_active_and_down_peers() -> None:
    status = parse_bgp_summary(ACTIVE_AND_DOWN_SUMMARY)
    assert status.configured is True
    assert status.total_peers == 2
    assert status.established_peers == 0

    active, down = status.peers
    assert active.state == "Active"
    assert active.established is False
    assert active.uptime == "00:01:02"
    assert active.description is None

    assert down.state == "Idle (Admin)"
    assert down.established is False
    assert down.uptime is None


def test_parse_not_configured() -> None:
    status = parse_bgp_summary(NOT_CONFIGURED)
    assert status.configured is False
    assert status.peers == []
    assert status.total_peers == 0
    assert status.error is not None


def test_parse_empty_text() -> None:
    status = parse_bgp_summary("   \n")
    assert status.configured is False
    assert status.peers == []
    assert status.error is not None


def test_parse_empty_json_payload() -> None:
    status = parse_bgp_summary({})
    assert status.configured is False
    assert status.peers == []
    assert status.error is not None


def test_parse_json_payload() -> None:
    status = parse_bgp_summary(JSON_SUMMARY)
    assert status.configured is True
    assert status.router_id == "10.255.0.1"
    assert status.local_as == 64512
    assert status.total_peers == 2
    assert status.established_peers == 1
    assert {peer.address_family for peer in status.peers} == {
        "ipv4-unicast",
        "ipv6-unicast",
    }


def test_parse_ignores_headers_and_malformed_lines() -> None:
    status = parse_bgp_summary(
        "IPv4 Unicast Summary:\n"
        "BGP router identifier 10.0.0.1, local AS number 64512\n"
        "Neighbor V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd\n"
        "not-an-address 4 65001 0 0 0 0 0 never Active\n"
    )
    assert status.peers == []
    assert status.total_peers == 0


def test_parse_version() -> None:
    text = (
        "Version:      VyOS 1.5-rolling-202601010000\n"
        "Built by:     mock@localhost\n"
        "Uptime:       14d 03h 12m\n"
    )
    version, uptime = parse_version(text)
    assert version == "VyOS 1.5-rolling-202601010000"
    assert uptime == "14d 03h 12m"


def test_parse_version_missing_fields() -> None:
    assert parse_version("no useful output") == (None, None)
