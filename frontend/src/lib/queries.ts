"use client";

import { useCallback } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api, buildQuery } from "@/lib/api";
import type {
  AuditPage,
  BgpConfig,
  BgpGlobalUpdate,
  BgpNetworkCreate,
  BgpNeighborCreate,
  BgpNeighborUpdate,
  BgpPeerGroupCreate,
  BgpPeerGroupUpdate,
  BgpStatus,
  ChangePasswordRequest,
  Driver,
  HealthStatus,
  OspfAreaCreate,
  OspfAreaUpdate,
  OspfConfig,
  OspfGlobal,
  OspfInterfaceCreate,
  OspfInterfaceUpdate,
  OspfRedistributeCreate,
  OspfRedistributeUpdate,
  OspfStatus,
  OspfVersion,
  Paginated,
  PrefixList,
  PrefixListCreate,
  PrefixListFamily,
  PrefixListList,
  PrefixListRuleCreate,
  PrefixListRuleUpdate,
  PrefixListUpdate,
  Router,
  RouteMap,
  RouteMapCreate,
  RouteMapList,
  RouteMapRuleCreate,
  RouteMapRuleUpdate,
  RouteMapUpdate,
  RouterCreate,
  RouterProtocol,
  RouterUpdate,
  StaticRoute,
  StaticRouteCreate,
  StaticRouteFamily,
  StaticRouteList,
  StaticRouteUpdate,
  SystemInfo,
  User,
  UserCreate,
  UserUpdate,
  WireGuardInterface,
  WireGuardInterfaceCreate,
  WireGuardInterfaceDetail,
  WireGuardInterfaceUpdate,
  WireGuardKeypair,
  WireGuardList,
  WireGuardPeerCreate,
  WireGuardPeerUpdate,
  WireGuardPresharedKey,
  WireGuardPrivateKeyUpdate,
  WireGuardStatus,
} from "@/lib/types";

export const queryKeys = {
  routers: ["routers"] as const,
  system: (routerId: string) => ["routers", routerId, "system"] as const,
  bgpConfig: (routerId: string) =>
    ["routers", routerId, "bgp", "config"] as const,
  bgpStatus: (routerId: string) =>
    ["routers", routerId, "bgp", "status"] as const,
  routeMaps: (routerId: string) =>
    ["routers", routerId, "route-maps"] as const,
  prefixLists: (routerId: string) =>
    ["routers", routerId, "prefix-lists"] as const,
  /** Prefix key for every OSPF version and status of one router. */
  ospf: (routerId: string) => ["routers", routerId, "ospf"] as const,
  ospfConfig: (routerId: string, version: OspfVersion) =>
    ["routers", routerId, "ospf", version] as const,
  ospfStatus: (routerId: string, version: OspfVersion) =>
    ["routers", routerId, "ospf", version, "status"] as const,
  /**
   * List key for one router's static routes. Detail keys extend it
   * (`[..., "static-routes", family, prefix]`), so list invalidation must pass
   * `{ exact: true }` to avoid refetching every open detail.
   */
  staticRoutes: (routerId: string) =>
    ["routers", routerId, "static-routes"] as const,
  staticRoute: (
    routerId: string,
    family: StaticRouteFamily,
    prefix: string,
  ) => ["routers", routerId, "static-routes", family, prefix] as const,
  /**
   * List key for one router's WireGuard interfaces. Detail keys extend it
   * (`[..., "wireguard", name]`), so list invalidation must pass
   * `{ exact: true }` to avoid refetching every open detail.
   */
  wireguard: (routerId: string) =>
    ["routers", routerId, "wireguard"] as const,
  wireguardInterface: (routerId: string, name: string) =>
    ["routers", routerId, "wireguard", name] as const,
  wireguardStatus: (routerId: string, name: string) =>
    ["routers", routerId, "wireguard", name, "status"] as const,
  users: ["users"] as const,
  audit: (limit: number, offset: number) =>
    ["audit", limit, offset] as const,
  health: ["health"] as const,
};

const POLL_INTERVAL = 15_000;

/* -------------------------------------------------------------------------- */
/* Read hooks                                                                 */
/* -------------------------------------------------------------------------- */

export function useRouters(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.routers,
    queryFn: ({ signal }) => api.get<Paginated<Router>>("/routers", signal),
    enabled: options.enabled ?? true,
    staleTime: 20_000,
    retry: 1,
  });
}

export function useSystemInfo(
  routerId: string | null | undefined,
  options: { poll?: number | false; enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: queryKeys.system(routerId ?? "none"),
    queryFn: ({ signal }) =>
      api.get<SystemInfo>(`/routers/${routerId}/system`, signal),
    enabled: !!routerId && (options.enabled ?? true),
    staleTime: 10_000,
    // 502 router_unreachable is a normal, displayed state — don't hammer.
    retry: 0,
    refetchInterval: options.poll ?? false,
  });
}

export function useBgpStatus(
  routerId: string | null | undefined,
  options: { poll?: number | false; enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: queryKeys.bgpStatus(routerId ?? "none"),
    queryFn: ({ signal }) =>
      api.get<BgpStatus>(`/routers/${routerId}/bgp/status`, signal),
    enabled: !!routerId && (options.enabled ?? true),
    staleTime: 10_000,
    retry: 0,
    refetchInterval: options.poll === undefined ? POLL_INTERVAL : options.poll,
    refetchIntervalInBackground: false,
  });
}

