"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type {
  OspfAreaType,
  OspfLogAdjacencyChanges,
  OspfNetworkType,
  OspfVersion,
} from "@/lib/types";

/** The API path segment doubles as the OSPF version key. */
export const OSPF_VERSIONS: OspfVersion[] = ["v2", "v3"];

export const VERSION_LABEL: Record<OspfVersion, string> = {
  v2: "OSPFv2 (IPv4)",
  v3: "OSPFv3 (IPv6)",
};

export const VERSION_SHORT: Record<OspfVersion, string> = {
  v2: "OSPFv2",
  v3: "OSPFv3",
};

export const VERSION_FAMILY: Record<OspfVersion, string> = {
  v2: "IPv4",
  v3: "IPv6",
};

export const VERSION_VYOS_PATH: Record<OspfVersion, string> = {
  v2: "protocols ospf",
  v3: "protocols ospfv3",
};

export const VERSION_NEIGHBOR_COMMAND: Record<OspfVersion, string> = {
  v2: "show ip ospf neighbor",
  v3: "show ipv6 ospfv3 neighbor",
};

/**
 * Fallbacks when a payload predates the supported-* lists. The API remains the
 * source of truth; these only keep the selects usable in a degraded response.
 */
export const NETWORK_TYPES: Record<OspfVersion, OspfNetworkType[]> = {
  v2: [
    "broadcast",
    "non-broadcast",
    "point-to-multipoint",
    "point-to-point",
  ],
  v3: ["broadcast", "point-to-point"],
};

export const REDISTRIBUTE_SOURCES: Record<OspfVersion, string[]> = {
  v2: ["babel", "bgp", "connected", "isis", "kernel", "rip", "static"],
  v3: ["babel", "bgp", "connected", "isis", "kernel", "ripng", "static"],
};

export const NETWORK_TYPE_LABEL: Record<OspfNetworkType, string> = {
  broadcast: "Broadcast",
  "non-broadcast": "Non-broadcast",
  "point-to-multipoint": "Point-to-multipoint",
  "point-to-point": "Point-to-point",
};

export const AREA_TYPE_LABEL: Record<OspfAreaType, string> = {
  normal: "Normal",
  stub: "Stub",
  nssa: "NSSA",
};

export const LOG_ADJACENCY_LABEL: Record<OspfLogAdjacencyChanges, string> = {
  none: "Off",
  normal: "Normal",
  detail: "Detail",
};

const SOURCE_LABEL: Record<string, string> = {
  babel: "Babel",
  bgp: "BGP",
  connected: "Connected",
  isis: "IS-IS",
  kernel: "Kernel",
  rip: "RIP",
  ripng: "RIPng",
  static: "Static",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABEL[source] ?? source;
}

/** Metric type is `null` when the device default (type 2) applies. */
export function metricTypeLabel(metricType: number | null): string {
  if (metricType === 1) return "Type 1";
  if (metricType === 2) return "Type 2";
  return "Default";
}

/* -------------------------------------------------------------------------- */
/* Area ID parsing                                                            */
/* -------------------------------------------------------------------------- */

const DECIMAL_AREA_ID = /^\d{1,10}$/;
const DOTTED_OCTET = /^\d{1,3}$/;
export const MAX_AREA_ID = 4_294_967_295;

/**
 * Accepts a decimal area number (`0`, `1`, `4294967295`) or dotted notation
 * (`0.0.0.0`, `0.0.0.1`) and returns the unsigned 32-bit value. Returns `null`
 * for anything else.
 */
export function parseAreaId(input: string): number | null {
  const value = input.trim();
  if (!value) return null;

  if (value.includes(".")) {
    const parts = value.split(".");
    if (parts.length !== 4) return null;
    const octets: number[] = [];
    for (const part of parts) {
      if (!DOTTED_OCTET.test(part)) return null;
      const octet = Number(part);
      if (octet > 255) return null;
      octets.push(octet);
    }
    return (
      ((octets[0] * 256 + octets[1]) * 256 + octets[2]) * 256 + octets[3]
    );
  }

  if (!DECIMAL_AREA_ID.test(value)) return null;
  const numeric = Number(value);
  if (!Number.isInteger(numeric) || numeric < 0 || numeric > MAX_AREA_ID) {
    return null;
  }
  return numeric;
}

