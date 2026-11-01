# VyOS Control — frontend

A Next.js static-export console for managing VyOS routers. The **BGP** module
covers global configuration, neighbors, peer groups, advertised networks and
live session health. The **Route maps** module manages `policy route-map` rules
that BGP uses as per-address-family import/export policy. The **Prefix lists**
module manages `policy prefix-list` / `policy prefix-list6` objects — the
permit/deny prefix sets referenced by route-map match conditions. The **OSPF**
module manages `protocols ospf` (OSPFv2/IPv4) and `protocols ospfv3`
(OSPFv3/IPv6): global settings, areas, interface activation, redistribution and
live neighbor state. The **Static routes** module manages
`protocols static route` / `protocols static route6`: unicast gateway routes
with one or more next hops, plus blackhole and reject routes. The **VPN** module
manages WireGuard (`interfaces wireguard wgN`): interfaces, key rotation, peers
and live handshake/transfer state. Each module is registered behind one registry
entry, so additional VyOS modules (firewall, interfaces, NAT, …) can be added
the same way.

- **Framework:** Next.js 15.5 (App Router, TypeScript strict), React 19
- **Styling:** Tailwind CSS v4 + shadcn/ui primitives (Radix), CVA + `cn`
- **Data:** `@tanstack/react-query` v5, in-memory access token, single-flight
  refresh
- **Forms:** `react-hook-form` + `zod` + `@hookform/resolvers`
- **Other:** `next-themes` (dark by default), `sonner`, `lucide-react`
- **Output:** fully static (`output: "export"`, `trailingSlash: true`) — no
  server actions, route handlers, middleware or runtime server dependency

## Requirements

- Node.js 20+ (built and validated on Node 26)
- pnpm 10+ (lockfile generated with pnpm 12)
- The FastAPI backend from this repository, for real data
- The app is usable without the backend running: every page renders and shows
  retryable error states instead of crashing.

## Install

Caches and the pnpm store must stay inside the workspace because the sandbox is
read-only outside it. A local `pnpm-workspace.yaml` isolates this package from
the parent repository's pnpm workspace.

```bash
cd frontend
export npm_config_cache=$PWD/../.cache/npm NEXT_TELEMETRY_DISABLED=1
pnpm install --store-dir=$PWD/../.cache/pnpm-store
```

`.npmrc` already points `store-dir`/`cache-dir` at `../.cache`, so the flags can
be omitted once the store is populated.

## Development

The API base URL defaults to `http://localhost:8000/api/v1` in development and
`/api/v1` in production builds. To override it, create `.env.local`:

```bash
cp .env.example .env.local
# NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
```

Run the backend on port 8000 (CORS allows `http://localhost:3000`), then:

```bash
pnpm dev        # http://localhost:3000
pnpm typecheck  # tsc --noEmit
```

If the backend is down, the login screen stays up and API calls show
“Cannot reach the API server…”.

## Static build & deployment

```bash
pnpm build
```

This writes `frontend/out/` with folder routes:

```
out/index.html
out/login/index.html
out/routers/index.html
out/bgp/index.html
out/bgp/neighbors/index.html
out/bgp/networks/index.html
out/bgp/peer-groups/index.html
out/bgp/settings/index.html
out/route-maps/index.html
out/prefix-lists/index.html
out/ospf/index.html
out/static-routes/index.html
out/vpn/index.html
out/settings/index.html
out/settings/users/index.html
out/audit/index.html
out/404.html
```

`NEXT_PUBLIC_API_BASE_URL` is baked in at build time. For the integrated
deployment (backend serves `out/` at `/` and the API at `/api/v1`) build with
the default or explicitly:

```bash
NEXT_PUBLIC_API_BASE_URL=/api/v1 pnpm build
```

Important: `next build` also reads `.env.local`. Do not leave a development
`.env.local` pointing at `http://localhost:8000` in a production build.

Preview the export locally with any static file server (remember trailing
slashes):

```bash
pnpm start      # npx serve out -l 3000
# open http://localhost:3000/login/
```

The backend is the recommended host: it serves the API and the export from the
same origin, so relative `/api/v1` and the HttpOnly refresh cookie work without
CORS caveats.

## Routes