export function useBgpConfig(
  routerId: string | null | undefined,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: queryKeys.bgpConfig(routerId ?? "none"),
    queryFn: ({ signal }) =>
      api.get<BgpConfig>(`/routers/${routerId}/bgp`, signal),
    enabled: !!routerId && (options.enabled ?? true),
    staleTime: 10_000,
    retry: 0,
  });
}

export function useRouteMaps(
  routerId: string | null | undefined,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: queryKeys.routeMaps(routerId ?? "none"),
    queryFn: ({ signal }) =>
      api.get<RouteMapList>(`/routers/${routerId}/route-maps`, signal),
    enabled: !!routerId && (options.enabled ?? true),
    staleTime: 10_000,
    // 502 router_unreachable is a normal, displayed state.
    retry: 0,
  });
}

/** Both families are fetched once; `family` filters the cached list client-side. */
export function usePrefixLists(
  routerId: string | null | undefined,
  options: { enabled?: boolean; family?: PrefixListFamily } = {},
) {
  const family = options.family;
  // Stable identity: a new `select` on every render would recompute the
  // observer snapshot for no reason.
  const select = useCallback(
    (data: PrefixListList): PrefixListList => {
      if (!family) return data;
      const items = data.items.filter((item) => item.family === family);
      return { items, total: items.length };
    },
    [family],
  );
  return useQuery({
    queryKey: queryKeys.prefixLists(routerId ?? "none"),
    queryFn: ({ signal }) =>
      api.get<PrefixListList>(`/routers/${routerId}/prefix-lists`, signal),
    enabled: !!routerId && (options.enabled ?? true),
    staleTime: 10_000,
    // 502 router_unreachable is a normal, displayed state.
    retry: 0,
    select,
  });
}

export function useOspfConfig(
  routerId: string | null | undefined,
  version: OspfVersion,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: queryKeys.ospfConfig(routerId ?? "none", version),
    queryFn: ({ signal }) =>
      api.get<OspfConfig>(`/routers/${routerId}/ospf/${version}`, signal),
    enabled: !!routerId && (options.enabled ?? true),
    staleTime: 10_000,
    // 502 router_unreachable is a normal, displayed state.
    retry: 0,
  });
}

/**
 * Live neighbor state. Polls every 15 s by default (the overview tab is the
 * only consumer); pass `poll: false` to freeze it. 502 router_unreachable is a
 * normal, displayed state, so retries are disabled.
 */
export function useOspfStatus(
  routerId: string | null | undefined,
  version: OspfVersion,
  options: { poll?: number | false; enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: queryKeys.ospfStatus(routerId ?? "none", version),
    queryFn: ({ signal }) =>
      api.get<OspfStatus>(
        `/routers/${routerId}/ospf/${version}/status`,
        signal,
      ),
    enabled: !!routerId && (options.enabled ?? true),
    staleTime: 10_000,
    retry: 0,
    refetchInterval: options.poll === undefined ? POLL_INTERVAL : options.poll,
    refetchIntervalInBackground: false,
  });
}

/**
 * Both families are fetched once; `family` filters the cached list client-side
 * (the API also supports `?family=`, but one cached list keeps tab counts free).
 */
export function useStaticRoutes(
  routerId: string | null | undefined,
  options: { enabled?: boolean; family?: StaticRouteFamily } = {},
) {
  const family = options.family;
  // Stable identity: a new `select` on every render would recompute the
  // observer snapshot for no reason.
  const select = useCallback(
    (data: StaticRouteList): StaticRouteList => {
      if (!family) return data;
      const items = data.items.filter((item) => item.family === family);
      return { items, total: items.length };
    },
    [family],
  );
  return useQuery({
    queryKey: queryKeys.staticRoutes(routerId ?? "none"),
    queryFn: ({ signal }) =>
      api.get<StaticRouteList>(`/routers/${routerId}/static-routes`, signal),
    enabled: !!routerId && (options.enabled ?? true),
    staleTime: 10_000,
    // 502 router_unreachable is a normal, displayed state.
    retry: 0,
    select,
  });
}

/** One route. Disabled until a family and prefix are provided. */
export function useStaticRoute(
  routerId: string | null | undefined,
  family: StaticRouteFamily,
  prefix: string | null | undefined,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: queryKeys.staticRoute(
      routerId ?? "none",
      family,
      prefix ?? "none",
    ),
    queryFn: ({ signal }) =>
      api.get<StaticRoute>(
        staticRoutePath(routerId ?? "", family, prefix ?? ""),
        signal,
      ),
    enabled: !!routerId && !!prefix && (options.enabled ?? true),
    staleTime: 10_000,
    retry: 0,
  });
}

export function useWireGuardInterfaces(
  routerId: string | null | undefined,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: queryKeys.wireguard(routerId ?? "none"),
    queryFn: ({ signal }) =>
      api.get<WireGuardList>(`/routers/${routerId}/wireguard`, signal),
    enabled: !!routerId && (options.enabled ?? true),
    staleTime: 10_000,
    // 502 router_unreachable is a normal, displayed state.
    retry: 0,
  });
}

