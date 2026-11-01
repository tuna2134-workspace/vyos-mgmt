# VyOS Management

A self-hosted web console for managing VyOS routers. The first release focuses
on **BGP** (global configuration, neighbors, peer groups, advertised networks
and live session health), **route-map policy** (match/set rules used for BGP
import/export filtering, OSPF redistribution and attribute changes),
**prefix-list policy**
(IPv4/IPv6 prefix filters used by route maps and BGP), **OSPFv2/v3**,
**static routing** and **WireGuard VPN**, while the backend and frontend are
structured so more VyOS feature modules can be added without rewiring the app.

- **Backend:** FastAPI · pyvyos · SQLAlchemy 2 (async) · asyncpg · Alembic
- **Auth:** JWT access + rotating refresh tokens (HttpOnly cookie) · Argon2id
- **Frontend:** Next.js (static export) · Tailwind CSS v4 · shadcn/ui
- **Database:** PostgreSQL 16+
- **Deploy:** one container serves the API and the pre-built static UI

---

## Screenshots

Captured against the built-in `mock` driver (no VyOS device required).

| Dashboard | BGP overview |
| --- | --- |
| ![Dashboard](docs/screenshots/dashboard.png) | ![BGP overview](docs/screenshots/bgp-overview.png) |

| BGP neighbors | BGP global settings |
| --- | --- |
| ![BGP neighbors](docs/screenshots/bgp-neighbors.png) | ![BGP settings](docs/screenshots/bgp-settings.png) |

| Route maps | Route-map rule editor |
| --- | --- |
| ![Route maps](docs/screenshots/route-maps.png) | ![Route-map rule editor](docs/screenshots/route-map-rule.png) |

| BGP route-map binding | In-use route-map protection |
| --- | --- |
| ![BGP route-map binding](docs/screenshots/bgp-route-map-binding.png) | ![In-use route-map protection](docs/screenshots/route-map-in-use.png) |

| Prefix lists (IPv4/IPv6) | Prefix-list rule editor |
| --- | --- |
| ![Prefix lists](docs/screenshots/prefix-lists.png) | ![Prefix-list rule editor](docs/screenshots/prefix-list-rule.png) |

| Route-map prefix-list match | In-use prefix-list protection |
| --- | --- |
| ![Route-map prefix-list fields](docs/screenshots/route-map-prefix-list-fields.png) | ![In-use prefix-list protection](docs/screenshots/prefix-list-in-use.png) |

| OSPFv2 (IPv4) | OSPFv3 (IPv6) |
| --- | --- |
| ![OSPFv2 overview](docs/screenshots/ospf-overview.png) | ![OSPFv3 overview](docs/screenshots/ospf-v3-overview.png) |

| OSPF interfaces | OSPF areas |
| --- | --- |
| ![OSPF interfaces](docs/screenshots/ospf-interfaces.png) | ![OSPF areas](docs/screenshots/ospf-areas.png) |

| OSPF redistribution | OSPF settings |
| --- | --- |
| ![OSPF redistribution](docs/screenshots/ospf-redistribution.png) | ![OSPF settings](docs/screenshots/ospf-settings.png) |

| Static routes (IPv4) | Static routes (IPv6) |
| --- | --- |
| ![Static routes IPv4](docs/screenshots/static-routes.png) | ![Static routes IPv6](docs/screenshots/static-routes-ipv6.png) |

| New static route |
| --- |
| ![New static route](docs/screenshots/static-route-dialog.png) |

| WireGuard tunnel | New WireGuard interface |
| --- | --- |
| ![WireGuard tunnel](docs/screenshots/vpn-wireguard.png) | ![New WireGuard interface](docs/screenshots/vpn-interface-dialog.png) |

| WireGuard peer editor | Rotate interface key |
| --- | --- |
| ![WireGuard peer editor](docs/screenshots/vpn-peer-dialog.png) | ![Rotate WireGuard key](docs/screenshots/vpn-rotate-key.png) |

| Sign in | Mobile |
| --- | --- |
| ![Sign in](docs/screenshots/login.png) | ![Mobile prefix lists](docs/screenshots/mobile-prefix-lists.png) |

## Features

- **Router inventory** — multiple VyOS devices, encrypted API keys, TLS
  verification toggle, connection test, and a built-in `mock` driver for demos
  and tests.
- **BGP configuration** — system AS / router ID, neighbors (remote AS, peer
  groups, timers, passwords, eBGP multihop, passive/shutdown, local AS), peer
  groups, and IPv4/IPv6 advertised networks.
