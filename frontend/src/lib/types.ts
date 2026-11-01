/**
 * Types mirroring docs/api-contract.md exactly. Keep this file in lockstep with
 * the backend contract; the API is the source of truth.
 */

export type Role = "admin" | "operator" | "viewer";

export const ROLE_RANK: Record<Role, number> = {
  viewer: 0,
  operator: 1,
  admin: 2,
};

export interface User {
  id: string;
  username: string;
  email: string | null;
  role: Role;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export interface LoginRequest {
  username: string;
  password: string;
  remember_me: boolean;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export type Driver = "pyvyos" | "mock";
export type RouterProtocol = "https" | "http";

export interface Router {
  id: string;
  name: string;
  host: string;
  port: number;
  protocol: RouterProtocol;
  verify_tls: boolean;
  driver: Driver;
  description: string | null;
  api_key_configured: boolean;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface RouterCreate {
  name: string;
  host: string;
  port: number;
  protocol: RouterProtocol;
  api_key?: string;
  verify_tls: boolean;
  driver: Driver;
  description?: string | null;
}

export type RouterUpdate = Partial<RouterCreate>;

export interface SystemInfo {
  /** Nullable when the device is unreachable and identity could not be read. */
  hostname: string | null;
  version: string | null;
  uptime: string | null;
  driver: Driver;
  reachable: boolean;
  latency_ms: number | null;
  error: string | null;
}

export type AddressFamilyKey = "ipv4-unicast" | "ipv6-unicast";

export interface AddressFamilySettings {
  route_reflector_client: boolean;
  next_hop_self: boolean;
  soft_reconfiguration_inbound: boolean;
  default_originate: boolean;
  allowas_in: number | null;
  /** VyOS `route-map import <name>` for this address family. */
  route_map_import: string | null;
  /** VyOS `route-map export <name>` for this address family. */
  route_map_export: string | null;
}

export type AddressFamilies = Partial<
  Record<AddressFamilyKey, AddressFamilySettings>
>;

export interface BgpTimers {
  keepalive: number;
  holdtime: number;
}

export interface BgpNeighbor {
  address: string;
  /** Nullable when the session inherits its AS from a peer group. */
  remote_as: number | null;
  description: string | null;
  peer_group: string | null;
  update_source: string | null;
  ebgp_multihop: number | null;
  password_configured: boolean;
  passive: boolean;
  shutdown: boolean;
  timers: BgpTimers | null;
  local_as: number | null;
  address_families: AddressFamilies;
}

export interface BgpPeerGroup {
  name: string;
  /** Nullable on read when the device does not report a concrete AS. */
  remote_as: number | null;
  description: string | null;
  update_source: string | null;
  ebgp_multihop: number | null;
  password_configured: boolean;
  address_families: AddressFamilies;
}

export interface BgpNetwork {
  af: AddressFamilyKey;
  prefix: string;
}

export interface BgpGlobal {
  configured: boolean;
  system_as: number | null;
  router_id: string | null;
  log_neighbor_changes: boolean;
}

export interface BgpRouterRef {
  id: string;
  name: string;
}

export interface BgpConfig {
  router: BgpRouterRef;
  configured: boolean;
  global: BgpGlobal;
  neighbors: BgpNeighbor[];
  peer_groups: BgpPeerGroup[];
  networks: BgpNetwork[];
  supported_address_families: AddressFamilyKey[];
}

export interface BgpGlobalUpdate {
  system_as: number;
  router_id: string | null;
  log_neighbor_changes: boolean;
}

export interface BgpNeighborCreate {
  address: string;
  remote_as: number;
  description?: string | null;
  peer_group?: string | null;
  update_source?: string | null;
  ebgp_multihop?: number | null;
  password?: string | null;
  passive?: boolean;
  shutdown?: boolean;
  timers?: BgpTimers | null;
  local_as?: number | null;
  address_families?: AddressFamilies;
}

/**
 * PATCH semantics: omitted fields are untouched. `null` removes a setting;
 * `password: ""` removes the password; `timers: null` removes timers.
 */
export interface BgpNeighborUpdate {
  remote_as?: number;
  description?: string | null;
  peer_group?: string | null;
  update_source?: string | null;
  ebgp_multihop?: number | null;
  password?: string | null;
  passive?: boolean;
  shutdown?: boolean;
  timers?: BgpTimers | null;
  local_as?: number | null;
  address_families?: AddressFamilies;
}

export interface BgpPeerGroupCreate {
  name: string;
  remote_as: number;
  description?: string | null;
  update_source?: string | null;
  ebgp_multihop?: number | null;
  password?: string | null;
  address_families?: AddressFamilies;
}

export type BgpPeerGroupUpdate = Partial<Omit<BgpPeerGroupCreate, "name">>;

export interface BgpNetworkCreate {
  af: AddressFamilyKey;
  prefix: string;
}

export interface BgpPeerStatus {
  address: string;
  remote_as: number | null;
  state: string;
  established: boolean;
  uptime: string | null;
  prefixes_received: number | null;
  prefixes_sent: number | null;
  msg_received: number | null;
  msg_sent: number | null;
  description: string | null;
  address_family: string | null;
}

export interface BgpStatus {
  configured: boolean;
  router_id: string | null;
  local_as: number | null;
  peers: BgpPeerStatus[];
  total_peers: number;
  established_peers: number;
  collected_at: string;
  error: string | null;
}

/* -------------------------------------------------------------------------- */
/* Route maps (`policy route-map`)                                            */
/* -------------------------------------------------------------------------- */

export type RouteMapAction = "permit" | "deny";
export type RouteMapOrigin = "igp" | "egp" | "incomplete";
export type RouteMapProtocol =
  | "babel"
  | "bgp"
  | "connected"
  | "isis"
  | "kernel"
  | "ospf"
  | "ospfv3"
  | "rip"
  | "ripng"
  | "static"
  | "table"
  | "vnc";
export type RouteMapRpki = "invalid" | "notfound" | "valid";
/** `null` means "do not change"; `goto` requires `goto_rule`. */
export type RouteMapOnMatch = "next" | "goto";
export type RouteMapCommunityAction = "add" | "replace" | "delete" | "none";
export type RouteMapMetricType = "type-1" | "type-2";

/** All fields are optional in the sense that `null` / `false` = not configured. */
export interface RouteMapMatch {
  ipv4_prefix_list: string | null;
  ipv6_prefix_list: string | null;
  as_path: string | null;
  community_list: string | null;
  community_exact_match: boolean;
  large_community_list: string | null;
  extcommunity: string | null;
  /** 1–65535 */
  metric: number | null;
  /** 0–4294967295 */
  local_preference: number | null;
  origin: RouteMapOrigin | null;
  /** 1–65535 */
  tag: number | null;
  protocol: RouteMapProtocol | null;
  rpki: RouteMapRpki | null;
  ip_nexthop: string | null;
  ipv6_nexthop: string | null;
  interface: string | null;
}

export interface RouteMapSet {
  /** 0–4294967295 */
  local_preference: number | null;
  /** `0-4294967295`, `+N`, `-N`, `rtt`, `+rtt`, `-rtt` */
  metric: string | null;
  origin: RouteMapOrigin | null;
  /** 0–4294967295 */
  weight: number | null;
  /** OSPF metric type (`type-1` / `type-2`). */
  metric_type: RouteMapMetricType | null;
  /** 1–65535 */
  tag: number | null;
  /** At most 20 ASNs (1–4294967295). Always a list on the wire. */
  as_path_prepend: number[];
  community_action: RouteMapCommunityAction | null;
  /** Community values (`65000:100`) or well-known names (`no-export`). */
  community_values: string[];
  /** Community-list name, used when `community_action` is `delete`. */
  community_delete: string | null;
  /** IPv4 address, `unchanged` or `peer-address`. */
  ip_next_hop: string | null;
  /** IPv4 address. */
  originator_id: string | null;
}

export interface RouteMapRule {
  /** 1–65535 */
  number: number;
  action: RouteMapAction;
  description: string | null;
  match: RouteMapMatch;
  set: RouteMapSet;
  on_match: RouteMapOnMatch | null;
  /** Required when `on_match` is `goto`; must differ from `number`. */
  goto_rule: number | null;
  call: string | null;
  /** Rule number evaluated after this rule matches (continue). */
  continue_rule: number | null;
}

export interface RouteMap {
  name: string;
  description: string | null;
  /** Sorted by `number` ascending. */
  rules: RouteMapRule[];
  /** Derived from BGP configuration and route-map `call` references. */
  in_use: boolean;
  used_by: string[];
}

export interface RouteMapCreate {
  name: string;
  description?: string | null;
}

/** `PUT /route-maps/{name}` updates the description only. */
export interface RouteMapUpdate {
  description: string | null;
}

/** `POST /route-maps/{name}/rules` body (includes `number`). */
export interface RouteMapRuleCreate extends RouteMapRule {}

/** `PUT /route-maps/{name}/rules/{number}` body (number comes from the path). */
export type RouteMapRuleUpdate = Omit<RouteMapRuleCreate, "number">;

export interface RouteMapList extends Paginated<RouteMap> {}

/* -------------------------------------------------------------------------- */
/* Prefix lists (`policy prefix-list` / `policy prefix-list6`)                */
/* -------------------------------------------------------------------------- */

/** `ipv4` maps to `policy prefix-list`, `ipv6` to `policy prefix-list6`. */
export type PrefixListFamily = "ipv4" | "ipv6";

export interface PrefixListRule {
  /** 1–65535 */
  number: number;
  action: RouteMapAction;
  /** IPv4/IPv6 network in CIDR notation, host bits zero. */
  prefix: string;
  /** Nullable prefix-length lower bound (`>=` the prefix length). */
  ge: number | null;
  /** Nullable prefix-length upper bound. Both null = exact-length match. */
  le: number | null;
  description: string | null;
}

export interface PrefixList {
  name: string;
  family: PrefixListFamily;
  description: string | null;
  /** Sorted by `number` ascending. */
  rules: PrefixListRule[];
  /** Derived from route-map and BGP references; deleting is refused. */
  in_use: boolean;
  used_by: string[];
}

export interface PrefixListCreate {
  name: string;
  family: PrefixListFamily;
  description?: string | null;
}

/** `PUT /prefix-lists/{family}/{name}` updates the description only. */
export interface PrefixListUpdate {
  description: string | null;
}

/** `POST /prefix-lists/{family}/{name}/rules` body (includes `number`). */
export interface PrefixListRuleCreate extends PrefixListRule {}

/** `PUT /prefix-lists/{family}/{name}/rules/{number}` (number from the path). */
export type PrefixListRuleUpdate = Omit<PrefixListRuleCreate, "number">;

export interface PrefixListList extends Paginated<PrefixList> {}

/* -------------------------------------------------------------------------- */
/* OSPF (`protocols ospf` / `protocols ospfv3`)                              */
/* -------------------------------------------------------------------------- */

/** `v2` → `protocols ospf` (IPv4); `v3` → `protocols ospfv3` (IPv6). */
export type OspfVersion = "v2" | "v3";

/** `"none"` when no adjacency logging is configured. */
export type OspfLogAdjacencyChanges = "none" | "normal" | "detail";

/** OSPF area level; `no_summary` is only valid for `stub` / `nssa`. */
export type OspfAreaType = "normal" | "stub" | "nssa";

/** OSPFv3 supports only `broadcast` and `point-to-point`. */
export type OspfNetworkType =
  | "broadcast"
  | "non-broadcast"
  | "point-to-multipoint"
  | "point-to-point";

/** OSPF external metric type (`type-1` / `type-2` in VyOS). */
export type OspfMetricType = 1 | 2;

export interface OspfRouterRef {
  id: string;
  name: string;
}

/**
 * Global settings. Unset values are `null`; `log_adjacency_changes` is
 * `"none"` when unset. This is also the `PUT /global` write body (full
 * replacement of the managed fields).
 */
export interface OspfGlobal {
  router_id: string | null;
  log_adjacency_changes: OspfLogAdjacencyChanges;
  auto_cost_reference_bandwidth: number | null;
  default_information_originate: boolean;
  default_information_always: boolean;
  distance_global: number | null;
}

export interface OspfArea {
  /** Canonical dotted decimal, e.g. `0.0.0.1`. Sorted numerically. */
  area_id: string;
  area_type: OspfAreaType;
  /** Only valid for `stub` / `nssa`; totally-stub / totally-NSSA. */
  no_summary: boolean;
  interface_count: number;
}

export interface OspfAreaCreate {
  /** Decimal (`1`, `4294967295`) or dotted (`0.0.0.1`) input. */
  area_id: string;
  area_type: OspfAreaType;
  no_summary: boolean;
}

/** `PUT /areas/{area_id}` — the area ID is immutable. */
export type OspfAreaUpdate = Omit<OspfAreaCreate, "area_id">;

export interface OspfInterface {
  /** VyOS interface name; immutable on update. */
  name: string;
  /** `null` when the device reports a missing/invalid area. */
  area_id: string | null;
  network_type: OspfNetworkType | null;
  /** 1–65535; `null` means the device default applies. */
  cost: number | null;
  /** 1–65535 */
  hello_interval: number | null;
  /** 1–65535 */
  dead_interval: number | null;
  /** 0–255 */
  priority: number | null;
  passive: boolean;
  bfd: boolean;
  mtu_ignore: boolean;
  /** 1–65535 */
  retransmit_interval: number | null;
  /** 1–65535 */
  transmit_delay: number | null;
}

export interface OspfInterfaceCreate {
  /** `^[A-Za-z][A-Za-z0-9._-]{0,63}$` */
  name: string;
  /** Must reference an existing area; otherwise `422 ospf_area_not_found`. */
  area_id: string;
  network_type?: OspfNetworkType | null;
  cost?: number | null;
  hello_interval?: number | null;
  dead_interval?: number | null;
  priority?: number | null;
  passive?: boolean;
  bfd?: boolean;
  mtu_ignore?: boolean;
  retransmit_interval?: number | null;
  transmit_delay?: number | null;
}

/** `PUT /interfaces/{name}` — full replacement of the managed fields. */
export type OspfInterfaceUpdate = Omit<OspfInterfaceCreate, "name">;

export interface OspfRedistribute {
  /** Route source; immutable on update. */
  source: string;
  /** 1–16777214 */
  metric: number | null;
  metric_type: OspfMetricType | null;
  /** Must reference an existing route map. */
  route_map: string | null;
}

export interface OspfRedistributeCreate {
  source: string;
  metric?: number | null;
  metric_type?: OspfMetricType | null;
  route_map?: string | null;
}

/** `PUT /redistribute/{source}` — the source is immutable. */
export type OspfRedistributeUpdate = Omit<OspfRedistributeCreate, "source">;

export interface OspfConfig {
  router: OspfRouterRef;
  version: OspfVersion;
  /** True when any OSPF/OSPFv3 configuration exists on the device. */
  configured: boolean;
  global: OspfGlobal;
  /** Sorted numerically by area ID. */
  areas: OspfArea[];
  interfaces: OspfInterface[];
  redistributions: OspfRedistribute[];
  /** Version specific: v3 omits `non-broadcast` / `point-to-multipoint`. */
  supported_network_types: OspfNetworkType[];
  /** Version specific: v3 uses `ripng` instead of `rip`. */
  supported_redistribute_sources: string[];
}

export interface OspfNeighborStatus {
  neighbor_id: string;
  priority: number | null;
  /** Raw OSPF state, e.g. `Full/DR`, `2-Way`, `Init`. */
  state: string;
  dead_time: string | null;
  address: string | null;
  interface: string | null;
  established: boolean;
}

export interface OspfStatus {
  configured: boolean;
  version: OspfVersion;
  router_id: string | null;
  neighbors: OspfNeighborStatus[];
  total_neighbors: number;
  full_neighbors: number;
  collected_at: string;
  /** Non-null when the process is configured but the daemon is not running. */
  error: string | null;
}

/* -------------------------------------------------------------------------- */
/* Static routes (`protocols static route` / `protocols static route6`)       */
/* -------------------------------------------------------------------------- */

/** `ipv4` → `protocols static route`, `ipv6` → `protocols static route6`. */
export type StaticRouteFamily = "ipv4" | "ipv6";

/**
 * One next hop of a unicast static route. At least one of `address` /
 * `interface` is set; `address` is a host address without a prefix length.
 */
export interface StaticNextHop {
  /** IPv4/IPv6 host address, or `null` for an interface-only next hop. */
  address: string | null;
  /** VyOS interface name, or `null` for an address-only next hop. */
  interface: string | null;
  /** 1–255, or `null` for the device default. */
  distance: number | null;
  /** `false` maps to the VyOS `disable` node. */
  enabled: boolean;
}

/**
 * `GET /routers/{router_id}/static-routes` item. A route is either a unicast
 * route with next hops or a blackhole / reject route (mutually exclusive).
 */
export interface StaticRoute {
  family: StaticRouteFamily;
  /** Canonical CIDR (`ip_network`), host bits zero. */
  prefix: string;
  description: string | null;
  blackhole: boolean;
  reject: boolean;
  /** Only for blackhole / reject routes; `null` otherwise. */
  distance: number | null;
  /** Only for blackhole / reject routes; `null` otherwise. */
  tag: number | null;
  /** Empty for blackhole / reject routes. */
  next_hops: StaticNextHop[];
}

/** `POST /static-routes` body. Family and prefix are immutable afterwards. */
export interface StaticRouteCreate {
  family: StaticRouteFamily;
  prefix: string;
  description: string | null;
  blackhole: boolean;
  reject: boolean;
  distance: number | null;
  tag: number | null;
  next_hops: StaticNextHop[];
}

/**
 * `PUT /static-routes/{family}/{prefix}` — full replacement of the managed
 * fields. Unknown device leaves on retained next hops are preserved.
 */
export type StaticRouteUpdate = Omit<StaticRouteCreate, "family" | "prefix">;

export interface StaticRouteList extends Paginated<StaticRoute> {}

/* -------------------------------------------------------------------------- */
/* VPN / WireGuard (`interfaces wireguard`)                                   */
/* -------------------------------------------------------------------------- */

/**
 * `GET /routers/{router_id}/wireguard` item.
 *
 * The private key is write-only and never returned; `public_key` is derived by
 * the device from the configured private key (`null` when it has none).
 */
export interface WireGuardInterface {
  /** VyOS `^wg[0-9]+$`; immutable after creation. */
  name: string;
  description: string | null;
  /** Interface CIDRs (IPv4/IPv6), host bits allowed. */
  addresses: string[];
  /** Listening port; `null` means the device default/random. */
  port: number | null;
  /** `null` when the device default (1420) applies. */
  mtu: number | null;
  enabled: boolean;
  /** Safe to display and copy. */
  public_key: string | null;
  peer_count: number;
}

/** `WireGuardInterface` plus its peers, sorted by peer alias. */
export interface WireGuardInterfaceDetail extends WireGuardInterface {
  peers: WireGuardPeer[];
}

export interface WireGuardPeer {
  /** Alias, `^[^\s]{1,100}$`; immutable after creation. */
  name: string;
  description: string | null;
  public_key: string;
  /** Canonical prefixes; an exact prefix may belong to only one peer. */
  allowed_ips: string[];
  /** Remote address or FQDN, without the port. */
  endpoint: string | null;
  endpoint_port: number | null;
  /** 1–65535; `null` disables persistent keepalive. */
  persistent_keepalive: number | null;
  /** Preshared keys are write-only; reads only expose this flag. */
  has_preshared_key: boolean;
  enabled: boolean;
}

export interface WireGuardInterfaceCreate {
  name: string;
  description?: string | null;
  addresses?: string[];
  port?: number | null;
  mtu?: number | null;
  enabled?: boolean;
  /** Required and write-only (Base64 32-byte key). */
  private_key: string;
}

/**
 * `PUT /wireguard/{name}` — full replacement of the managed metadata fields.
 * The private key and the peers are untouched.
 */
export interface WireGuardInterfaceUpdate {
  description: string | null;
  addresses: string[];
  port: number | null;
  mtu: number | null;
  enabled: boolean;
}

/** `PUT /wireguard/{name}/private-key`. */
export interface WireGuardPrivateKeyUpdate {
  private_key: string;
}

export interface WireGuardPeerCreate {
  name: string;
  description?: string | null;
  public_key: string;
  allowed_ips: string[];
  endpoint?: string | null;
  endpoint_port?: number | null;
  persistent_keepalive?: number | null;
  /** Optional and write-only (Base64 32-byte key). */
  preshared_key?: string | null;
  enabled?: boolean;
}

/**
 * `PUT /wireguard/{name}/peers/{peer}` — full replacement of the managed peer
 * fields (including `public_key`); the alias is immutable. Omit
 * `preshared_key` to leave the configured one untouched.
 */
export type WireGuardPeerUpdate = Omit<WireGuardPeerCreate, "name">;

/** One-time output of `POST /wireguard/keypair` (never persisted). */
export interface WireGuardKeypair {
  private_key: string;
  public_key: string;
}

/** One-time output of `POST /wireguard/preshared-key`. */
export interface WireGuardPresharedKey {
  preshared_key: string;
}

/** One row of `show interfaces wireguard <name> summary`. */
export interface WireGuardStatusPeer {
  /** Joins to the configured peer by `public_key`. */
  public_key: string;
  /** `address:port` as reported by the device. */
  endpoint: string | null;
  allowed_ips: string[];
  latest_handshake: string | null;
  transfer_received: string | null;
  transfer_sent: string | null;
}

export interface WireGuardStatus {
  configured: boolean;
  name: string;
  public_key: string | null;
  listening_port: number | null;
  peers: WireGuardStatusPeer[];
  collected_at: string;
  /** Non-null when the interface is configured but not running. */
  error: string | null;
}

export interface WireGuardList extends Paginated<WireGuardInterface> {}

export interface AuditLog {
  id: string;
  actor_username: string;
  router_id: string | null;
  router_name: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  status: string;
  details: Record<string, unknown> | null;
  request_id: string | null;
  created_at: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
}

export interface AuditPage extends Paginated<AuditLog> {}

export interface UserCreate {
  username: string;
  email: string | null;
  password: string;
  role: Role;
}

export interface UserUpdate {
  email?: string | null;
  role?: Role;
  is_active?: boolean;
  password?: string;
}

export interface FeatureDescriptor {
  key: string;
  title: string;
  description: string;
  status: "available" | "planned" | string;
  href: string;
}

export interface HealthStatus {
  status: string;
  version: string;
  environment: string;
  database: string;
}

export interface ValidationDetail {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: ValidationDetail[] | Record<string, unknown> | null;
    request_id?: string | null;
  };
}

