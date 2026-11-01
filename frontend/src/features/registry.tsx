import {
  ArrowLeftRight,
  Cable,
  Filter,
  Globe2,
  LayoutDashboard,
  ListFilter,
  Map,
  Network,
  RadioTower,
  Route,
  ScrollText,
  Server,
  Shield,
  Settings,
  SlidersHorizontal,
  Tags,
  UsersRound,
  Waypoints,
  type LucideIcon,
} from "lucide-react";

import type { Role } from "@/lib/types";

export interface FeatureNavItem {
  title: string;
  href: string;
  description?: string;
  icon?: LucideIcon;
}

export interface FeatureQuickAction {
  title: string;
  href: string;
  icon: LucideIcon;
}

export interface FeatureModule {
  key: string;
  title: string;
  description: string;
  href: string;
  icon: LucideIcon;
  nav: FeatureNavItem[];
  quickActions: FeatureQuickAction[];
  /** Roles allowed to open the module. Omit for "everyone". */
  roles?: Role[];
  status: "available" | "coming-soon";
}

/**
 * ─────────────────────────────────────────────────────────────────────────────
 * FEATURE REGISTRY — the one extension point for VyOS feature modules.
 *
 * To add a new module (e.g. firewall, interfaces, NAT):
 *   1. Create the static routes under `src/app/<module>/` (folder routes only,
 *      no dynamic path segments — this app is a static export).
 *   2. Append one FeatureModule entry below with its nav + quick actions.
 *   3. Add any API hooks/query keys in `src/lib/queries.ts`.
 * The sidebar, dashboard module cards and the module subnav all read from this
 * list, so no other navigation changes are needed. Keep `roles` if a module is
 * restricted; the backend still enforces authorization.
 * ─────────────────────────────────────────────────────────────────────────────
 */
export const FEATURE_MODULES: FeatureModule[] = [
  {
    key: "bgp",
    title: "BGP",
    description:
      "Border Gateway Protocol configuration, neighbors and session health",
    href: "/bgp/",
    icon: Network,
    status: "available",
    nav: [
      {
        title: "Overview",
        href: "/bgp/",
        description: "Session health and global state",
        icon: LayoutDashboard,
      },
      {
        title: "Neighbors",
        href: "/bgp/neighbors/",
        description: "Peers, timers and address families",
        icon: RadioTower,
      },
      {
        title: "Networks",
        href: "/bgp/networks/",
        description: "Advertised prefixes",
        icon: Globe2,
      },
      {
        title: "Peer groups",
        href: "/bgp/peer-groups/",
        description: "Reusable session templates",
        icon: Tags,
      },
      {
        title: "Global settings",
        href: "/bgp/settings/",
        description: "AS number, router ID and teardown",
        icon: SlidersHorizontal,
      },
    ],
    quickActions: [
      {
        title: "Add neighbor",
        href: "/bgp/neighbors/",
        icon: RadioTower,
      },
      {
        title: "Advertise prefix",
        href: "/bgp/networks/",
        icon: Globe2,
      },
      {
        title: "Create peer group",
        href: "/bgp/peer-groups/",
        icon: Tags,
      },
    ],
  },
  {
    key: "route-maps",
    title: "Route maps",
    description:
      "Policy route-map rules used for BGP import/export filtering and attribute changes",
    href: "/route-maps/",
    icon: Route,
    status: "available",
    nav: [
      {
        title: "All route maps",
        href: "/route-maps/",
        description: "Rules, match conditions and set actions",
        icon: Route,
      },
    ],
    quickActions: [
      {
        title: "Route-map rules",
        href: "/route-maps/",
        icon: Route,
      },
      {
        title: "Apply to a neighbor",
        href: "/bgp/neighbors/",
        icon: Network,
      },
    ],
  },
  {
    key: "prefix-lists",
    title: "Prefix lists",
    description:
      "IPv4 and IPv6 prefix-list policy objects used by route-map and BGP filters",
    href: "/prefix-lists/",
    icon: ListFilter,
    status: "available",
    nav: [
      {
        title: "All prefix lists",
        href: "/prefix-lists/",
        description: "Ordered permit/deny prefix rules by address family",
        icon: Filter,
      },
    ],
    quickActions: [
      {
        title: "Prefix-list rules",
        href: "/prefix-lists/",
        icon: Filter,
      },
      {
        title: "Reference from a route map",
        href: "/route-maps/",
        icon: Route,
      },
    ],
  },
  {
    key: "ospf",
    title: "OSPF",
    description: "OSPFv2 (IPv4) and OSPFv3 (IPv6) routing",
    href: "/ospf/",
    icon: Waypoints,
    status: "available",
    nav: [
      {
        title: "OSPF overview",
        href: "/ospf/",
        description: "Neighbor health, areas and interface activation",
        icon: Waypoints,
      },
    ],
    quickActions: [
      {
        title: "OSPF interfaces",
        href: "/ospf/?tab=interfaces",
        icon: Cable,
      },
      {
        title: "OSPF areas",
        href: "/ospf/?tab=areas",
        icon: Map,
      },
      {
        title: "OSPF redistribution",
        href: "/ospf/?tab=redistribution",
        icon: ArrowLeftRight,
      },
    ],
  },
  {
    key: "static-routes",
    title: "Static routes",
    description:
      "IPv4/IPv6 static routes with next hops, blackhole and reject",
    href: "/static-routes/",
    icon: Route,
    status: "available",
    nav: [
      {
        title: "All static routes",
        href: "/static-routes/",
        description: "Gateway, blackhole and reject routes by address family",
        icon: Route,
      },
    ],
    quickActions: [
      {
        title: "IPv4 static routes",
        href: "/static-routes/?family=ipv4",
        icon: Network,
      },
      {
        title: "IPv6 static routes",
        href: "/static-routes/?family=ipv6",
        icon: Globe2,
      },
    ],
  },
  {
    key: "vpn",
    title: "VPN",
    description: "WireGuard tunnels and peers",
    href: "/vpn/",
    icon: Shield,
    status: "available",
    nav: [
      {
        title: "WireGuard",
        href: "/vpn/",
        description: "Interfaces, keys and live peer handshakes",
        icon: Shield,
      },
    ],
    quickActions: [
      {
        title: "WireGuard tunnels",
        href: "/vpn/",
        icon: Shield,
      },
    ],
  },
];