| Route | Access | Purpose |
| --- | --- | --- |
| `/login/` | public | Branded sign-in, remember-me, rate-limit messaging |
| `/` | any signed-in | Fleet cards, per-router health, recent audit (admins), quick actions |
| `/routers/` | view any; mutate admin | Register routers, test connections, select active router |
| `/bgp/` | any signed-in | Global state, session health, peer table, quick actions (15 s poll) |
| `/bgp/neighbors/` | view any; mutate operator+ | Search/filter, create/edit/delete neighbors, per-AF policy |
| `/bgp/networks/` | view any; mutate operator+ | Advertised prefixes per address family |
| `/bgp/peer-groups/` | view any; mutate operator+ | Reusable peer templates and deletion |
| `/bgp/settings/` | view any; save operator+; teardown admin | Global ASN/router ID/logging + typed-name BGP teardown |
| `/route-maps/` | view any; mutate operator+ | Master-detail route maps, ordered permit/deny rules, match/set editor, `?map=<name>` selection; `in_use` references from BGP import/export policy and OSPF redistribution. IPv4/IPv6 prefix-list fields suggest existing lists via `<datalist>` |
| `/prefix-lists/` | view any; mutate operator+ | Master-detail prefix lists with IPv4/IPv6 tabs (with counts, `?family=ipv4` or `?family=ipv6`), ordered permit/deny rules with prefix + `ge`/`le`, `?list=<name>` selection, `in_use` references from route-map and BGP policy |
| `/ospf/` | view any; mutate operator+; process teardown admin | OSPFv2 (IPv4) / OSPFv3 (IPv6) selected by `?version=v2` or `?version=v3`, section tabs via `?tab=` (overview, interfaces, areas, redistribution, settings). Overview KPIs + neighbor table (15 s poll), area and interface CRUD, redistribution with route-map `<datalist>`, global form and typed-name process teardown |
| `/static-routes/` | view any; mutate operator+ | IPv4/IPv6 static routes with tabs (`?family=ipv4` or `?family=ipv6`, default IPv4): KPI strip (total, unicast, blackhole, reject), search over prefix/description/next hop, gateway routes with dynamic next-hop rows (address, interface, distance, enabled) and blackhole/reject routes with distance/tag. Create/edit/delete with canonical prefix + duplicate validation |
| `/vpn/` | view any; mutate operator+ | WireGuard master-detail: interface list selected by `?if=<name>`, interface create/edit, private-key rotation, peer CRUD (public key, allowed IPs, endpoint, keepalive, preshared key) and live handshake/transfer status (15 s poll) |
| `/settings/` | any signed-in | Profile, change password, theme |
| `/settings/users/` | admin | Account CRUD, role/active toggles, password reset |
| `/audit/` | admin | Paginated audit log with expandable JSON details |

Unknown routes render a static 404 page. Every page is prerendered at build
time; data is fetched client-side after mount.

## Session & security model

- The access token is kept **in memory only** (never localStorage,
  sessionStorage or a cookie) and attached as `Authorization: Bearer`.
- Bootstrap calls `POST /auth/refresh`; the refresh token is an HttpOnly cookie,
  so nothing sensitive is readable from JavaScript.
- `POST /auth/refresh` and `POST /auth/logout` send
  `X-Requested-With: vyos-mgmt`; every request uses `credentials: "include"`.
- A 401 triggers **one** shared refresh and then one retry. Concurrent 401s
  share a single refresh request (token rotation cannot race). If refresh
  fails, auth state is cleared and the user is sent to `/login/` with the
  original route as `?next=`.
- UI role gating is a convenience only; the API enforces authorization. Roles:
  viewer (read), operator (BGP, route-map, prefix-list, OSPF, static-route and
  WireGuard writes), admin (routers, users, audit, BGP and OSPF process
  teardown).

## Architecture

```
src/
  app/
    layout.tsx                 root providers (theme, query, auth, toasts)
    login/                     public sign-in (+ metadata layout)
    (app)/                     authenticated shell via AppShell
      page.tsx                 dashboard
      routers/  bgp/…  settings/…  audit/
    not-found.tsx  error.tsx  global-error.tsx  loading.tsx
  components/
    ui/                        shadcn/ui primitives
    app-shell.tsx              sidebar/topbar/breadcrumbs/module subnav
    sidebar.tsx  router-switcher.tsx  user-menu.tsx  theme-toggle.tsx
    states.tsx                 page headers, empty/error/loading, badges, role guard
    bgp/ routers/ users/       feature dialogs and shared BGP widgets
    route-maps/                rule editor, route-map dialogs, match/set summaries
    prefix-lists/              list/rule dialogs, family badges and ge/le helpers
    ospf/                      area/interface/redistribution dialogs, settings panel,
                               version labels, area-ID parsing and state badges
    static-routes/             route create/edit dialog (next-hop rows, type switch),
                               delete confirmation, family badges and hop labels
    vpn/                       interface/peer dialogs, key rotation, delete confirmations,
                               masked secret input, copy buttons and WireGuard helpers
  features/
    registry.tsx               single extension point for feature modules
  lib/
    api.ts                     typed fetch client, ApiError, refresh, CSRF
    auth.tsx                   AuthProvider (bootstrap, login, logout, refresh)
    router-context.tsx         RouterProvider (selection + ?router= sync)
    queries.ts                 query keys, fetchers, mutations, invalidation
    types.ts                   all types from docs/api-contract.md
    validation.ts              IP/prefix/AS validators
    form-errors.ts             map 422 details onto react-hook-form fields
    format.ts  roles.ts  utils.ts
```