- **Route-map policy** — route maps with ordered permit/deny rules, IPv4/IPv6
  prefix-list matches, AS-path / community / large-community matching, metric,
  local-preference, tag, origin, protocol and RPKI conditions, plus set actions
  (local-preference, MED/metric, origin, weight, tag, AS-path prepend,
  communities, next-hop, originator ID). Route maps can be attached to BGP
  neighbors and peer groups as per-AF import/export policy; in-use maps are
  protected from deletion. Route maps can also filter OSPF redistribution.
- **Prefix lists** — IPv4 (`prefix-list`) and IPv6 (`prefix-list6`) policy
  objects with ordered permit/deny rules, strict network prefixes, `ge`/`le`
  length bounds and duplicate-definition protection. Prefix lists are selectable
  in route-map match conditions, and in-use objects are protected from deletion.
- **OSPFv2 and OSPFv3** — IPv4/IPv6 OSPF processes with router ID, adjacency
  logging, auto-cost, default-information, areas (normal/stub/NSSA/totally
  stub), interface activation (area, network type, cost, timers, priority,
  passive/BFD/MTU), redistribution with metric/metric-type/route-map, live
  neighbor status, and per-version tabs.
- **Static routes** — IPv4/IPv6 unicast routes with multiple next hops
  (address and/or interface, per-next-hop distance/disable), plus blackhole and
  reject routes with distance/tag; duplicate-prefix protection.
- **WireGuard VPN** — interface addresses/listen port/MTU, write-only private
  keys with server-side keypair generation, peers with public keys, allowed
  IPs, endpoint/keepalive, optional preshared keys, live handshake/transfer
  status, and duplicate allowed-IP/public-key protection.
- **Live session health** — parsed `show bgp summary` / OSPF neighbor output:
  state, uptime, prefix counts, message counters, polling in the UI.
- **Safe writes** — every change is one atomic VyOS multi-operation commit and
  the API returns the resulting configuration; destructive actions require
  explicit confirmation.
- **RBAC** — `admin`, `operator`, `viewer`; enforced in the API and reflected in
  the UI.
- **Audit log** — every privileged/configuration mutation is recorded with the
  actor, router, action, resource and request ID (secrets redacted).
- **Secure defaults** — Argon2id password hashing, encrypted device API keys,
  short-lived access tokens, refresh-token rotation/revocation, login rate
  limiting, CSRF-protected refresh/logout, security headers, no secret leakage
  in responses.

## Architecture

```
┌──────────────────────────────┐        HTTPS + API key
│ Browser (static Next.js)     │   ┌────────────────────┐      ┌──────────┐
│ React Query / fetch          │   │ FastAPI            │      │  VyOS    │
│ access token in memory       │──▶│ /api/v1            │─────▶│  HTTPS   │
│ HttpOnly refresh cookie      │   │ auth · RBAC · audit│      │  API     │
└──────────────────────────────┘   │ BGP service        │      └──────────┘
                                   │ pyvyos driver      │
                                   └─────────┬──────────┘
                                             │ SQLAlchemy async
                                   ┌─────────▼──────────┐
                                   │ PostgreSQL         │
                                   │ users · routers    │
                                   │ tokens · audit     │
                                   └────────────────────┘
```

The static export is served by FastAPI at `/` in production; in development the
Next.js dev server (`:3000`) talks to the API (`:8000`) using CORS with
credentials.

### Extensibility

Adding a feature (e.g. interfaces, firewall, OSPF) is a two-sided, mechanical
change:

1. **Backend** — add a route module under `src/vyos_mgmt/api/routes/`, a
   service under `src/vyos_mgmt/services/`, and register the router + descriptor
   in `src/vyos_mgmt/features/registry.py`. Drivers already expose generic
   `get_config(path)` / `show(path)` / `apply([ConfigOp(...)])` primitives, so
   most features need no driver changes.
2. **Frontend** — add the feature to `frontend/src/features/registry.tsx` plus
   its route folder. The sidebar, module navigation and dashboard cards are
   generated from that registry; no shell changes are required.

All API shapes are documented in [`docs/api-contract.md`](docs/api-contract.md).

## Quick start (Docker)

```bash
cp .env.example .env
# Set at minimum:
#   SECRET_KEY=<python -c "import secrets;print(secrets.token_urlsafe(48))">
#   POSTGRES_PASSWORD=<random>
#   BOOTSTRAP_ADMIN_PASSWORD=<strong password>   # first boot only
docker compose up -d --build
```