export interface PlatformNavItem {
  title: string;
  href: string;
  icon: LucideIcon;
  roles?: Role[];
}

export const PLATFORM_NAV: PlatformNavItem[] = [
  { title: "Dashboard", href: "/", icon: LayoutDashboard },
  { title: "Routers", href: "/routers/", icon: Server },
  { title: "Users", href: "/settings/users/", icon: UsersRound, roles: ["admin"] },
  { title: "Audit log", href: "/audit/", icon: ScrollText, roles: ["admin"] },
  { title: "Settings", href: "/settings/", icon: Settings },
];

export function modulesForRole(role: Role | undefined | null): FeatureModule[] {
  return FEATURE_MODULES.filter(
    (module) => !module.roles || (role ? module.roles.includes(role) : false),
  );
}

/** Longest matching module for the current pathname (trailing slash safe). */
export function moduleForPath(pathname: string): FeatureModule | undefined {
  const normalized = pathname.endsWith("/") ? pathname : `${pathname}/`;
  return [...FEATURE_MODULES]
    .sort((a, b) => b.href.length - a.href.length)
    .find((module) => normalized.startsWith(module.href));
}

export function navItemForPath(
  module: FeatureModule | undefined,
  pathname: string,
): FeatureNavItem | undefined {
  if (!module) return undefined;
  const normalized = pathname.endsWith("/") ? pathname : `${pathname}/`;
  return [...module.nav]
    .sort((a, b) => b.href.length - a.href.length)
    .find((item) => normalized.startsWith(item.href));
}

/**
 * Nav items are exact static routes. Prefix matching would light up both the
 * module root ("/bgp/") and a child ("/bgp/neighbors/") at the same time, so
 * compare normalized paths exactly.
 */
export function isNavActive(href: string, pathname: string): boolean {
  if (href === "/") return pathname === "/";
  const normalized = pathname.endsWith("/") ? pathname : `${pathname}/`;
  return normalized === href;
}

/** Extra breadcrumb labels for routes that aren't module nav items. */
export const ROUTE_LABELS: Record<string, string> = {
  routers: "Routers",
  bgp: "BGP",
  neighbors: "Neighbors",
  networks: "Networks",
  "peer-groups": "Peer groups",
  "route-maps": "Route maps",
  "prefix-lists": "Prefix lists",
  ospf: "OSPF",
  "static-routes": "Static routes",
  vpn: "VPN",
  settings: "Settings",
  users: "Users",
  audit: "Audit log",
};

