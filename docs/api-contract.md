# API contract (v1)

This document is the source of truth shared by the backend and frontend. Both
are developed independently; change this file first, then the two sides.

Base URL in development: `http://localhost:8000/api/v1`
Base URL in a static deployment served by the backend: `/api/v1`

All JSON, UTF-8. Times are ISO 8601 with timezone. IDs are UUID strings.

## Authentication

- Access token: JWT (HS256), lifetime 15 minutes, sent as
  `Authorization: Bearer <token>`. Keep it **in memory only**.
- Refresh token: JWT in an `HttpOnly` cookie named `vyos_mgmt_refresh`, path
  `/api/v1/auth`, `SameSite=Lax` by default. The frontend must call auth
  endpoints with `credentials: "include"`.
- Every call to `POST /auth/refresh` and `POST /auth/logout` must send the
  header `X-Requested-With: vyos-mgmt` (CSRF defence; triggers CORS preflight).
- On page load call `POST /auth/refresh`; if it returns 401 show the login page.
- Access-token 401 responses should trigger exactly one refresh attempt and
  then retry the original request. On refresh failure, clear state and redirect
  to `/login/`.

### `POST /auth/login`

```json
{ "username": "admin", "password": "secret", "remember_me": true }
```

`200` → `TokenResponse`, sets refresh cookie. `remember_me=false` makes the
cookie a session cookie. Error: `401 invalid_credentials`, `429 rate_limited`
(with `Retry-After`).

### `POST /auth/refresh`

No body. Requires cookie + CSRF header. Rotates the refresh token.

`200` → `TokenResponse`. `401 invalid_refresh_token`.

### `POST /auth/logout`

Cookie + CSRF header. `204`. Always clears the cookie.

### `GET /auth/me`

Bearer. `200` → `UserRead`.

### `POST /auth/change-password`

Bearer.

```json
{ "current_password": "old", "new_password": "at-least-12-chars" }
```

`204`. All refresh tokens are revoked; the frontend must send the user to
`/login/`.

