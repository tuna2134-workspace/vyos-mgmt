"use client";

import * as React from "react";

import type {
  StaticNextHop,
  StaticRoute,
  StaticRouteFamily,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { isIPv4, isIPv6 } from "@/lib/validation";
import { Badge } from "@/components/ui/badge";

export const STATIC_FAMILY_LABEL: Record<StaticRouteFamily, string> = {
  ipv4: "IPv4",
  ipv6: "IPv6",
};

/** `protocols static route` (4) or `protocols static route6` (6). */
export const STATIC_FAMILY_VYOS_PATH: Record<StaticRouteFamily, string> = {
  ipv4: "protocols static route",
  ipv6: "protocols static route6",
};

export const STATIC_FAMILY_PLACEHOLDER: Record<
  StaticRouteFamily,
  { prefix: string; next_hop: string }
> = {
  ipv4: { prefix: "10.0.0.0/8", next_hop: "192.0.2.1" },
  ipv6: { prefix: "2001:db8::/32", next_hop: "2001:db8::1" },
};

/** VyOS interface names used for next hops (`eth0`, `wg0`, `br0.10`, …). */
export const INTERFACE_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9._-]{0,63}$/;

export function staticFamilyBadgeClass(family: StaticRouteFamily): string {
  return family === "ipv4"
    ? "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300"
    : "border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-300";
}

export function StaticFamilyBadge({
  family,
  className,
}: {
  family: StaticRouteFamily;
  className?: string;
}) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "font-mono text-[9px] uppercase",
        staticFamilyBadgeClass(family),
        className,
      )}
    >
      {STATIC_FAMILY_LABEL[family]}
    </Badge>
  );
}

export type StaticRouteType = "gateway" | "blackhole" | "reject";

export const ROUTE_TYPE_LABEL: Record<StaticRouteType, string> = {
  gateway: "Gateway",
  blackhole: "Blackhole",
  reject: "Reject",
};

export const ROUTE_TYPE_DESCRIPTION: Record<StaticRouteType, string> = {
  gateway: "Forward matching traffic to one or more next hops",
  blackhole: "Silently discard matching traffic",
  reject: "Discard matching traffic and answer with ICMP unreachable",
};

export function staticRouteType(
  route: Pick<StaticRoute, "blackhole" | "reject">,
): StaticRouteType {
  if (route.blackhole) return "blackhole";
  if (route.reject) return "reject";
  return "gateway";
}

export function RouteTypeBadge({
  type,
  className,
}: {
  type: StaticRouteType;
  className?: string;
}) {
  const variant =
    type === "blackhole"
      ? "warning"
      : type === "reject"
        ? "destructive"
        : "outline";
  return (
    <Badge
      variant={variant}
      className={cn(
        "font-mono text-[9px] uppercase",
        type === "gateway" && "text-foreground",
        className,
      )}
    >
      {ROUTE_TYPE_LABEL[type]}
    </Badge>
  );
}

export function sortStaticRoutes(items: StaticRoute[]): StaticRoute[] {
  return [...items].sort((a, b) =>
    a.family === b.family
      ? a.prefix.localeCompare(b.prefix)
      : a.family.localeCompare(b.family),
  );
}

export interface StaticRouteCounts {
  total: number;
  unicast: number;
  blackhole: number;
  reject: number;
}

export function staticRouteCounts(routes: StaticRoute[]): StaticRouteCounts {
  return {
    total: routes.length,
    unicast: routes.filter((route) => !route.blackhole && !route.reject).length,
    blackhole: routes.filter((route) => route.blackhole).length,
    reject: routes.filter((route) => route.reject).length,
  };
}

/** Next-hop addresses are host addresses (no prefix length) per family. */
export function nextHopMatchesFamily(
  address: string,
  family: StaticRouteFamily,
): boolean {
  return family === "ipv4" ? isIPv4(address) : isIPv6(address);
}

/**
 * Human label for one next hop: `192.0.2.1`, `dev eth0`, or `192.0.2.1 via
 * eth0` when both are configured (VyOS `next-hop <address> interface <if>`).
 */
export function nextHopLabel(hop: StaticNextHop): string {
  if (hop.address && hop.interface) {
    return `${hop.address} via ${hop.interface}`;
  }
  if (hop.address) return hop.address;
  if (hop.interface) return `dev ${hop.interface}`;
  return "—";
}

/** Stable key for duplicate detection, mirroring the API's pair rule. */
export function nextHopPairKey(hop: {
  address: string | null;
  interface: string | null;
}): string {
  return `${(hop.address ?? "").trim().toLowerCase()}|${(
    hop.interface ?? ""
  ).trim()}`;
}

export function NextHopList({ hops }: { hops: StaticNextHop[] }) {
  if (hops.length === 0) {
    return <span className="text-[11px] text-muted-foreground">—</span>;
  }
  return (
    <ul className="space-y-1">
      {hops.map((hop, index) => (
        <li
          key={`${hop.address ?? ""}:${hop.interface ?? ""}:${index}`}
          className="flex flex-wrap items-center gap-1.5"
        >
          <span
            className={cn(
              "font-mono text-[11px] break-all",
              hop.enabled ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {nextHopLabel(hop)}
          </span>
          {hop.distance !== null && (
            <Badge variant="outline" className="font-mono text-[9px]">
              distance {hop.distance}
            </Badge>
          )}
          {!hop.enabled && (
            <Badge variant="muted" className="text-[9px]">
              disabled
            </Badge>
          )}
        </li>
      ))}
    </ul>
  );
}

/** `distance 10 · tag 100` for blackhole/reject routes, `—` for unicast. */
export function distanceTagLabel(route: StaticRoute): string {
  if (!route.blackhole && !route.reject) return "—";
  const parts: string[] = [];
  if (route.distance !== null) parts.push(`distance ${route.distance}`);
  if (route.tag !== null) parts.push(`tag ${route.tag}`);
  return parts.length > 0 ? parts.join(" · ") : "defaults";
}
