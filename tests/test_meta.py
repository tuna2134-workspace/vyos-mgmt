"""Integration tests for health, feature discovery, docs and static serving."""

from __future__ import annotations

from pathlib import Path

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from tests.helpers import auth_headers
from vyos_mgmt.main import create_app


async def test_health_is_public(client) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"status", "version", "environment", "database"}
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["environment"] == "test"


async def test_features_require_auth_and_match_contract(client, admin_token) -> None:
    unauthenticated = await client.get("/api/v1/meta/features")
    assert unauthenticated.status_code == 401

    response = await client.get("/api/v1/meta/features", headers=auth_headers(admin_token))
    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "key": "bgp",
            "title": "BGP",
            "description": "Border Gateway Protocol configuration and session health",
            "status": "available",
            "href": "/bgp/",
        },
        {
            "key": "route-maps",
            "title": "Route maps",
            "description": (
                "Policy route-map rules for BGP import/export filtering and attribute changes"
            ),
            "status": "available",
            "href": "/route-maps/",
        },
        {
            "key": "prefix-lists",
            "title": "Prefix lists",
            "description": (
                "IPv4 and IPv6 prefix-list policy objects used by route-map and BGP filters"
            ),
            "status": "available",
            "href": "/prefix-lists/",
        },
        {
            "key": "ospf",
            "title": "OSPF",
            "description": "OSPFv2 (IPv4) and OSPFv3 (IPv6) routing",
            "status": "available",
            "href": "/ospf/",
        },
        {
            "key": "static-routes",
            "title": "Static routes",
            "description": "IPv4/IPv6 static routes with next hops, blackhole and reject",
            "status": "available",
            "href": "/static-routes/",
        },
        {
            "key": "vpn",
            "title": "VPN",
            "description": "WireGuard tunnels and peers",
            "status": "available",
            "href": "/vpn/",
        },
    ]


async def test_unknown_api_paths_use_json_error_envelope(client) -> None:
    for path in ("/api/v1/nope", "/api/unknown", "/api"):
        response = await client.get(path)
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "not_found"
        assert body["error"]["request_id"] == response.headers["X-Request-ID"]


async def test_openapi_and_docs(client) -> None:
    schema = await client.get("/api/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/routers/{router_id}/bgp/neighbors" in paths
    assert "/api/v1/routers/{router_id}/route-maps" in paths
    assert "/api/v1/routers/{router_id}/route-maps/{name}/rules/{number}" in paths
    assert "/api/v1/routers/{router_id}/prefix-lists" in paths
    assert "/api/v1/routers/{router_id}/prefix-lists/{family}/{name}" in paths
    assert "/api/v1/routers/{router_id}/prefix-lists/{family}/{name}/rules/{number}" in paths
    assert "/api/v1/routers/{router_id}/ospf/{version}" in paths
    assert "/api/v1/routers/{router_id}/ospf/{version}/global" in paths
    assert "/api/v1/routers/{router_id}/ospf/{version}/areas" in paths
    assert "/api/v1/routers/{router_id}/ospf/{version}/areas/{area_id}" in paths
    assert "/api/v1/routers/{router_id}/ospf/{version}/interfaces" in paths
    assert "/api/v1/routers/{router_id}/ospf/{version}/interfaces/{name}" in paths
    assert "/api/v1/routers/{router_id}/ospf/{version}/redistribute" in paths
    assert "/api/v1/routers/{router_id}/ospf/{version}/redistribute/{source}" in paths
    assert "/api/v1/routers/{router_id}/ospf/{version}/status" in paths
    assert "/api/v1/routers/{router_id}/static-routes" in paths
    assert "/api/v1/routers/{router_id}/static-routes/{family}/{prefix}" in paths
    assert "/api/v1/routers/{router_id}/wireguard" in paths
    assert "/api/v1/routers/{router_id}/wireguard/keypair" in paths
    assert "/api/v1/routers/{router_id}/wireguard/preshared-key" in paths
    assert "/api/v1/routers/{router_id}/wireguard/{name}" in paths
    assert "/api/v1/routers/{router_id}/wireguard/{name}/private-key" in paths
    assert "/api/v1/routers/{router_id}/wireguard/{name}/status" in paths
    assert "/api/v1/routers/{router_id}/wireguard/{name}/peers" in paths
    assert "/api/v1/routers/{router_id}/wireguard/{name}/peers/{peer}" in paths

    docs = await client.get("/api/docs")
    assert docs.status_code == 200
    assert "text/html" in docs.headers["content-type"]


async def test_cors_preflight(client) -> None:
    response = await client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_static_frontend_serves_export_and_404(settings, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html><body>home page</body></html>")
    (tmp_path / "404.html").write_text("<html><body>custom not found</body></html>")
    (tmp_path / "bgp").mkdir()
    (tmp_path / "bgp" / "index.html").write_text("<html><body>bgp page</body></html>")

    static_settings = settings.model_copy(update={"serve_frontend": True, "frontend_dir": tmp_path})
    application = create_app(static_settings)
    transport = ASGITransport(app=application)
    async with (
        LifespanManager(application),
        AsyncClient(
            transport=transport, base_url="http://testserver", follow_redirects=True
        ) as http_client,
    ):
        home = await http_client.get("/")
        assert home.status_code == 200
        assert "home page" in home.text

        bgp = await http_client.get("/bgp/")
        assert bgp.status_code == 200
        assert "bgp page" in bgp.text

        missing = await http_client.get("/does-not-exist/")
        assert missing.status_code == 404
        assert "custom not found" in missing.text

        api_missing = await http_client.get("/api/v1/nope")
        assert api_missing.status_code == 404
        assert api_missing.json()["error"]["code"] == "not_found"

        health = await http_client.get("/api/v1/health")
        assert health.status_code == 200


async def test_missing_frontend_directory_does_not_break_app(settings) -> None:
    absent_settings = settings.model_copy(
        update={"serve_frontend": True, "frontend_dir": Path("/nonexistent/vyos-out")}
    )
    application = create_app(absent_settings)
    transport = ASGITransport(app=application)
    async with (
        LifespanManager(application),
        AsyncClient(transport=transport, base_url="http://testserver") as http_client,
    ):
        response = await http_client.get("/api/v1/health")
        assert response.status_code == 200