export function areaIdToDotted(value: number): string {
  return [
    (value >>> 24) & 0xff,
    (value >>> 16) & 0xff,
    (value >>> 8) & 0xff,
    value & 0xff,
  ].join(".");
}

/** Canonical dotted form of a user-typed area ID (`null` when invalid). */
export function normalizeAreaId(input: string): string | null {
  const parsed = parseAreaId(input);
  return parsed === null ? null : areaIdToDotted(parsed);
}

/* -------------------------------------------------------------------------- */
/* Form helpers                                                               */
/* -------------------------------------------------------------------------- */

/** VyOS interface names accepted by the OSPF interface endpoints. */
export const INTERFACE_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9._-]{0,63}$/;
/** Route-map references reuse the route-map name shape. */
export const ROUTE_MAP_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const UNSIGNED_INTEGER = /^\d+$/;

/** Empty input means "device default" (`null`), not zero. */
export function isOptionalIntegerInRange(
  value: string,
  min: number,
  max: number,
): boolean {
  const trimmed = value.trim();
  if (!trimmed) return true;
  if (!UNSIGNED_INTEGER.test(trimmed)) return false;
  const numeric = Number(trimmed);
  return Number.isInteger(numeric) && numeric >= min && numeric <= max;
}

export function optionalInteger(value: string): number | null {
  const trimmed = value.trim();
  return trimmed ? Number(trimmed) : null;
}

/* -------------------------------------------------------------------------- */
/* Badges                                                                     */
/* -------------------------------------------------------------------------- */

const OSPF_DOWN_STATES = new Set(["down", "attempt"]);

export function OspfNeighborStateBadge({
  state,
  established,
}: {
  state: string;
  established: boolean;
}) {
  const normalized = state.toLowerCase();
  const tone = established
    ? "success"
    : OSPF_DOWN_STATES.has(normalized)
      ? "destructive"
      : "warning";
  const dot = established
    ? "bg-emerald-500"
    : OSPF_DOWN_STATES.has(normalized)
      ? "bg-destructive"
      : "bg-amber-500";

  return (
    <Badge variant={tone} className="gap-1.5 font-mono">
      <span className={cn("size-1.5 rounded-full", dot)} />
      {state || "Unknown"}
    </Badge>
  );
}

export function AreaTypeBadge({
  areaType,
  noSummary,
}: {
  areaType: OspfAreaType;
  noSummary: boolean;
}) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Badge
        variant={areaType === "normal" ? "muted" : "outline"}
        className="font-mono text-[9px]"
      >
        {AREA_TYPE_LABEL[areaType]}
      </Badge>
      {noSummary && (
        <Badge variant="secondary" className="font-mono text-[9px]">
          no-summary
        </Badge>
      )}
    </span>
  );
}

/** Small flag chips used by the interface table. */
export function InterfaceFlags({
  passive,
  bfd,
  mtuIgnore,
}: {
  passive: boolean;
  bfd: boolean;
  mtuIgnore: boolean;
}) {
  const flags = [
    passive ? "passive" : null,
    bfd ? "BFD" : null,
    mtuIgnore ? "MTU-ignore" : null,
  ].filter((flag): flag is string => flag !== null);

  if (flags.length === 0) {
    return (
      <span className="text-[11px] text-muted-foreground/70">—</span>
    );
  }

  return (
    <span className="inline-flex flex-wrap gap-1">
      {flags.map((flag) => (
        <Badge
          key={flag}
          variant="outline"
          className="border-border/80 bg-muted/40 font-mono text-[9px]"
        >
          {flag}
        </Badge>
      ))}
    </span>
  );
}

/** `1`, `2` or "—" for the redistribution table. */
export function MetricTypeCell({ metricType }: { metricType: number | null }) {
  if (metricType === null) {
    return <span className="text-[11px] text-muted-foreground">Default</span>;
  }
  return (
    <Badge variant="outline" className="font-mono text-[9px]">
      Type {metricType}
    </Badge>
  );
}