Open <http://localhost:8000> and sign in with the bootstrap admin (or create one
with `docker compose exec app vyos-mgmt create-admin --username admin`).

The bootstrap account is only created when the `users` table is empty. Remove
`BOOTSTRAP_ADMIN_PASSWORD` after the first start.

> Serving over plain HTTP: keep `COOKIE_SECURE=false`. Behind HTTPS set
> `COOKIE_SECURE=true` and `TRUSTED_PROXY_HEADERS=true` when a trusted reverse
> proxy terminates TLS (see `docker-compose.yml`).

## Local development

Prerequisites: Python 3.13, [uv](https://docs.astral.sh/uv/), Node 22+ and pnpm,
PostgreSQL 16 (or Docker).

```bash
# 1. Database
docker run -d --name vyos-mgmt-db \
  -e POSTGRES_USER=vyos -e POSTGRES_PASSWORD=vyos -e POSTGRES_DB=vyos_mgmt \
  -p 55432:5432 postgres:16-alpine

# 2. Backend
cp .env.example .env            # set SECRET_KEY and (optionally) bootstrap admin
uv sync --all-groups
uv run alembic upgrade head
uv run vyos-mgmt create-admin --username admin
uv run uvicorn vyos_mgmt.main:app --reload --port 8000
# API docs: http://localhost:8000/api/docs

# 3. Frontend (second terminal)
cd frontend
pnpm install
pnpm dev                        # http://localhost:3000
```

The frontend dev server defaults to `http://localhost:8000/api/v1`; the backend
allows `http://localhost:3000` via `CORS_ORIGINS`. Use the same hostname
(`localhost`, not a mix of `localhost`/`127.0.0.1`) so the refresh cookie is
treated as same-site.

### Mock router

Create a router with **Driver: mock** in the UI (an API key is not required) to
explore every BGP screen without a VyOS device. The mock driver implements the
same atomic set/delete semantics as the real HTTPS API and ships with a
realistic BGP configuration, including an admin-down peer, seeded route maps
(`BGP-IN`, `BGP-OUT`, `LOCAL-PREF`, `OSPF-OUT`) bound to BGP and OSPF, the
prefix lists those route maps reference, and seeded OSPFv2/OSPFv3 processes
with areas, interfaces and neighbors, plus IPv4/IPv6 static routes and a
WireGuard interface with a site-to-site and a road-warrior peer.

## Configuring VyOS

On the device, enable the HTTPS API and create an API key:

```
configure
set service https api rest
set service https api keys id vyos-mgmt key '<long-random-secret>'
commit
save
```

Then add the router in the console with its management address, port `443`, the
API key and (for self-signed certificates) TLS verification disabled. Prefer a
trusted certificate, or pin a certificate at your reverse proxy.

## Configuration

All backend settings are environment variables, validated in
`src/vyos_mgmt/config.py`; `.env.example` documents them. Highlights:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | dev-only | JWT signing **and** encryption of stored API keys. Rotating it invalidates sessions and encrypted credentials. |
| `DATABASE_URL` | local Docker DB | `postgresql+asyncpg://…` |
| `ACCESS_TOKEN_TTL_SECONDS` | `900` | Access-token lifetime |
| `REFRESH_TOKEN_TTL_DAYS` | `7` | Refresh-token lifetime |
| `COOKIE_SECURE` / `COOKIE_SAMESITE` | `false` / `lax` | Refresh cookie flags |
| `CORS_ORIGINS` | `http://localhost:3000,…` | Comma-separated, explicit origins only |
| `SERVE_FRONTEND` | `true` | Serve `frontend/out` from FastAPI |
| `BOOTSTRAP_ADMIN_*` | unset | First-run admin (only when no users exist) |
| `TRUSTED_PROXY_HEADERS` | `false` | Honour `X-Forwarded-For` for rate limiting |
| `VYOS_TIMEOUT_SECONDS` | `10` | pyvyos request timeout |

Production guardrails: startup refuses the default `SECRET_KEY`, short secrets,
`COOKIE_SECURE=false`, or wildcard CORS when `ENVIRONMENT=production`.

## Security model

- **Passwords:** Argon2id (64 MiB, t=3, p=4, 32-byte hash) with transparent
  rehash on login when parameters change.
- **Access token:** JWT HS256, 15 minutes, kept only in JavaScript memory (not
  localStorage). Page reloads use the refresh cookie.
- **Refresh token:** JWT with `jti`, stored hashed in PostgreSQL, rotated on
  every refresh, revoked on logout/password change; independently revocable per
  session. `HttpOnly`, `SameSite=Lax`, path-scoped to `/api/v1/auth`.
- **CSRF:** refresh/logout require `X-Requested-With: vyos-mgmt`, which forces a
  CORS preflight restricted to `CORS_ORIGINS`.
- **Device credentials:** API keys are encrypted at rest with Fernet using a key
  derived from `SECRET_KEY`; they are never returned by the API or written to
  logs/audit details.
- **RBAC:** enforced server-side on every route; the UI merely hides actions.
- **Rate limiting:** login attempts per IP + username; single-process in-memory
  limiter (swap for Redis if you scale horizontally).
- **Audit:** append-only `audit_logs` table; failures are surfaced as errors, not
  silently logged.
- **Headers:** `X-Content-Type-Options`, `X-Frame-Options: DENY`, referrer and
  permissions policies, `Cache-Control: no-store` for API responses.

For internet exposure, terminate TLS at a reverse proxy, set `COOKIE_SECURE=true`,
keep the database private, back up `SECRET_KEY`, and restrict who can reach the
console (VPN or allow-list).

## Testing

```bash
uv run pytest -q            # backend unit + API integration (Postgres required)
uv run ruff check src tests
pnpm --dir frontend exec tsc --noEmit
pnpm --dir frontend build   # must emit frontend/out
```

Backend integration tests use the `mock` driver and a separate
`vyos_mgmt_test` database; no VyOS appliance is required.

## API

- Interactive docs: `/api/docs`
- OpenAPI: `/api/openapi.json`
- Health: `/api/v1/health`
- Route maps: `/api/v1/routers/{router_id}/route-maps`
- Prefix lists: `/api/v1/routers/{router_id}/prefix-lists`
- OSPF: `/api/v1/routers/{router_id}/ospf/{version}` (`version` = `v2` or `v3`)
- Static routes: `/api/v1/routers/{router_id}/static-routes`
- WireGuard: `/api/v1/routers/{router_id}/wireguard`
- Contract: [`docs/api-contract.md`](docs/api-contract.md)

## Project layout

```
src/vyos_mgmt/
  api/routes/          auth, users, routers, bgp, route_maps, prefix_lists, ospf, static_routes, wireguard, audit, meta
  core/                JWT/Argon2, crypto, errors, middleware, rate limit
  db/                  models, async session
  features/registry.py extension point for feature modules
  schemas/             Pydantic request/response models
  services/            BGP, route-map, prefix-list, OSPF, static-route, WireGuard services + VyOS drivers
alembic/               database migrations
tests/                 unit + API integration tests
frontend/src/          Next.js app (static export), features/registry.tsx
frontend/README.md     frontend development/build notes
docs/api-contract.md   frontend/backend contract
```

## Known limitations / next steps

- BGP covers `ipv4-unicast` and `ipv6-unicast`; other address families are left
  untouched on the device but are not surfaced in the UI yet.
- The `mock` driver keeps its configuration in process memory; it is reseeded
  when the backend restarts. It is intended for demos, tests and UI development.
- BGP passwords are write-only through the API (intentional).
- Route maps expose the BGP-relevant match/set subset; unsupported VyOS
  directives on an existing rule are preserved when other fields are edited.
- AS-path and community-list objects are referenced by name and must exist on
  the device; they are managed outside this API for now (prefix lists are
  managed by the dedicated module).
- Route maps are attached to BGP **neighbors and peer groups** per address
  family (import/export) and to OSPF redistribution. Network/aggregate
  route-map attachments are not surfaced in the UI yet.
- OSPF area ranges/summarisation, virtual links and authentication are not
  exposed yet; interface/area/redistribution management and neighbor status are
  supported.
- Static routes cover unicast/blackhole/reject routes and next-hop
  address/interface/distance/disable. BFD, SRv6 segments, VRF leaking,
  non-main tables and multicast static routes are not exposed yet.
- VPN starts with WireGuard; IPsec, OpenVPN, firewall exceptions and static
  routes for tunnel traffic are not surfaced yet. WireGuard private/preshared
  keys are write-only and never returned by the API.
- VyOS stores route-map multi-value attributes (AS-path prepend, communities)
  as sets; identical duplicate entries are deduplicated when read back.
- Login rate limiting is per process; use Redis for multi-replica deployments.
- No scheduled configuration backups/diffs yet; those would be natural next
  feature modules.