### Adding a feature module

`src/features/registry.tsx` is the only navigation extension point. The sidebar,
the dashboard module cards and the module subnav all derive from `FEATURE_MODULES`.

1. Add folder routes under `src/app/(app)/<module>/` (no dynamic path segments —
   static export). Wrap pages in the authenticated `(app)` layout automatically.
2. Append one `FeatureModule` entry with `key`, `title`, `description`, `href`,
   `icon`, `nav`, `quickActions`, optional `roles` and `status`.
3. Add API types/hooks in `src/lib/types.ts` and `src/lib/queries.ts`.
4. Gate mutating actions with `canWrite` / `isAdmin` from `src/lib/roles.ts`;
   the backend remains authoritative.

## Notes / known boundaries

- **No backend at build time.** `pnpm build` performs no API calls; it produces
  HTML that boots into a session check in the browser.
- **Router selection** lives in client state, `localStorage` and an optional
  `?router=<uuid>` query string — never in a path segment, because static export
  cannot prerender unknown params. The selected route map uses the same pattern
  via `?map=<name>`, and the selected prefix list via `?family=ipv4|ipv6` +
  `?list=<name>` (the same name may exist in both families). OSPF keeps its
  version and section in `?version=v2|v3` and
  `?tab=overview|interfaces|areas|redistribution|settings`, next to the shared
  `?router=` parameter. The static-route page keeps its active family in
  `?family=ipv4|ipv6` (default `ipv4`), again next to `?router=`. The selected
  WireGuard interface uses `?if=<name>`; these URL parameters only ever contain
  names, never key material.
- **OSPF module:** one static page drives both address families. `v2` maps to
  `protocols ospf` and `v3` to `protocols ospfv3`; supported network types and
  redistribution sources differ (OSPFv3: broadcast / point-to-point, `ripng`
  instead of `rip`). Area IDs accept decimal or dotted input but are always
  written and displayed in canonical dotted decimal. `configured: false` is a
  normal response; the overview shows a not-configured empty state that links to
  the settings tab, and saving global settings creates the process (a
  global-only process is valid). Neighbor state polls every 15 s only while the
  overview tab is open and the process is configured; `status.error` explains a
  stopped daemon and a `502` renders as a retryable alert.
- **OSPF ↔ route maps:** redistribution entries may reference an existing route
  map (free text plus `<datalist>` suggestions, like prefix lists). OSPF writes
  invalidate the route-map list because route-map `in_use` / `used_by` changes,
  and route-map writes invalidate OSPF config/status. Deleting a referenced map
  is refused with `409 route_map_in_use`. Area deletion is refused while
  interfaces use it (`409 ospf_area_in_use`, `details.used_by`); the dialog also
  disables confirmation when `interface_count > 0`.
- **OSPF writes:** every config mutation (global PUT, area/interface/
  redistribution create-update-delete) returns the refreshed `OspfConfigRead`,
  which replaces the cached config; status and route maps are invalidated.
  Deleting a whole process is `204` and admin-only, requires typing the router
  name, and drops the cached config/status so the page re-reads
  `configured: false`.
- **Static routes:** one page manages both address families. The list is fetched
  once (`GET /routers/{id}/static-routes`) and the IPv4/IPv6 tabs filter it
  client-side so tab counts and the KPI strip stay instant; the API `?family=`
  filter is supported by the hook (`useStaticRoutes(routerId, { family })`) but
  not needed by the page. The active tab lives in `?family=ipv4|ipv6` (default
  `ipv4`) next to the shared `?router=` parameter via
  `window.history.replaceState`, so deep links and the registry quick actions
  work without a navigation.
- **Static-route writes:** `POST` and `PUT` send the full managed body
  (`description`, `blackhole`, `reject`, `distance`, `tag`, `next_hops`) and
  return the refreshed `StaticRouteRead`, which patches the list and detail
  caches before the list is invalidated; `DELETE` is `204` and drops both. Query
  keys are `["routers", id, "static-routes"]` with detail keys extending them by
  `family` + `prefix`, so list invalidation uses `{ exact: true }`. The prefix is
  URL-encoded as one path segment (`/static-routes/ipv4/10.0.0.0%2F8`). Family
  and prefix are immutable on edit: the form disables both, and changing either
  means deleting and recreating the route.