/** Interface metadata plus peers. Disabled until an interface is selected. */
export function useWireGuardInterface(
  routerId: string | null | undefined,
  name: string | null | undefined,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: queryKeys.wireguardInterface(routerId ?? "none", name ?? "none"),
    queryFn: ({ signal }) =>
      api.get<WireGuardInterfaceDetail>(
        `/routers/${routerId}/wireguard/${encodeURIComponent(name ?? "")}`,
        signal,
      ),
    enabled: !!routerId && !!name && (options.enabled ?? true),
    staleTime: 10_000,
    retry: 0,
  });
}

/**
 * Live peer state (`show interfaces wireguard <name> summary`). Polls every
 * 15 s by default; pass `poll: false` to freeze it. A configured but stopped
 * interface answers `200` with `error` populated, so retries are disabled.
 */
export function useWireGuardStatus(
  routerId: string | null | undefined,
  name: string | null | undefined,
  options: { poll?: number | false; enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: queryKeys.wireguardStatus(routerId ?? "none", name ?? "none"),
    queryFn: ({ signal }) =>
      api.get<WireGuardStatus>(
        `/routers/${routerId}/wireguard/${encodeURIComponent(name ?? "")}/status`,
        signal,
      ),
    enabled: !!routerId && !!name && (options.enabled ?? true),
    staleTime: 10_000,
    retry: 0,
    refetchInterval: options.poll === undefined ? POLL_INTERVAL : options.poll,
    refetchIntervalInBackground: false,
  });
}

export function useHealth(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => api.get<HealthStatus>("/health", signal),
    enabled: options.enabled ?? true,
    staleTime: 20_000,
    retry: 1,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}

export function useUsers(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.users,
    queryFn: ({ signal }) => api.get<Paginated<User>>("/users", signal),
    enabled: options.enabled ?? true,
    staleTime: 15_000,
    retry: 1,
  });
}

export function useAudit(
  limit = 20,
  offset = 0,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: queryKeys.audit(limit, offset),
    queryFn: ({ signal }) =>
      api.get<AuditPage>(`/audit${buildQuery({ limit, offset })}`, signal),
    enabled: options.enabled ?? true,
    staleTime: 10_000,
    retry: 0,
    placeholderData: keepPreviousData,
  });
}

/* -------------------------------------------------------------------------- */
/* Router mutations                                                           */
/* -------------------------------------------------------------------------- */

export interface RouterPayload {
  name: string;
  host: string;
  port: number;
  protocol: RouterProtocol;
  api_key?: string;
  verify_tls: boolean;
  driver: Driver;
  description: string | null;
}

export function useTestRouter() {
  return useMutation<SystemInfo, Error, string>({
    mutationFn: (routerId) =>
      api.post<SystemInfo>(`/routers/${routerId}/test`),
  });
}

export function useCreateRouter() {
  const queryClient = useQueryClient();
  return useMutation<Router, Error, RouterPayload>({
    mutationFn: (payload) =>
      api.post<Router>("/routers", payload satisfies RouterCreate),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.routers });
    },
  });
}

export function useUpdateRouter() {
  const queryClient = useQueryClient();
  return useMutation<
    Router,
    Error,
    { routerId: string; payload: RouterUpdate }
  >({
    mutationFn: ({ routerId, payload }) =>
      api.patch<Router>(`/routers/${routerId}`, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.routers });
    },
  });
}