### `TokenResponse`

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "id": "9a9b...",
    "username": "admin",
    "email": "admin@example.com",
    "role": "admin",
    "is_active": true,
    "last_login_at": "2026-01-01T00:00:00Z",
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z"
  }
}
```

## Roles

`admin` > `operator` > `viewer`.

| Action | viewer | operator | admin |
| --- | --- | --- | --- |
| Read routers, BGP, route maps, prefix lists, OSPF, static routes, WireGuard | yes | yes | yes |
| Create/update/delete BGP objects | no | yes | yes |
| Create/update/delete route maps and rules | no | yes | yes |
| Create/update/delete prefix lists and rules | no | yes | yes |
| Create/update/delete OSPF areas, interfaces and redistribution | no | yes | yes |
| Create/update/delete IPv4/IPv6 static routes | no | yes | yes |
| Create/update/delete WireGuard interfaces, keys and peers | no | yes | yes |
| Delete an entire OSPF process | no | no | yes |
| Test router connection | yes | yes | yes |
| Create/update/delete routers | no | no | yes |
| Manage users | no | no | yes |
| Read audit log | no | no | yes |
| Delete whole BGP configuration | no | no | yes |

## Errors

Every error uses the same envelope:

```json
{
  "error": {
    "code": "router_unreachable",
    "message": "Could not reach 192.0.2.1:443 ...",
    "details": null,
    "request_id": "f00d..."
  }
}
```

- `401 not_authenticated` / `401 invalid_credentials` / `401 invalid_refresh_token`
- `403 forbidden` / `403 csrf_failed`
- `404` feature-specific (`router_not_found`, `neighbor_not_found`, ...)
- `409` feature-specific (`neighbor_exists`, `network_exists`, `router_exists`, ...)
- `422 validation_error` with `details: [{loc, msg, type, input}]`
- `429 rate_limited`
- `502 router_unreachable` / `router_command_failed`
- `500 internal_error`

The UI should show `error.message` and use `error.code` for special cases.

## Meta / health

- `GET /health` (public): `{status, version, environment, database}`. Returns
  `503` with `status: "degraded"` and `database: "error"` when the database is
  unreachable; container health checks rely on the status code.
- `GET /meta/features` (auth): list of feature descriptors. Current:
  ```json
  [
    {
      "key": "bgp",
      "title": "BGP",
      "description": "Border Gateway Protocol configuration and session health",
      "status": "available",
      "href": "/bgp/"
    },
    {
      "key": "route-maps",
      "title": "Route maps",
      "description": "Policy route-map rules for BGP and OSPF filtering and attribute changes",
      "status": "available",
      "href": "/route-maps/"
    },
    {
      "key": "prefix-lists",
      "title": "Prefix lists",
      "description": "IPv4 and IPv6 prefix-list policy objects used by route-map and BGP filters",
      "status": "available",
      "href": "/prefix-lists/"
    },
    {
      "key": "ospf",
      "title": "OSPF",
      "description": "OSPFv2 (IPv4) and OSPFv3 (IPv6) routing",
      "status": "available",
      "href": "/ospf/"
    },
    {
      "key": "static-routes",
      "title": "Static routes",
      "description": "IPv4/IPv6 static routes with next hops, blackhole and reject",
      "status": "available",
      "href": "/static-routes/"
    },
    {
      "key": "vpn",
      "title": "VPN",
      "description": "WireGuard tunnels and peers",
      "status": "available",
      "href": "/vpn/"
    }
  ]
  ```
  The frontend keeps its own static registry for rendering; this endpoint
  exists so future dynamic UIs can discover features.

## Users (admin)

- `GET /users` → `{items: UserRead[], total: number}`
- `POST /users`
  ```json
  { "username": "noc", "email": null, "password": "at-least-12-chars", "role": "operator" }
  ```
  → `201 UserRead`
- `PATCH /users/{id}` — all fields optional:
  `{email?, role?, is_active?, password?}` → `UserRead`
- `DELETE /users/{id}` → `204`

Rules: cannot delete/deactivate/demote the last active admin; cannot delete
yourself. Usernames are lowercase, 3–64 chars, `[a-z0-9._-]`.

## Routers

`GET /routers` → `{items: RouterRead[], total}` (any role)

`POST /routers` (admin)

```json
{
  "name": "edge-tokyo",
  "host": "192.0.2.10",
  "port": 443,
  "protocol": "https",
  "api_key": "vyos-api-key",
  "verify_tls": false,
  "driver": "pyvyos",
  "description": "Tokyo edge"
}
```

`driver` is `pyvyos` (real device) or `mock` (built-in demo/test device; no API
key needed). For `pyvyos` the API key is required. It is encrypted at rest and
never returned.

`RouterRead`

```json
{
  "id": "uuid",
  "name": "edge-tokyo",
  "host": "192.0.2.10",
  "port": 443,
  "protocol": "https",
  "verify_tls": false,
  "driver": "pyvyos",
  "description": "Tokyo edge",
  "api_key_configured": true,
  "created_by_id": "uuid",
  "created_at": "...",
  "updated_at": "..."
}
```

- `GET /routers/{id}` → `RouterRead`
- `PATCH /routers/{id}` (admin) — optional fields; `api_key: ""` clears it
- `DELETE /routers/{id}` (admin) → `204` (does not change the device)
- `POST /routers/{id}/test` → `SystemInfo` (200 even when unreachable;
  `reachable=false`, `error` populated)
- `GET /routers/{id}/system` → `SystemInfo` (502 if unreachable)

`SystemInfo`

```json
{
  "hostname": "edge-tokyo",
  "version": "VyOS 1.5-rolling-...",
  "uptime": "14d 03h 12m",
  "driver": "pyvyos",
  "reachable": true,
  "latency_ms": 42.1,
  "error": null
}
```

## BGP

All paths are under `/routers/{router_id}/bgp`. Read requires any role; writes
require operator or admin unless stated otherwise.

`GET ""` → `BgpConfigRead`

```json
{
  "router": { "id": "uuid", "name": "edge-tokyo" },
  "configured": true,
  "global": {
    "configured": true,
    "system_as": 64512,
    "router_id": "10.255.0.1",
    "log_neighbor_changes": true
  },
  "neighbors": [{
    "address": "192.0.2.1",
    "remote_as": 65001,
    "description": "Transit A",
    "peer_group": null,
    "update_source": null,
    "ebgp_multihop": 2,
    "password_configured": true,
    "passive": false,
    "shutdown": false,
    "timers": { "keepalive": 30, "holdtime": 90 },
    "local_as": null,
    "address_families": {
      "ipv4-unicast": {
        "route_reflector_client": false,
        "next_hop_self": true,
        "soft_reconfiguration_inbound": true,
        "default_originate": false,
        "allowas_in": null,
        "route_map_import": "BGP-IN",
        "route_map_export": "BGP-OUT"
      }
    }
  }],
  "peer_groups": [{
    "name": "transit",
    "remote_as": 65001,
    "description": "...",
    "update_source": null,
    "ebgp_multihop": null,
    "password_configured": false,
    "address_families": { "ipv4-unicast": { "...": "same shape" } }
  }],
  "networks": [
    { "af": "ipv4-unicast", "prefix": "203.0.113.0/24" }
  ],
  "supported_address_families": ["ipv4-unicast", "ipv6-unicast"]
}
```

Notes:

- `address_families` is keyed by AF; the presence of a key means the family is
  activated for that neighbor/peer-group. Only `ipv4-unicast` and
  `ipv6-unicast` are managed (other AFs on the device are left untouched but not
  shown).
- `route_map_import` / `route_map_export` are per-address-family route-map
  names (nullable). They map to
  `neighbor <peer> address-family <af> route-map import|export <name>` and are
  available on both neighbors and peer groups. Names are validated for shape,
  not existence; the UI offers the router's existing route maps.
- Passwords are never returned; only `password_configured`.
- All mutations return the refreshed `BgpConfigRead`, so the UI can replace its
  cache without an extra GET.

### Global

- `PUT /global` (operator) — full update of the managed global fields:
  ```json
  { "system_as": 64512, "router_id": "10.255.0.1", "log_neighbor_changes": true }
  ```
  `router_id: null` removes it. → `BgpConfigRead`
- `DELETE ""` (admin) → `204`, removes `protocols bgp` (destructive; the UI must
  ask for confirmation by typing the router name).

### Neighbors

- `POST /neighbors` (operator) — `BgpNeighborCreate`:
  ```json
  {
    "address": "192.0.2.1",
    "remote_as": 65001,
    "description": "Transit A",
    "peer_group": null,
    "update_source": "eth0",
    "ebgp_multihop": 2,
    "password": "optional-write-only",
    "passive": false,
    "shutdown": false,
    "timers": { "keepalive": 30, "holdtime": 90 },
    "local_as": null,
    "address_families": {
      "ipv4-unicast": {
        "route_reflector_client": false,
        "next_hop_self": true,
        "soft_reconfiguration_inbound": true,
        "default_originate": false,
        "allowas_in": null,
        "route_map_import": "BGP-IN",
        "route_map_export": "BGP-OUT"
      }
    }
  }
  ```
  If `address_families` is omitted it defaults to `ipv4-unicast`.
- `PATCH /neighbors/{address}` (operator) — partial update; omitted fields are
  untouched. `description`, `peer_group`, `update_source` set to `null`/`""`
  remove the setting; `password: ""` removes it; `timers: null` removes them;
  `address_families` (when present) is authoritative for the managed AFs, so
  included families are enabled and omitted ones removed.
- `DELETE /neighbors/{address}` (operator) → `BgpConfigRead`.

`address` may be an IPv4/IPv6 address or an interface name (unnumbered).

### Networks

- `POST /networks` (operator)
  ```json
  { "af": "ipv4-unicast", "prefix": "203.0.113.0/24" }
  ```
  Prefix must be a valid network (host bits zero) matching the AF.
- `DELETE /networks?af=ipv4-unicast&prefix=203.0.113.0%2F24` (operator)
  → `BgpConfigRead`.

### Peer groups

- `POST /peer-groups` (operator)
  ```json
  {
    "name": "transit",
    "remote_as": 65001,
    "description": null,
    "update_source": null,
    "ebgp_multihop": null,
    "password": null,
    "address_families": { "ipv4-unicast": { "...": "same AF shape" } }
  }
  ```
- `PATCH /peer-groups/{name}` (operator) — same partial semantics as neighbors.
- `DELETE /peer-groups/{name}` (operator) → `BgpConfigRead`.

### Status

`GET /status` → `BgpStatus`

```json
{
  "configured": true,
  "router_id": "10.255.0.1",
  "local_as": 64512,
  "peers": [{
    "address": "192.0.2.1",
    "remote_as": 65001,
    "state": "Established",
    "established": true,
    "uptime": "3d 04h 22m",
    "prefixes_received": 12,
    "prefixes_sent": 3,
    "msg_received": 120,
    "msg_sent": 118,
    "description": "Transit A",
    "address_family": "ipv4-unicast"
  }],
  "total_peers": 3,
  "established_peers": 2,
  "collected_at": "2026-01-01T00:00:00Z",
  "error": null
}
```

When BGP is not configured: `200` with `configured: false` and no peers.
When the router is unreachable: `502`.

## Prefix lists

Prefix-list management is a separate feature module backed by the VyOS
`policy prefix-list` (IPv4) and `policy prefix-list6` (IPv6) trees. It is the
object store used by the route-map `ipv4_prefix_list` / `ipv6_prefix_list`
match conditions (and by BGP prefix-list filters). Both families may use the
same name; the API always identifies an object by `family` + `name`.

Base path: `/routers/{router_id}/prefix-lists`. Read requires any role;
mutations require operator or admin.

Names match `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` (a safe subset of the VyOS
constraint; IPv4 and IPv6 names are independent).

### `PrefixListRead`

```json
{
  "name": "TRANSIT-IN",
  "family": "ipv4",
  "description": "Transit customer prefixes",
  "rules": [
    {
      "number": 10,
      "action": "permit",
      "prefix": "203.0.113.0/24",
      "ge": 24,
      "le": 32,
      "description": "Customer /24s"
    },
    {
      "number": 20,
      "action": "deny",
      "prefix": "0.0.0.0/0",
      "ge": null,
      "le": 32,
      "description": "Catch-all deny"
    }
  ],
  "in_use": true,
  "used_by": [
    "Route-map BGP-IN · rule 10 · IPv4 prefix-list"
  ]
}
```

Rules are sorted by `number` (ascending). `ge` / `le` are nullable prefix-length
bounds; `null` for both means an exact-length match. Rules without `action` or
`prefix` are omitted from reads (VyOS requires both).

`in_use` / `used_by` are derived from route-map and BGP configuration
references; deleting an in-use prefix list is refused.

### Write validation

- `action`: `permit` | `deny` (required).
- `prefix`: a valid IPv4/IPv6 network in CIDR notation; host bits must be zero.
- `ge` / `le`: IPv4 `0-32`, IPv6 `0-128`; each must be `>=` the prefix length;
  when both are present `ge <= le`.
- Duplicate rule definitions within one list (same `action`, `prefix`, `ge`,
  `le`) are rejected with `409 prefix_list_rule_duplicate`.
- `description`: up to 255 characters.
- Prefix-list rules may be added/removed without touching route-maps; VyOS
  re-evaluates the policy on commit.

### Endpoints

- `GET /prefix-lists?family=ipv4|ipv6` → `{items: PrefixListRead[], total}`
  (family optional; both families returned when omitted; sorted by family then
  name).
- `POST /prefix-lists`
  ```json
  { "name": "TRANSIT-IN", "family": "ipv4", "description": "Transit customer prefixes" }
  ```
  → `201 PrefixListRead` (empty `rules`); `409 prefix_list_exists`.
- `GET /prefix-lists/{family}/{name}` → `PrefixListRead`;
  `404 prefix_list_not_found`.
- `PUT /prefix-lists/{family}/{name}` — update description only:
  `{ "description": "new text or null" }` → `PrefixListRead`.
- `DELETE /prefix-lists/{family}/{name}` → `204`;
  `409 prefix_list_in_use` with `details: {"used_by": [...]}` when referenced.
- `POST /prefix-lists/{family}/{name}/rules` — full rule body including
  `number` → `PrefixListRead`; `409 prefix_list_rule_exists`.
- `PUT /prefix-lists/{family}/{name}/rules/{number}` — full replacement of the
  managed rule fields → `PrefixListRead`; `404 prefix_list_rule_not_found`.
  Unknown/unsupported fields on that rule are preserved.
- `DELETE /prefix-lists/{family}/{name}/rules/{number}` → `PrefixListRead`;
  `404 prefix_list_rule_not_found`.

### Rule write body

`POST` includes `number` (1–65535); `PUT` takes the number from the path.

```json
{
  "number": 10,
  "action": "permit",
  "prefix": "203.0.113.0/24",
  "ge": 24,
  "le": 32,
  "description": "Customer /24s"
}
```

Audit actions: `prefix_list.create`, `prefix_list.update`,
`prefix_list.delete`, `prefix_list.rule.create`,
`prefix_list.rule.update`, `prefix_list.rule.delete`
(resource type `prefix_list` / `prefix_list_rule`).

## Route maps

Route-map management is a separate feature module backed by the VyOS
`policy route-map` configuration tree. It is used by the BGP neighbor / peer
group `route_map_import` and `route_map_export` fields described above, and by
OSPF/OSPFv3 redistribution. Route maps reference prefix-list / AS-path /
community-list objects by name.
Prefix lists are managed by the dedicated **Prefix lists** module above; AS-path
and community-list objects are still managed on the device for now.

Base path: `/routers/{router_id}/route-maps`. Read requires any role; mutations
require operator or admin.

All route-map names match `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`.

### `RouteMapRead`

```json
{
  "name": "BGP-IN",
  "description": "Inbound filtering for transit",
  "rules": [{
    "number": 10,
    "action": "permit",
    "description": "Allow transit prefixes",
    "match": {
      "ipv4_prefix_list": "TRANSIT-IN",
      "ipv6_prefix_list": null,
      "as_path": null,
      "community_list": "CUSTOMER-COMM",
      "community_exact_match": false,
      "large_community_list": null,
      "extcommunity": null,
      "metric": null,
      "local_preference": null,
      "origin": "igp",
      "tag": null,
      "protocol": "bgp",
      "rpki": "valid",
      "ip_nexthop": null,
      "ipv6_nexthop": null,
      "interface": null
    },
    "set": {
      "local_preference": 200,
      "metric": "+50",
      "origin": "igp",
      "weight": null,
      "metric_type": null,
      "tag": null,
      "as_path_prepend": [64512, 64512],
      "community_action": "add",
      "community_values": ["64512:100"],
      "community_delete": null,
      "ip_next_hop": null,
      "originator_id": null
    },
    "on_match": "next",
    "goto_rule": null,
    "call": null,
    "continue_rule": null
  }],
  "in_use": true,
  "used_by": [
    "BGP neighbor 192.0.2.1 · ipv4-unicast · import"
  ]
}
```

Rules are returned sorted by `number` (ascending). `in_use` / `used_by` are
derived from the current BGP configuration (and route-map `call` references) and
are informational; deleting an in-use route map is refused.

`match` fields are optional; `null` / `false` means "not configured".
`set.metric` accepts `0-4294967295`, `+N`, `-N`, `rtt`, `+rtt`, `-rtt`.
`set.community_action` is one of `add`, `replace`, `delete`, `none` or `null`:

- `add` / `replace`: `community_values` contains community values
  (`65000:100`) or well-known names (`no-export`, `blackhole`, …).
- `delete`: `community_delete` contains a community-list name.
- `none`: remove all communities.
- `null`: do not change communities.

`on_match` is `null`, `"next"` or `"goto"`; when `"goto"`, `goto_rule` is
required and must differ from the rule number.

### Endpoints

- `GET /route-maps` → `{items: RouteMapRead[], total: number}` (sorted by name)
- `POST /route-maps`
  ```json
  { "name": "BGP-IN", "description": "Inbound filtering" }
  ```
  → `201 RouteMapRead` (empty `rules`); `409 route_map_exists`.
- `GET /route-maps/{name}` → `RouteMapRead`; `404 route_map_not_found`.
- `PUT /route-maps/{name}` — update the description only (rules are managed
  below): `{ "description": "new text or null" }` → `RouteMapRead`.
- `DELETE /route-maps/{name}` → `204`; `409 route_map_in_use` with
  `details: {"used_by": [...]}` when referenced.
- `POST /route-maps/{name}/rules` — body is the full rule (see below, including
  `number`) → `RouteMapRead`; `409 rule_exists`.
- `PUT /route-maps/{name}/rules/{number}` — full replacement of the managed
  fields of an existing rule → `RouteMapRead`; `404 rule_not_found`.
  Unknown/unsupported VyOS fields on that rule are preserved.
- `DELETE /route-maps/{name}/rules/{number}` → `RouteMapRead`;
  `404 rule_not_found`.

### Rule write body

`POST` includes `number` (1–65535); `PUT` takes the number from the path.

```json
{
  "number": 10,
  "action": "permit",
  "description": "Allow transit prefixes",
  "match": {
    "ipv4_prefix_list": "TRANSIT-IN",
    "ipv6_prefix_list": null,
    "as_path": null,
    "community_list": "CUSTOMER-COMM",
    "community_exact_match": false,
    "large_community_list": null,
    "extcommunity": null,
    "metric": null,
    "local_preference": null,
    "origin": "igp",
    "tag": null,
    "protocol": "bgp",
    "rpki": "valid",
    "ip_nexthop": null,
    "ipv6_nexthop": null,
    "interface": null
  },
  "set": {
    "local_preference": 200,
    "metric": "+50",
    "origin": null,
    "weight": null,
    "metric_type": null,
    "tag": null,
    "as_path_prepend": [64512, 64512],
    "community_action": "add",
    "community_values": ["64512:100"],
    "community_delete": null,
    "ip_next_hop": null,
    "originator_id": null
  },
  "on_match": "next",
  "goto_rule": null,
  "call": null,
  "continue_rule": null
}
```

Validation summary:

- `action`: `permit` | `deny` (required).
- `protocol`: `babel`, `bgp`, `connected`, `isis`, `kernel`, `ospf`, `ospfv3`,
  `rip`, `ripng`, `static`, `table`, `vnc`.
- `origin`: `igp`, `egp`, `incomplete`.
- `rpki`: `invalid`, `notfound`, `valid`.
- `metric` (match): 1–65535; `local_preference` (match): 0–4294967295;
  `tag`: 1–65535.
- `set.metric`: validated expression described above.
- `set.weight` / `set.local_preference`: 0–4294967295.
- `set.as_path_prepend`: at most 20 ASNs (1–4294967295); always a JSON array
  (`[]` clears it).
- `set.community_values`: always a JSON array (`[]` when not applicable).
- `set.metric_type`: `type-1` or `type-2` (VyOS/FRR OSPF external metric type).
- Route-map names are limited to 64 characters. Referenced policy-object names
  may be up to 128 characters. Prefix-list references must exist in the
  matching family (managed by the Prefix lists module); AS-path / community-list
  references are validated for shape only and are still managed on the device.
- `set.ip_next_hop`: IPv4 address, `unchanged` or `peer-address`.
- `set.originator_id`, `match.ip_nexthop`: IPv4 address.
- `match.ipv6_nexthop`: IPv6 address.

Audit actions: `route_map.create`, `route_map.update`, `route_map.delete`,
`route_map.rule.create`, `route_map.rule.update`, `route_map.rule.delete`
(resource type `route_map` / `route_map_rule`). Details contain the route-map
name, rule number, action and the managed fields — never credentials.

## OSPF

OSPFv2 (IPv4) and OSPFv3 (IPv6) are managed by one feature module, selected by
a `version` path segment:

- `v2` → VyOS `protocols ospf` (IPv4)
- `v3` → VyOS `protocols ospfv3` (IPv6)

Base path: `/routers/{router_id}/ospf`. Read requires any role; mutations
require operator or admin except deleting the whole process, which requires
admin.

### Concepts

- **Global** settings: router ID, adjacency logging, auto-cost reference
  bandwidth, default-information originate, and global administrative distance.
- **Areas** are identified by a canonical dotted-decimal area ID. Input accepts
  either a decimal area number (`0`, `1`, `4294967295`) or dotted notation
  (`0.0.0.0`); responses always use dotted decimal. OSPFv2 can additionally use
  area network statements in the CLI, but this API activates OSPF through
  **interfaces** only (the recommended VyOS model).
- **Interfaces** are the unit that activates OSPF. Each interface must reference
  an existing area. Network type choices differ by version; OSPFv3 supports only
  `broadcast` and `point-to-point`.
- **Redistribution** supports the route sources valid for the selected version.
  `route_map` must reference an existing route map.

Levels: normal, stub, NSSA, totally-stub/NSSA (`no_summary`) are supported.
Area range/summarisation, virtual links and authentication are not exposed yet.

### `OspfConfigRead`

```json
{
  "router": { "id": "uuid", "name": "edge-tokyo" },
  "version": "v2",
  "configured": true,
  "global": {
    "router_id": "10.255.0.1",
    "log_adjacency_changes": "detail",
    "auto_cost_reference_bandwidth": 1000,
    "default_information_originate": true,
    "default_information_always": false,
    "distance_global": 110
  },
  "areas": [
    { "area_id": "0.0.0.0", "area_type": "normal", "no_summary": false, "interface_count": 1 },
    { "area_id": "0.0.0.1", "area_type": "stub", "no_summary": true, "interface_count": 1 }
  ],
  "interfaces": [{
    "name": "eth0",
    "area_id": "0.0.0.0",
    "network_type": "point-to-point",
    "cost": 10,
    "hello_interval": 10,
    "dead_interval": 40,
    "priority": 1,
    "passive": false,
    "bfd": true,
    "mtu_ignore": false,
    "retransmit_interval": null,
    "transmit_delay": null
  }],
  "redistributions": [{
    "source": "connected",
    "metric": 20,
    "metric_type": 2,
    "route_map": "OSPF-OUT"
  }],
  "supported_network_types": [
    "broadcast", "non-broadcast", "point-to-multipoint", "point-to-point"
  ],
  "supported_redistribute_sources": [
    "babel", "bgp", "connected", "isis", "kernel", "rip", "static"
  ]
}
```

- `configured` is true when any OSPF/OSPFv3 configuration exists. A global-only
  process is possible without any interface.
- Global values that are unset are `null`; `log_adjacency_changes` is `"none"`
  when unset.
- Area IDs are canonical dotted decimal and sorted numerically.
- Interfaces with a missing/invalid area are still returned with `area_id:
  null` (they cannot be created through this API).
- `supported_network_types` and `supported_redistribute_sources` are version
  specific (v3: `broadcast`, `point-to-point`; sources `babel`, `bgp`,
  `connected`, `isis`, `kernel`, `ripng`, `static`).

### `OspfGlobal`

Write body for `PUT /global` (full replacement of the managed fields):

```json
{
  "router_id": "10.255.0.1",
  "log_adjacency_changes": "detail",
  "auto_cost_reference_bandwidth": 1000,
  "default_information_originate": true,
  "default_information_always": false,
  "distance_global": 110
}
```

Validation: router ID IPv4; log `none|normal|detail`; auto-cost 1–4294967;
distance 1–255; `default_information_always` requires
`default_information_originate`.

### `OspfAreaRead` and writes

```json
{ "area_id": "0.0.0.0", "area_type": "normal", "no_summary": false, "interface_count": 1 }
```

- `POST /areas` body `{ "area_id": "0.0.0.0", "area_type": "normal", "no_summary": false }`
  → `201 OspfConfigRead`; `409 ospf_area_exists`.
- `PUT /areas/{area_id}` updates `area_type`/`no_summary` (area ID immutable)
  → `OspfConfigRead`.
- `DELETE /areas/{area_id}` → `OspfConfigRead`; `409 ospf_area_in_use` with
  `details.used_by` (interface names) while interfaces reference it.
- `no_summary` is only valid for `stub`/`nssa`.

### `OspfInterfaceRead` and writes

- `POST /interfaces` body:
  ```json
  {
    "name": "eth0",
    "area_id": "0.0.0.0",
    "network_type": "point-to-point",
    "cost": 10,
    "hello_interval": 10,
    "dead_interval": 40,
    "priority": 1,
    "passive": false,
    "bfd": true,
    "mtu_ignore": false,
    "retransmit_interval": null,
    "transmit_delay": null
  }
  ```
  → `201 OspfConfigRead`; `409 ospf_interface_exists`; `422 ospf_area_not_found`
  when the area is missing.
- `PUT /interfaces/{name}` — full replacement of the managed fields; `name` is
  immutable. Unknown device fields are preserved.
- `DELETE /interfaces/{name}` → `OspfConfigRead`.
- Ranges: cost 1–65535, hello/dead/retransmit/transmit 1–65535, priority 0–255.
- Interface names use the safe VyOS interface shape
  `^[A-Za-z][A-Za-z0-9._-]{0,63}$`.
- Network types must be allowed for the version. Unset values are `null` and
  the device default applies.

### `OspfRedistributeRead` and writes

```json
{ "source": "connected", "metric": 20, "metric_type": 2, "route_map": "OSPF-OUT" }
```

- `POST /redistribute` body `{source, metric?, metric_type?, route_map?}`
  → `201 OspfConfigRead`; `409 ospf_redistribute_exists`.
- `PUT /redistribute/{source}` — update metric/metric-type/route-map
  (source immutable) → `OspfConfigRead`.
- `DELETE /redistribute/{source}` → `OspfConfigRead`.
- `source` must be in `supported_redistribute_sources` for the version;
  metric 1–16777214; metric type `1` or `2`; `route_map` must reference an
  existing route map (`422 route_map_not_found` otherwise).

### Status

`GET /routers/{router_id}/ospf/{version}/status` → `OspfStatus`

```json
{
  "configured": true,
  "version": "v2",
  "router_id": "10.255.0.1",
  "neighbors": [{
    "neighbor_id": "10.0.0.2",
    "priority": 1,
    "state": "Full/DR",
    "dead_time": "38.365s",
    "address": "10.0.0.2",
    "interface": "eth0",
    "established": true
  }],
  "total_neighbors": 2,
  "full_neighbors": 2,
  "collected_at": "2026-01-01T00:00:00Z",
  "error": null
}
```

Sources: `show ip ospf neighbor` (v2), `show ipv6 ospfv3 neighbor` (v3).
When no OSPF configuration exists: `200` with `configured: false` and no
neighbors. When the router is unreachable: `502`. If the process is configured
but not running, `configured` reflects the configuration and `error` explains
the daemon state.

### Other endpoints

- `GET /ospf/{version}` → `OspfConfigRead`; `404` only for an unknown version
  (the config itself may be empty with `configured: false`).
- `PUT /ospf/{version}/global` → `OspfConfigRead`.
- `DELETE /ospf/{version}` (admin) → `204`, removes the whole
  `protocols ospf` / `protocols ospfv3` subtree.

Audit actions: `ospf.global.update`, `ospf.delete`, `ospf.area.create`,
`ospf.area.update`, `ospf.area.delete`, `ospf.interface.create`,
`ospf.interface.update`, `ospf.interface.delete`, `ospf.redistribute.create`,
`ospf.redistribute.update`, `ospf.redistribute.delete`
(resource types `ospf_area`, `ospf_interface`, `ospf_redistribute`).

Route-map references from OSPF redistribution participate in route-map
`in_use`/`used_by` detection, so an OSPF-referenced route map cannot be deleted.

## Static routes

IPv4 (`protocols static route`) and IPv6 (`protocols static route6`) static
routes are managed by one module. The module covers unicast gateway routes,
interface routes and blackhole/reject routes; BFD, SRv6 segments, VRF leaking,
non-main routing tables and multicast (`mroute`) are not exposed yet.

Base path: `/routers/{router_id}/static-routes`. Read requires any role;
mutations require operator or admin.

### Model

A route is either a **unicast** route with one or more next hops, or a
**blackhole** / **reject** route. Prefixes are canonical (`ip_network`,
host bits zero) and family-specific.

`StaticNextHop`:

```json
{
  "address": "192.0.2.1",
  "interface": "eth0",
  "distance": 10,
  "enabled": true
}
```

- `address` is an IPv4/IPv6 host address (no prefix), or `null` for an
  interface-only next hop.
- `interface` is an interface name, or `null` for an address-only next hop.
- At least one of `address` / `interface` is required. Both may be set (VyOS
  `next-hop <address> interface <if>`).
- `distance` is 1–255, or `null` for the device default.
- `enabled: false` maps to the VyOS `disable` node.
- Duplicate `(address, interface)` pairs within a route are rejected.

`StaticRouteRead`:

```json
{
  "family": "ipv4",
  "prefix": "0.0.0.0/0",
  "description": "Default via transit",
  "blackhole": false,
  "reject": false,
  "distance": null,
  "tag": null,
  "next_hops": [{
    "address": "192.0.2.254",
    "interface": null,
    "distance": null,
    "enabled": true
  }]
}
```

- `blackhole` and `reject` are mutually exclusive.
- For `blackhole`/`reject`, `next_hops` is empty; `distance` (1–255) and `tag`
  (1–4294967295) are optional.
- For a unicast route, `next_hops` has at least one entry and `distance`/`tag`
  are `null`.
- `description` is optional, max 255 characters.

### Writes

`POST /static-routes` — create (201 `StaticRouteRead`):

```json
{
  "family": "ipv4",
  "prefix": "10.0.0.0/8",
  "description": "Lab block",
  "blackhole": false,
  "reject": false,
  "distance": null,
  "tag": null,
  "next_hops": [
    { "address": "192.0.2.1", "interface": "eth0", "distance": 10, "enabled": true },
    { "interface": "eth1", "address": null, "distance": null, "enabled": true }
  ]
}
```

- `409 static_route_exists` for a duplicate family+prefix.
- `422 validation_error` for family/prefix mismatch, host bits set, invalid
  next hop, duplicate next hop, blackhole/reject with next hops, a unicast route
  without next hops, or `distance`/`tag` on a unicast route.

`PUT /static-routes/{family}/{prefix}` — full replacement of the managed fields
(`description`, `blackhole`, `reject`, `distance`, `tag`, `next_hops`). Family
and prefix are immutable. Unknown device leaves on retained next hops are
preserved.

`DELETE /static-routes/{family}/{prefix}` — 204.

`GET /static-routes` — list, optional `?family=ipv4|ipv6`; returns
`{ "items": [StaticRouteRead], "total": N }`, sorted by family then prefix.

`GET /static-routes/{family}/{prefix}` — one route. The prefix path uses a path
converter, so both `10.0.0.0/8` and its URL-encoded form are accepted.

### Errors and audit

- `404 static_route_not_found`
- `409 static_route_exists`
- `422 validation_error` (details include a field loc for form mapping)

Audit actions: `static_route.create`, `static_route.update`,
`static_route.delete` (resource type `static_route`, resource id
`family:prefix`).

## VPN / WireGuard

The VPN module starts with **WireGuard** (`interfaces wireguard wgN`). IPsec and
OpenVPN can be added later without changing the existing routes. The API is
deliberately separate from interface addressing: only the WireGuard tree is
managed.

Base path: `/routers/{router_id}/wireguard`. Read requires any role; every
mutation and key generation requires operator or admin.

### Secrets and keys

WireGuard uses Base64-encoded 32-byte keys.

- **Private key** (interface) is write-only. It is never returned by any GET,
  list, create, update or key-rotation response.
- **Preshared key** (peer) is write-only; reads only expose
  `has_preshared_key`.
- Validation errors redact secret inputs (`private_key`, `preshared_key`), and
  audit entries never contain key material.
- `public_key` on an interface is derived from the configured private key; it is
  safe to display and copy.
- Key generation endpoints return secrets **once** and do not write to the
  device. The client is responsible for storing/copying them.

### `WireGuardInterfaceRead`

```json
{
  "name": "wg0",
  "description": "Tokyo branch tunnel",
  "addresses": ["10.100.0.1/24"],
  "port": 51820,
  "mtu": 1420,
  "enabled": true,
  "public_key": "EKY0dxRrSD98QHjfHOK13mZ5PJ7hnddRZt5woB3szyw=",
  "peer_count": 2
}
```

- `name` matches VyOS `^wg[0-9]+$`.
- `addresses` are interface CIDRs (IPv4/IPv6), one per value.
- `port` is the listening port; `null` means the device default/random.
- `mtu` is `null` when the device default (1420) applies.
- `public_key` is `null` if the device has no valid private key.

### `WireGuardPeerRead`

```json
{
  "name": "branch-office",
  "description": "Branch router",
  "public_key": "XMrlPykaxhdAAiSjhtPlvi30NVkvLQliQuKP7AI7CyI=",
  "allowed_ips": ["192.168.50.0/24"],
  "endpoint": "198.51.100.10",
  "endpoint_port": 51820,
  "persistent_keepalive": 25,
  "has_preshared_key": true,
  "enabled": true
}
```

- Peer aliases match `^[^\s]{1,100}$`.
- `endpoint` is the remote address **or** FQDN (without the port); the API maps
  IPv4/IPv6 to VyOS `peer <name> address` and FQDNs to `peer <name> host-name`.
- `endpoint_port` is the remote UDP port.
- `allowed_ips` are canonical prefixes. The same exact prefix cannot be assigned
  to two peers (VyOS restriction) → `422 wireguard_allowed_ips_conflict`.
- The same public key cannot be assigned to two peers →
  `422 wireguard_public_key_conflict`.

### `WireGuardInterfaceDetail`

`WireGuardInterfaceRead` plus `peers: WireGuardPeerRead[]`, sorted by peer name.

### Writes

`POST /wireguard` — create an interface (201 `WireGuardInterfaceDetail`):

```json
{
  "name": "wg0",
  "description": "Tokyo branch tunnel",
  "addresses": ["10.100.0.1/24"],
  "port": 51820,
  "mtu": 1420,
  "enabled": true,
  "private_key": "iJJyEARGK52Ls1GYRCcFvPuTj7WyWYDo//BknoDU0XY="
}
```

- `private_key` is required and write-only.
- `409 wireguard_interface_exists`.

`PUT /wireguard/{name}` — full replacement of the managed metadata fields
(`description`, `addresses`, `port`, `mtu`, `enabled`). The private key and peers
are untouched.

`PUT /wireguard/{name}/private-key` — rotate the private key:

```json
{ "private_key": "4Krkv8h6NkAYMMaBWI957yYDJDMvj9URTHstdlOcDU0=" }
```

Returns `WireGuardInterfaceDetail`; peers must be updated with the new public key
out of band.

`DELETE /wireguard/{name}` — 204; removes the interface and all peers.

`POST /wireguard/{name}/peers` — create a peer (201 detail):

```json
{
  "name": "branch-office",
  "description": "Branch router",
  "public_key": "XMrlPykaxhdAAiSjhtPlvi30NVkvLQliQuKP7AI7CyI=",
  "allowed_ips": ["192.168.50.0/24"],
  "endpoint": "198.51.100.10",
  "endpoint_port": 51820,
  "persistent_keepalive": 25,
  "preshared_key": null,
  "enabled": true
}
```

- `409 wireguard_peer_exists` for a duplicate alias.
- `allowed_ips` is non-empty; each entry is IPv4/IPv6 CIDR.
- Ranges: port/persistent keepalive 1–65535; MTU 68–16000.

`PUT /wireguard/{name}/peers/{peer}` — full replacement of the managed peer
fields (including `public_key`); the alias is immutable. `preshared_key` is
tri-state: **omitted** preserves the configured key, a Base64 string replaces
it, and `null` removes it. The API never returns the key itself.

`DELETE /wireguard/{name}/peers/{peer}` — 204.

### Key generation

`POST /wireguard/keypair` — operator+; returns a one-time keypair:

```json
{
  "private_key": "iJJyEARGK52Ls1GYRCcFvPuTj7WyWYDo//BknoDU0XY=",
  "public_key": "EKY0dxRrSD98QHjfHOK13mZ5PJ7hnddRZt5woB3szyw="
}
```

`POST /wireguard/preshared-key` — operator+; returns:

```json
{ "preshared_key": "OHH2EwZfMNK+1L6BXbYw3bKCtMrfjpR4mCAEeBlFnRs=" }
```

These endpoints do not touch the device and are not audited with key material.
They must be declared before `/{name}` so they are not captured as interface
names.

### Status

`GET /wireguard/{name}/status` → `WireGuardStatus`

```json
{
  "configured": true,
  "name": "wg0",
  "public_key": "EKY0dxRrSD98QHjfHOK13mZ5PJ7hnddRZt5woB3szyw=",
  "listening_port": 51820,
  "peers": [{
    "public_key": "XMrlPykaxhdAAiSjhtPlvi30NVkvLQliQuKP7AI7CyI=",
    "endpoint": "198.51.100.10:51820",
    "allowed_ips": ["192.168.50.0/24"],
    "latest_handshake": "23 hours, 45 minutes, 26 seconds ago",
    "transfer_received": "1.26 MiB",
    "transfer_sent": "6.47 MiB"
  }],
  "collected_at": "2026-01-01T00:00:00Z",
  "error": null
}
```

Source: `show interfaces wireguard <name> summary`. The interface must exist
(`404 wireguard_interface_not_found`). A configured but not-running interface
returns `error` with an empty/short peer list. Router connection failures map to
`502`.

### Other endpoints

- `GET /wireguard` → `{ "items": [WireGuardInterfaceRead], "total": N }`, sorted
  by interface name.
- `GET /wireguard/{name}` → `WireGuardInterfaceDetail`.
- `POST /wireguard` / `PUT /wireguard/{name}` / peer writes return the refreshed
  detail.
- `404 wireguard_interface_not_found` / `404 wireguard_peer_not_found`.

Audit actions: `wireguard.interface.create`, `wireguard.interface.update`,
`wireguard.interface.delete`, `wireguard.private_key.update`,
`wireguard.peer.create`, `wireguard.peer.update`, `wireguard.peer.delete`
(resource types `wireguard_interface`, `wireguard_peer`). Key material is never
included in audit details.

## Audit

`GET /audit?limit=20&offset=0` (admin, max limit 200) →

```json
{
  "items": [{
    "id": "uuid",
    "actor_username": "admin",
    "router_id": "uuid",
    "router_name": "edge-tokyo",
    "action": "bgp.neighbor.create",
    "resource_type": "bgp_neighbor",
    "resource_id": "192.0.2.1",
    "status": "success",
    "details": { "remote_as": 65001 },
    "request_id": "...",
    "created_at": "..."
  }],
  "total": 42
}
```

## Static deployment

The frontend is a Next.js static export (`output: "export"`, `trailingSlash:
true`). It must never call the API at build time. The backend optionally serves
`frontend/out` at `/` after the API routes.

`NEXT_PUBLIC_API_BASE_URL` is baked in at build time. Default it to `/api/v1`.
For local dev use `http://localhost:8000/api/v1` (backend CORS allows
`http://localhost:3000`). `credentials: "include"` must be used for auth calls.

Because static export cannot pre-render unknown dynamic params:

- use trailing-slash, folder-based routes only;
- keep selected router in client state (localStorage + optional `?router=<id>`
  query string), not in a path segment;
- wrap `useSearchParams()` usage in `<Suspense>`.