- **Static-route validation and errors:** the dialog validates canonical CIDR
  with host bits zero (`isPrefix`), family match, at least one next hop for
  gateway routes, at least one of address/interface per hop, family-correct host
  addresses, interface-name shape, next-hop distance (1–255), duplicate
  `(address, interface)` pairs, and blackhole/reject distance/tag ranges
  (distance 1–255, tag 1–4294967295). `409 static_route_exists` maps to the
  prefix field; `422 validation_error` details map to `prefix`, `description`,
  `distance`, `tag` and `next_hops[i].address|interface|distance`; anything else
  is shown as a form-level alert. The viewer role sees the table with a
  read-only banner and no mutation controls.
- **Route maps ↔ BGP:** neighbor and peer-group address-family editors load
  route-map names from `/routers/{id}/route-maps` and store them in
  `route_map_import` / `route_map_export`. Route-map `in_use` / `used_by` is
  derived by the API from the current BGP configuration; deletion of a
  referenced map is refused with `409 route_map_in_use`.
- **Route-map payload shape:** `set.as_path_prepend` and `set.community_values`
  are always arrays (`[]` when unset) and the route-map `DELETE` returns `204`;
  rule writes return the refreshed `RouteMapRead`.
- **Prefix lists ↔ route maps:** route-map `match.ipv4_prefix_list` /
  `match.ipv6_prefix_list` must name an existing prefix list, so the route-map
  rule editor offers the current names as `<datalist>` suggestions (free text is
  still allowed) and links to `/prefix-lists/`. Prefix-list writes return the
  refreshed `PrefixListRead` (the list `DELETE` returns `204`); the prefix-list
  list is invalidated by route-map and BGP writes because `in_use` / `used_by`
  derive from those references. Duplicate rule definitions are rejected with
  `409 prefix_list_rule_duplicate` and shown as a form-level error; in-use
  deletion (`409 prefix_list_in_use`) lists `details.used_by`.
- The BGP **advertised prefix** count on the dashboard is derived from each
  router's BGP configuration (network statements), not from device RIB counts.
- `GET /health` is assumed to be relative to the API base (`/api/v1/health`),
  per the “Meta / health” section of `docs/api-contract.md`.
- Write-only passwords: the API returns only `password_configured`; the UI never
  displays a stored password, offers replacement and explicit removal.
- All destructive actions use AlertDialogs; deleting a whole BGP configuration
  additionally requires typing the router name.
- **VPN / WireGuard secrets:** private keys and preshared keys are write-only.
  No GET, list, create, update or rotation response returns them; reads expose
  only the interface `public_key` (derived by the device) and the peer
  `has_preshared_key` flag. The UI keeps generated key material in form state
  only — never in localStorage, the URL, a toast or the console — and clears the
  dialog state on close. `POST /wireguard/keypair` and
  `POST /wireguard/preshared-key` return a secret exactly once and are not
  cached by react-query. A pasted private key cannot have its public key derived
  client-side, so the derived public key is only shown for keypairs generated in
  the same form; after saving, the interface detail shows it.
- **VPN / WireGuard preshared keys (tri-state):** on peer edit the
  `preshared_key` field is omitted when the replace field is left blank (the
  configured key is preserved), a typed/generated Base64 key replaces it, and
  the explicit “Remove the configured preshared key” checkbox sends `null`. A
  blank replace field never clears an existing key. Peer create sends `null`
  when the optional field is empty.
- **VPN / WireGuard cache and status:** query keys are
  `["routers", id, "wireguard"]` (list), `[..., name]` (detail) and
  `[..., name, "status"]`. Interface and peer create/update and key rotation
  return the refreshed detail, which replaces the detail cache, then the list
  (exact) and the live status are invalidated. Deletes invalidate list, detail
  and status (the peer DELETE is `204`). Live status polls every 15 s while an
  interface is selected and rows are joined to configuration by `public_key`;
  when the interface is configured but not running, `status.error` is shown and
  the table falls back to configured values. A `502` renders as a retryable
  alert.
- **VPN / WireGuard error mapping:** `409 wireguard_interface_exists` and
  `409 wireguard_peer_exists` become field errors on the name/alias,
  `422 wireguard_allowed_ips_conflict` on allowed IPs and
  `422 wireguard_public_key_conflict` on the public key; other `422` validation
  details are mapped to their form fields (including list-valued
  `addresses` / `allowed_ips`) with a form-level fallback.

## Scripts

| Command | Description |
| --- | --- |
| `pnpm dev` | Next dev server on :3000 |
| `pnpm build` | Production static export to `out/` |
| `pnpm typecheck` | Strict TypeScript check |
| `pnpm start` | Static preview with `serve` (downloads on first use) |