export function useDeleteRouter() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (routerId) => api.delete<void>(`/routers/${routerId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.routers });
    },
  });
}

/* -------------------------------------------------------------------------- */
/* BGP mutations                                                              */
/* -------------------------------------------------------------------------- */

function useBgpMutation<TVariables>(
  routerId: string,
  mutationFn: (variables: TVariables) => Promise<BgpConfig>,
) {
  const queryClient = useQueryClient();
  return useMutation<BgpConfig, Error, TVariables>({
    mutationFn,
    onSuccess: (config) => {
      // All mutations return the refreshed config, so replace the cache
      // instead of spending a second round-trip.
      queryClient.setQueryData(queryKeys.bgpConfig(routerId), config);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.bgpStatus(routerId),
      });
      // Route-map `in_use` / `used_by` is derived from BGP policy references.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.routeMaps(routerId),
      });
      // Prefix-list `in_use` / `used_by` is derived from the same references
      // (route-map matches and BGP policy), so refresh it too.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.prefixLists(routerId),
      });
    },
  });
}

export function useUpdateBgpGlobal(routerId: string) {
  return useBgpMutation<BgpGlobalUpdate>(routerId, (payload) =>
    api.put<BgpConfig>(`/routers/${routerId}/bgp/global`, payload),
  );
}

export function useDeleteBgpConfig(routerId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, Error, void>({
    mutationFn: () => api.delete<void>(`/routers/${routerId}/bgp`),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.bgpConfig(routerId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.bgpStatus(routerId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.routeMaps(routerId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.prefixLists(routerId),
      });
    },
  });
}

export function useCreateNeighbor(routerId: string) {
  return useBgpMutation<BgpNeighborCreate>(routerId, (payload) =>
    api.post<BgpConfig>(`/routers/${routerId}/bgp/neighbors`, payload),
  );
}

export function useUpdateNeighbor(routerId: string) {
  return useBgpMutation<{ address: string; payload: BgpNeighborUpdate }>(
    routerId,
    ({ address, payload }) =>
      api.patch<BgpConfig>(
        `/routers/${routerId}/bgp/neighbors/${encodeURIComponent(address)}`,
        payload,
      ),
  );
}

export function useDeleteNeighbor(routerId: string) {
  return useBgpMutation<string>(routerId, (address) =>
    api.delete<BgpConfig>(
      `/routers/${routerId}/bgp/neighbors/${encodeURIComponent(address)}`,
    ),
  );
}

export function useCreateNetwork(routerId: string) {
  return useBgpMutation<BgpNetworkCreate>(routerId, (payload) =>
    api.post<BgpConfig>(`/routers/${routerId}/bgp/networks`, payload),
  );
}

export function useDeleteNetwork(routerId: string) {
  return useBgpMutation<BgpNetworkCreate>(routerId, ({ af, prefix }) =>
    api.delete<BgpConfig>(
      `/routers/${routerId}/bgp/networks${buildQuery({ af, prefix })}`,
    ),
  );
}

export function useCreatePeerGroup(routerId: string) {
  return useBgpMutation<BgpPeerGroupCreate>(routerId, (payload) =>
    api.post<BgpConfig>(`/routers/${routerId}/bgp/peer-groups`, payload),
  );
}

export function useUpdatePeerGroup(routerId: string) {
  return useBgpMutation<{ name: string; payload: BgpPeerGroupUpdate }>(
    routerId,
    ({ name, payload }) =>
      api.patch<BgpConfig>(
        `/routers/${routerId}/bgp/peer-groups/${encodeURIComponent(name)}`,
        payload,
      ),
  );
}

export function useDeletePeerGroup(routerId: string) {
  return useBgpMutation<string>(routerId, (name) =>
    api.delete<BgpConfig>(
      `/routers/${routerId}/bgp/peer-groups/${encodeURIComponent(name)}`,
    ),
  );
}

/* -------------------------------------------------------------------------- */
/* OSPF mutations                                                             */
/* -------------------------------------------------------------------------- */

function ospfPath(routerId: string, version: OspfVersion): string {
  return `/routers/${routerId}/ospf/${version}`;
}

/**
 * Every OSPF config write returns the refreshed `OspfConfigRead`, so replace
 * the cached config instead of spending a second round-trip. Status is derived
 * from the device, and route-map `in_use` / `used_by` changes because OSPF
 * redistribution references route maps.
 */
function useOspfMutation<TVariables>(
  routerId: string,
  version: OspfVersion,
  mutationFn: (variables: TVariables) => Promise<OspfConfig>,
) {
  const queryClient = useQueryClient();
  return useMutation<OspfConfig, Error, TVariables>({
    mutationFn,
    onSuccess: (config) => {
      queryClient.setQueryData(queryKeys.ospfConfig(routerId, version), config);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.ospfConfig(routerId, version),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.ospfStatus(routerId, version),
      });
      // Route-map `in_use` / `used_by` includes OSPF redistribution references.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.routeMaps(routerId),
      });
    },
  });
}

export function useUpdateOspfGlobal(routerId: string, version: OspfVersion) {
  return useOspfMutation<OspfGlobal>(routerId, version, (payload) =>
    api.put<OspfConfig>(`${ospfPath(routerId, version)}/global`, payload),
  );
}

/** Admin only. The endpoint returns `204` and removes the whole subtree. */
export function useDeleteOspfProcess(routerId: string, version: OspfVersion) {
  const queryClient = useQueryClient();
  return useMutation<void, Error, void>({
    mutationFn: () => api.delete<void>(ospfPath(routerId, version)),
    onSuccess: () => {
      // Drop the stale configuration so the page re-reads `configured: false`
      // and the status query stops reporting old neighbors.
      queryClient.removeQueries({
        queryKey: queryKeys.ospfConfig(routerId, version),
      });
      queryClient.removeQueries({
        queryKey: queryKeys.ospfStatus(routerId, version),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.ospfConfig(routerId, version),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.ospfStatus(routerId, version),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.routeMaps(routerId),
      });
    },
  });
}

export function useCreateOspfArea(routerId: string, version: OspfVersion) {
  return useOspfMutation<OspfAreaCreate>(routerId, version, (payload) =>
    api.post<OspfConfig>(`${ospfPath(routerId, version)}/areas`, payload),
  );
}

export function useUpdateOspfArea(routerId: string, version: OspfVersion) {
  return useOspfMutation<{ areaId: string; payload: OspfAreaUpdate }>(
    routerId,
    version,
    ({ areaId, payload }) =>
      api.put<OspfConfig>(
        `${ospfPath(routerId, version)}/areas/${encodeURIComponent(areaId)}`,
        payload,
      ),
  );
}

export function useDeleteOspfArea(routerId: string, version: OspfVersion) {
  return useOspfMutation<string>(routerId, version, (areaId) =>
    api.delete<OspfConfig>(
      `${ospfPath(routerId, version)}/areas/${encodeURIComponent(areaId)}`,
    ),
  );
}

export function useCreateOspfInterface(routerId: string, version: OspfVersion) {
  return useOspfMutation<OspfInterfaceCreate>(routerId, version, (payload) =>
    api.post<OspfConfig>(`${ospfPath(routerId, version)}/interfaces`, payload),
  );
}

export function useUpdateOspfInterface(routerId: string, version: OspfVersion) {
  return useOspfMutation<{ name: string; payload: OspfInterfaceUpdate }>(
    routerId,
    version,
    ({ name, payload }) =>
      api.put<OspfConfig>(
        `${ospfPath(routerId, version)}/interfaces/${encodeURIComponent(name)}`,
        payload,
      ),
  );
}

export function useDeleteOspfInterface(routerId: string, version: OspfVersion) {
  return useOspfMutation<string>(routerId, version, (name) =>
    api.delete<OspfConfig>(
      `${ospfPath(routerId, version)}/interfaces/${encodeURIComponent(name)}`,
    ),
  );
}

export function useCreateOspfRedistribute(
  routerId: string,
  version: OspfVersion,
) {
  return useOspfMutation<OspfRedistributeCreate>(
    routerId,
    version,
    (payload) =>
      api.post<OspfConfig>(
        `${ospfPath(routerId, version)}/redistribute`,
        payload,
      ),
  );
}

export function useUpdateOspfRedistribute(
  routerId: string,
  version: OspfVersion,
) {
  return useOspfMutation<{ source: string; payload: OspfRedistributeUpdate }>(
    routerId,
    version,
    ({ source, payload }) =>
      api.put<OspfConfig>(
        `${ospfPath(routerId, version)}/redistribute/${encodeURIComponent(source)}`,
        payload,
      ),
  );
}

export function useDeleteOspfRedistribute(
  routerId: string,
  version: OspfVersion,
) {
  return useOspfMutation<string>(routerId, version, (source) =>
    api.delete<OspfConfig>(
      `${ospfPath(routerId, version)}/redistribute/${encodeURIComponent(source)}`,
    ),
  );
}

/* -------------------------------------------------------------------------- */
/* Static-route mutations                                                     */
/* -------------------------------------------------------------------------- */

function sortStaticRoutes(items: StaticRoute[]): StaticRoute[] {
  return [...items].sort((a, b) =>
    a.family === b.family
      ? a.prefix.localeCompare(b.prefix)
      : a.family.localeCompare(b.family),
  );
}

/** Routes are identified by `family` + `prefix`; IPv4 and IPv6 are independent. */
function isSameStaticRoute(a: StaticRoute, b: StaticRoute): boolean {
  return a.family === b.family && a.prefix === b.prefix;
}

function mergeStaticRouteList(
  previous: StaticRouteList | undefined,
  route: StaticRoute,
): StaticRouteList {
  const items = previous?.items ?? [];
  const exists = items.some((item) => isSameStaticRoute(item, route));
  const next = exists
    ? items.map((item) => (isSameStaticRoute(item, route) ? route : item))
    : [...items, route];
  return { items: sortStaticRoutes(next), total: next.length };
}

/** The prefix keeps its `/`, URL-encoded so it stays a single path segment. */
function staticRoutePath(
  routerId: string,
  family: StaticRouteFamily,
  prefix: string,
): string {
  return `/routers/${routerId}/static-routes/${family}/${encodeURIComponent(prefix)}`;
}

/**
 * Create and update return the refreshed `StaticRouteRead`, so the list and the
 * route detail are patched immediately, then the list is invalidated so the
 * device ordering converges. The DELETE answers `204` and drops both caches.
 */
function useStaticRouteMutation<TVariables>(
  routerId: string,
  mutationFn: (variables: TVariables) => Promise<StaticRoute>,
) {
  const queryClient = useQueryClient();
  return useMutation<StaticRoute, Error, TVariables>({
    mutationFn,
    onSuccess: (route) => {
      queryClient.setQueryData<StaticRouteList>(
        queryKeys.staticRoutes(routerId),
        (previous) => mergeStaticRouteList(previous, route),
      );
      queryClient.setQueryData(
        queryKeys.staticRoute(routerId, route.family, route.prefix),
        route,
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.staticRoutes(routerId),
        exact: true,
      });
    },
  });
}

export function useCreateStaticRoute(routerId: string) {
  return useStaticRouteMutation<StaticRouteCreate>(routerId, (payload) =>
    api.post<StaticRoute>(`/routers/${routerId}/static-routes`, payload),
  );
}

export function useUpdateStaticRoute(routerId: string) {
  return useStaticRouteMutation<{
    family: StaticRouteFamily;
    prefix: string;
    payload: StaticRouteUpdate;
  }>(routerId, ({ family, prefix, payload }) =>
    api.put<StaticRoute>(staticRoutePath(routerId, family, prefix), payload),
  );
}

export function useDeleteStaticRoute(routerId: string) {
  const queryClient = useQueryClient();
  return useMutation<
    void,
    Error,
    { family: StaticRouteFamily; prefix: string }
  >({
    mutationFn: ({ family, prefix }) =>
      api.delete<void>(staticRoutePath(routerId, family, prefix)),
    onSuccess: (_result, { family, prefix }) => {
      queryClient.setQueryData<StaticRouteList>(
        queryKeys.staticRoutes(routerId),
        (previous) => {
          if (!previous) return previous;
          const items = previous.items.filter(
            (item) => !(item.family === family && item.prefix === prefix),
          );
          return { items, total: items.length };
        },
      );
      queryClient.removeQueries({
        queryKey: queryKeys.staticRoute(routerId, family, prefix),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.staticRoutes(routerId),
        exact: true,
      });
    },
  });
}

/* -------------------------------------------------------------------------- */
/* VPN / WireGuard mutations                                                  */
/* -------------------------------------------------------------------------- */

function wireGuardPath(routerId: string, name?: string): string {
  const base = `/routers/${routerId}/wireguard`;
  return name ? `${base}/${encodeURIComponent(name)}` : base;
}

/**
 * Interface writes, key rotation and peer create/update all return the
 * refreshed `WireGuardInterfaceDetail`, so the detail cache is replaced
 * directly. The list is invalidated (interface and peer counts) and the live
 * status is refetched because a key, address or enabled change affects it.
 */
function useWireGuardDetailMutation<TVariables>(
  routerId: string,
  mutationFn: (variables: TVariables) => Promise<WireGuardInterfaceDetail>,
) {
  const queryClient = useQueryClient();
  return useMutation<WireGuardInterfaceDetail, Error, TVariables>({
    mutationFn,
    onSuccess: (detail) => {
      queryClient.setQueryData(
        queryKeys.wireguardInterface(routerId, detail.name),
        detail,
      );
      // Merge the summary into the list immediately. Without this, selecting a
      // newly created interface would race the list refetch and the page would
      // drop `?if=` because the name is not in the stale list yet.
      queryClient.setQueryData<WireGuardList>(
        queryKeys.wireguard(routerId),
        (previous) => {
          if (!previous) return previous;
          const summary: WireGuardInterface = {
            name: detail.name,
            description: detail.description,
            addresses: detail.addresses,
            port: detail.port,
            mtu: detail.mtu,
            enabled: detail.enabled,
            public_key: detail.public_key,
            peer_count: detail.peer_count,
          };
          const exists = previous.items.some(
            (item) => item.name === summary.name,
          );
          const items = exists
            ? previous.items.map((item) =>
                item.name === summary.name ? summary : item,
              )
            : [...previous.items, summary];
          items.sort((a, b) => a.name.localeCompare(b.name));
          return { items, total: items.length };
        },
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.wireguard(routerId),
        exact: true,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.wireguardStatus(routerId, detail.name),
      });
    },
  });
}

export function useCreateWireGuardInterface(routerId: string) {
  return useWireGuardDetailMutation<WireGuardInterfaceCreate>(
    routerId,
    (payload) =>
      api.post<WireGuardInterfaceDetail>(wireGuardPath(routerId), payload),
  );
}

export function useUpdateWireGuardInterface(routerId: string) {
  return useWireGuardDetailMutation<{
    name: string;
    payload: WireGuardInterfaceUpdate;
  }>(routerId, ({ name, payload }) =>
    api.put<WireGuardInterfaceDetail>(wireGuardPath(routerId, name), payload),
  );
}

/** `PUT /wireguard/{name}/private-key` — peers need the new public key. */
export function useRotateWireGuardPrivateKey(routerId: string) {
  return useWireGuardDetailMutation<{
    name: string;
    payload: WireGuardPrivateKeyUpdate;
  }>(routerId, ({ name, payload }) =>
    api.put<WireGuardInterfaceDetail>(
      `${wireGuardPath(routerId, name)}/private-key`,
      payload,
    ),
  );
}

export function useDeleteWireGuardInterface(routerId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (name) => api.delete<void>(wireGuardPath(routerId, name)),
    onSuccess: (_result, name) => {
      // Drop the row immediately so the master-detail selection reconciles
      // against a list that no longer contains the deleted interface.
      queryClient.setQueryData<WireGuardList>(
        queryKeys.wireguard(routerId),
        (previous) => {
          if (!previous) return previous;
          const items = previous.items.filter((item) => item.name !== name);
          return { items, total: items.length };
        },
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.wireguard(routerId),
        exact: true,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.wireguardInterface(routerId, name),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.wireguardStatus(routerId, name),
      });
    },
  });
}

export function useCreateWireGuardPeer(routerId: string) {
  return useWireGuardDetailMutation<{
    iface: string;
    payload: WireGuardPeerCreate;
  }>(routerId, ({ iface, payload }) =>
    api.post<WireGuardInterfaceDetail>(
      `${wireGuardPath(routerId, iface)}/peers`,
      payload,
    ),
  );
}

export function useUpdateWireGuardPeer(routerId: string) {
  return useWireGuardDetailMutation<{
    iface: string;
    peer: string;
    payload: WireGuardPeerUpdate;
  }>(routerId, ({ iface, peer, payload }) =>
    api.put<WireGuardInterfaceDetail>(
      `${wireGuardPath(routerId, iface)}/peers/${encodeURIComponent(peer)}`,
      payload,
    ),
  );
}

/** The peer DELETE answers `204`, so the detail is invalidated instead. */
export function useDeleteWireGuardPeer(routerId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, Error, { iface: string; peer: string }>({
    mutationFn: ({ iface, peer }) =>
      api.delete<void>(
        `${wireGuardPath(routerId, iface)}/peers/${encodeURIComponent(peer)}`,
      ),
    onSuccess: (_result, { iface }) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.wireguard(routerId),
        exact: true,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.wireguardInterface(routerId, iface),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.wireguardStatus(routerId, iface),
      });
    },
  });
}

/**
 * One-time key material. These endpoints do not touch the device and return a
 * secret exactly once, so nothing is cached: the caller must write the value
 * into its form state immediately.
 */
export function useGenerateWireGuardKeypair(routerId: string) {
  return useMutation<WireGuardKeypair, Error, void>({
    mutationFn: () =>
      api.post<WireGuardKeypair>(`${wireGuardPath(routerId)}/keypair`),
  });
}

export function useGenerateWireGuardPresharedKey(routerId: string) {
  return useMutation<WireGuardPresharedKey, Error, void>({
    mutationFn: () =>
      api.post<WireGuardPresharedKey>(`${wireGuardPath(routerId)}/preshared-key`),
  });
}

/* -------------------------------------------------------------------------- */
/* Route-map mutations                                                        */
/* -------------------------------------------------------------------------- */

function sortRouteMaps(items: RouteMap[]): RouteMap[] {
  return [...items].sort((a, b) => a.name.localeCompare(b.name));
}

function mergeRouteMapList(
  previous: RouteMapList | undefined,
  routeMap: RouteMap,
): RouteMapList {
  const items = previous?.items ?? [];
  const exists = items.some((item) => item.name === routeMap.name);
  const next = exists
    ? items.map((item) => (item.name === routeMap.name ? routeMap : item))
    : [...items, routeMap];
  return { items: sortRouteMaps(next), total: next.length };
}

/**
 * Every route-map write returns the refreshed RouteMapRead (except the
 * route-map DELETE, which is 204). Patch the list cache, then invalidate so
 * `in_use` / `used_by` converge with the device, and invalidate BGP config so
 * neighbor / peer-group forms pick up renamed references.
 */
function useRouteMapMutation<TVariables>(
  routerId: string,
  mutationFn: (variables: TVariables) => Promise<RouteMap | void>,
) {
  const queryClient = useQueryClient();
  return useMutation<RouteMap | void, Error, TVariables>({
    mutationFn,
    onSuccess: (routeMap) => {
      if (routeMap) {
        queryClient.setQueryData<RouteMapList>(
          queryKeys.routeMaps(routerId),
          (previous) => mergeRouteMapList(previous, routeMap),
        );
      }
      void queryClient.invalidateQueries({
        queryKey: queryKeys.routeMaps(routerId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.bgpConfig(routerId),
      });
      // Route-map rules reference prefix lists by name; their `in_use` /
      // `used_by` lists are derived from these references.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.prefixLists(routerId),
      });
      // OSPF redistribution references route maps by name; renaming or
      // deleting one changes what the OSPF tabs can offer.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.ospf(routerId),
      });
    },
  });
}

export function useCreateRouteMap(routerId: string) {
  return useRouteMapMutation<RouteMapCreate>(routerId, (payload) =>
    api.post<RouteMap>(`/routers/${routerId}/route-maps`, payload),
  );
}

export function useUpdateRouteMap(routerId: string) {
  return useRouteMapMutation<{ name: string; payload: RouteMapUpdate }>(
    routerId,
    ({ name, payload }) =>
      api.put<RouteMap>(
        `/routers/${routerId}/route-maps/${encodeURIComponent(name)}`,
        payload,
      ),
  );
}

export function useDeleteRouteMap(routerId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (name) =>
      api.delete<void>(
        `/routers/${routerId}/route-maps/${encodeURIComponent(name)}`,
      ),
    onSuccess: (_result, name) => {
      queryClient.setQueryData<RouteMapList>(
        queryKeys.routeMaps(routerId),
        (previous) => {
          if (!previous) return previous;
          const items = previous.items.filter((item) => item.name !== name);
          return { items, total: items.length };
        },
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.routeMaps(routerId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.bgpConfig(routerId),
      });
      // Route-map rules reference prefix lists by name; their `in_use` /
      // `used_by` lists are derived from these references.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.prefixLists(routerId),
      });
      // OSPF redistribution references route maps by name.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.ospf(routerId),
      });
    },
  });
}

export function useCreateRouteMapRule(routerId: string) {
  return useRouteMapMutation<{ name: string; payload: RouteMapRuleCreate }>(
    routerId,
    ({ name, payload }) =>
      api.post<RouteMap>(
        `/routers/${routerId}/route-maps/${encodeURIComponent(name)}/rules`,
        payload,
      ),
  );
}

export function useUpdateRouteMapRule(routerId: string) {
  return useRouteMapMutation<{
    name: string;
    number: number;
    payload: RouteMapRuleUpdate;
  }>(routerId, ({ name, number, payload }) =>
    api.put<RouteMap>(
      `/routers/${routerId}/route-maps/${encodeURIComponent(name)}/rules/${number}`,
      payload,
    ),
  );
}

export function useDeleteRouteMapRule(routerId: string) {
  return useRouteMapMutation<{ name: string; number: number }>(
    routerId,
    ({ name, number }) =>
      api.delete<RouteMap>(
        `/routers/${routerId}/route-maps/${encodeURIComponent(name)}/rules/${number}`,
      ),
  );
}

/* -------------------------------------------------------------------------- */
/* Prefix-list mutations                                                      */
/* -------------------------------------------------------------------------- */

function sortPrefixLists(items: PrefixList[]): PrefixList[] {
  return [...items].sort((a, b) =>
    a.family === b.family
      ? a.name.localeCompare(b.name)
      : a.family.localeCompare(b.family),
  );
}

/** Lists are identified by `family` + `name`; the same name may exist twice. */
function isSamePrefixList(a: PrefixList, b: PrefixList): boolean {
  return a.family === b.family && a.name === b.name;
}

function mergePrefixListList(
  previous: PrefixListList | undefined,
  prefixList: PrefixList,
): PrefixListList {
  const items = previous?.items ?? [];
  const exists = items.some((item) => isSamePrefixList(item, prefixList));
  const next = exists
    ? items.map((item) =>
        isSamePrefixList(item, prefixList) ? prefixList : item,
      )
    : [...items, prefixList];
  return { items: sortPrefixLists(next), total: next.length };
}

function prefixListPath(
  routerId: string,
  family: PrefixListFamily,
  name: string,
): string {
  return `/routers/${routerId}/prefix-lists/${family}/${encodeURIComponent(name)}`;
}

/**
 * Every prefix-list write returns the refreshed `PrefixListRead` (except the
 * prefix-list DELETE, which is 204). Patch the list cache, then invalidate so
 * `in_use` / `used_by` converge with the device. Route maps and BGP config are
 * invalidated as well: both reference prefix lists by name.
 */
function usePrefixListMutation<TVariables>(
  routerId: string,
  mutationFn: (variables: TVariables) => Promise<PrefixList>,
) {
  const queryClient = useQueryClient();
  return useMutation<PrefixList, Error, TVariables>({
    mutationFn,
    onSuccess: (prefixList) => {
      queryClient.setQueryData<PrefixListList>(
        queryKeys.prefixLists(routerId),
        (previous) => mergePrefixListList(previous, prefixList),
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.prefixLists(routerId),
      });
    },
  });
}

export function useCreatePrefixList(routerId: string) {
  return usePrefixListMutation<PrefixListCreate>(routerId, (payload) =>
    api.post<PrefixList>(`/routers/${routerId}/prefix-lists`, payload),
  );
}

export function useUpdatePrefixList(routerId: string) {
  return usePrefixListMutation<{
    family: PrefixListFamily;
    name: string;
    payload: PrefixListUpdate;
  }>(routerId, ({ family, name, payload }) =>
    api.put<PrefixList>(prefixListPath(routerId, family, name), payload),
  );
}

export function useDeletePrefixList(routerId: string) {
  const queryClient = useQueryClient();
  return useMutation<
    void,
    Error,
    { family: PrefixListFamily; name: string }
  >({
    mutationFn: ({ family, name }) =>
      api.delete<void>(prefixListPath(routerId, family, name)),
    onSuccess: (_result, { family, name }) => {
      queryClient.setQueryData<PrefixListList>(
        queryKeys.prefixLists(routerId),
        (previous) => {
          if (!previous) return previous;
          const items = previous.items.filter(
            (item) => !(item.family === family && item.name === name),
          );
          return { items, total: items.length };
        },
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.prefixLists(routerId),
      });
    },
  });
}

export function useCreatePrefixListRule(routerId: string) {
  return usePrefixListMutation<{
    family: PrefixListFamily;
    name: string;
    payload: PrefixListRuleCreate;
  }>(routerId, ({ family, name, payload }) =>
    api.post<PrefixList>(
      `${prefixListPath(routerId, family, name)}/rules`,
      payload,
    ),
  );
}

export function useUpdatePrefixListRule(routerId: string) {
  return usePrefixListMutation<{
    family: PrefixListFamily;
    name: string;
    number: number;
    payload: PrefixListRuleUpdate;
  }>(routerId, ({ family, name, number, payload }) =>
    api.put<PrefixList>(
      `${prefixListPath(routerId, family, name)}/rules/${number}`,
      payload,
    ),
  );
}

export function useDeletePrefixListRule(routerId: string) {
  return usePrefixListMutation<{
    family: PrefixListFamily;
    name: string;
    number: number;
  }>(routerId, ({ family, name, number }) =>
    api.delete<PrefixList>(
      `${prefixListPath(routerId, family, name)}/rules/${number}`,
    ),
  );
}

/* -------------------------------------------------------------------------- */
/* User + account mutations                                                   */
/* -------------------------------------------------------------------------- */

export function useCreateUser() {
  const queryClient = useQueryClient();
  return useMutation<User, Error, UserCreate>({
    mutationFn: (payload) => api.post<User>("/users", payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users });
    },
  });
}

export function useUpdateUser() {
  const queryClient = useQueryClient();
  return useMutation<User, Error, { userId: string; payload: UserUpdate }>({
    mutationFn: ({ userId, payload }) =>
      api.patch<User>(`/users/${userId}`, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users });
    },
  });
}

export function useDeleteUser() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (userId) => api.delete<void>(`/users/${userId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users });
    },
  });
}

export function useChangePassword() {
  return useMutation<void, Error, ChangePasswordRequest>({
    mutationFn: (payload) =>
      api.post<void>("/auth/change-password", payload),
  });
}

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

export function bgpConfigFetcher(routerId: string) {
  return (signal?: AbortSignal) =>
    api.get<BgpConfig>(`/routers/${routerId}/bgp`, signal);
}

export function statusFetcher(routerId: string) {
  return (signal?: AbortSignal) =>
    api.get<BgpStatus>(`/routers/${routerId}/bgp/status`, signal);
}
