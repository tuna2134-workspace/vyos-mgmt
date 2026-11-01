"use client";

import * as React from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowUpRight,
  Clock,
  Globe2,
  Hash,
  Layers,
  RadioTower,
  RefreshCw,
  SlidersHorizontal,
  Tags,
  Users,
  Waypoints,
} from "lucide-react";

import { useAuth } from "@/lib/auth";
import { useRouterSelection } from "@/lib/router-context";
import { useBgpConfig, useBgpStatus, queryKeys } from "@/lib/queries";
import { canWrite } from "@/lib/roles";
import {
  formatNumber,
  formatRelative,
  formatDateTime,
} from "@/lib/format";
import { cn } from "@/lib/utils";
import type { BgpNeighbor, BgpPeerStatus } from "@/lib/types";
import {
  AddressFamilyBadges,
  BgpPageHeading,
  BgpRouterBoundary,
  NoBgpConfigured,
  RouteMapPolicy,
} from "@/components/bgp/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Stat, StatStrip } from "@/components/ui/stat";
import {
  EmptyState,
  ErrorPanel,
  InlineAlert,
  PeerStateBadge,
  Spinner,
  StatusDot,
  TableSkeleton,
} from "@/components/states";

function statusCounts(peers: BgpPeerStatus[]) {
  const established = peers.filter((p) => p.established).length;
  const idle = peers.filter((p) => p.state.toLowerCase() === "idle").length;
  const negotiating = peers.filter((p) =>
    ["active", "connect", "opensent", "openconfirm"].includes(
      p.state.toLowerCase(),
    ),
  ).length;
  return {
    established,
    idle,
    negotiating,
    other: peers.length - established - idle - negotiating,
  };
}

function PeerRow({
  peer,
  neighbor,
}: {
  peer?: BgpPeerStatus;
  neighbor: BgpNeighbor;
}) {
  const state = peer?.state ?? "Unknown";
  return (
    <tr className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/25">
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "flex size-7 shrink-0 items-center justify-center rounded-md border",
              peer?.established
                ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300"
                : "border-border bg-muted/40 text-muted-foreground",
            )}
          >
            <RadioTower className="size-3.5" />
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-[12px] font-medium">
                {neighbor.address}
              </span>
              {neighbor.shutdown && (
                <Badge variant="destructive" className="text-[9px]">
                  shutdown
                </Badge>
              )}
              {neighbor.passive && (
                <Badge variant="muted" className="text-[9px]">
                  passive
                </Badge>
              )}
            </div>
            <p className="truncate text-[10px] text-muted-foreground">
              {neighbor.description || neighbor.peer_group || "No description"}
            </p>
          </div>
        </div>
      </td>
      <td className="px-4 py-3">
        <PeerStateBadge state={state} />
      </td>
      <td className="px-4 py-3">
        <p className="font-mono text-[11px]">
          {neighbor.remote_as ?? "inherited"}
        </p>
        {neighbor.local_as != null && (
          <p className="text-[9px] text-muted-foreground">
            local {neighbor.local_as}
          </p>
        )}
      </td>
      <td className="px-4 py-3 font-mono text-[11px]">
        {peer?.uptime || "—"}
      </td>
      <td className="px-4 py-3">
        <span className="font-mono text-[11px]">
          <span className="text-emerald-600 dark:text-emerald-300">
            {formatNumber(peer?.prefixes_received)}
          </span>
          <span className="mx-1 text-muted-foreground">/</span>
          {formatNumber(peer?.prefixes_sent)}
        </span>
        <p className="text-[9px] text-muted-foreground">received / sent</p>
      </td>
      <td className="px-4 py-3 font-mono text-[10px] text-muted-foreground">
        {peer ? `${formatNumber(peer.msg_received)} / ${formatNumber(peer.msg_sent)}` : "—"}
      </td>
      <td className="px-4 py-3">
        <AddressFamilyBadges families={neighbor.address_families} />
        <RouteMapPolicy families={neighbor.address_families} />
      </td>
    </tr>
  );
}

function Overview({ router }: { router: { id: string; name: string } }) {
  const { user } = useAuth();
  const writer = canWrite(user?.role);
  const queryClient = useQueryClient();
  const configQuery = useBgpConfig(router.id);
  const statusQuery = useBgpStatus(router.id);
  const [refreshing, setRefreshing] = React.useState(false);

  const refresh = async () => {
    setRefreshing(true);
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.bgpConfig(router.id),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.bgpStatus(router.id),
      }),
    ]);
    setRefreshing(false);
  };

  if (configQuery.isLoading) return <TableSkeleton rows={5} />;

  if (configQuery.isError && !configQuery.data) {
    return (
      <ErrorPanel
        title={`Could not read BGP from ${router.name}`}
        error={configQuery.error}
        onRetry={() => void configQuery.refetch()}
      />
    );
  }

  const config = configQuery.data;
  if (!config) return <TableSkeleton rows={5} />;

  if (!config.configured) {
    return (
      <NoBgpConfigured
        router={router}
        title={`BGP is not configured on ${router.name}`}
      />
    );
  }

  const status = statusQuery.data;
  const peers = status?.peers ?? [];
  const statusByAddress = new Map(peers.map((peer) => [peer.address, peer]));
  const neighbors = config.neighbors;
  const counts = statusCounts(peers);
  const totalReceived = peers.reduce(
    (sum, peer) => sum + (peer.prefixes_received ?? 0),
    0,
  );
  const totalSent = peers.reduce(
    (sum, peer) => sum + (peer.prefixes_sent ?? 0),
    0,
  );
  const established = status?.established_peers ?? counts.established;
  const totalPeers = status?.total_peers ?? peers.length;
  const percent =
    totalPeers > 0 ? Math.round((established / totalPeers) * 100) : 0;

  const quickActions = [
    {
      title: "Add neighbor",
      href: "/bgp/neighbors/",
      icon: RadioTower,
      write: true,
    },
    {
      title: "Advertise prefix",
      href: "/bgp/networks/",
      icon: Globe2,
      write: true,
    },
    {
      title: "Peer group",
      href: "/bgp/peer-groups/",
      icon: Tags,
      write: true,
    },
    {
      title: "Global settings",
      href: "/bgp/settings/",
      icon: SlidersHorizontal,
      write: false,
    },
  ];

  return (
    <div className="space-y-5">
      {configQuery.isError && (
        <InlineAlert tone="warning" title="Showing cached configuration">
          The latest refresh failed:{" "}
          {configQuery.error instanceof Error
            ? configQuery.error.message
            : "unknown error"}
        </InlineAlert>
      )}
      {status?.error && (
        <InlineAlert tone="warning" title="BGP collector reported an issue">
          {status.error}
        </InlineAlert>
      )}

      <StatStrip>
        <Stat
          label="Local AS"
          value={config.global.system_as ?? status?.local_as ?? "—"}
          hint={
            <span className="flex items-center gap-1.5">
              <StatusDot tone="primary" /> Autonomous system
            </span>
          }
          icon={Hash}
        />
        <Stat
          label="Router ID"
          value={config.global.router_id ?? status?.router_id ?? "—"}
          hint="BGP identifier"
          icon={Waypoints}
        />
        <Stat
          label="Sessions established"
          value={
            <span>
              {established}
              <span className="text-base font-normal text-muted-foreground">
                /{totalPeers}
              </span>
            </span>
          }
          hint={
            statusQuery.isLoading ? (
              "Collecting session status…"
            ) : statusQuery.isError ? (
              "Status unavailable"
            ) : (
              `${formatNumber(peers.length)} peers reported`
            )
          }
          icon={RadioTower}
        />
        <Stat
          label="Advertised networks"
          value={formatNumber(config.networks.length)}
          hint={`${config.peer_groups.length} peer groups configured`}
          icon={Globe2}
        />
      </StatStrip>

      <div className="grid gap-4 lg:grid-cols-[1.35fr_1fr]">
        <Card className="gap-4">
          <CardHeader className="flex-row items-start justify-between gap-2 border-b border-border/60 px-5 pb-3">
            <div>
              <CardTitle className="text-sm">Session health</CardTitle>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                Collected from the device every 15 seconds
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge
                variant={statusQuery.isError ? "warning" : "outline"}
                className="gap-1.5 font-mono text-[9px]"
              >
                {statusQuery.isFetching ? (
                  <Spinner className="size-2.5" />
                ) : (
                  <StatusDot
                    tone={statusQuery.isError ? "warning" : "success"}
                    pulse={!statusQuery.isError}
                  />
                )}
                {statusQuery.isError ? "collector error" : "live"}
              </Badge>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => void refresh()}
                disabled={refreshing}
                aria-label="Refresh BGP status"
              >
                <RefreshCw className={cn("size-3.5", refreshing && "animate-spin")} />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4 px-5">
            {statusQuery.isError ? (
              <InlineAlert tone="warning" title="BGP status unavailable">
                {statusQuery.error instanceof Error
                  ? statusQuery.error.message
                  : "The router did not return session status."}
                <div className="mt-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-[11px]"
                    onClick={() => void statusQuery.refetch()}
                  >
                    <RefreshCw className="size-3" /> Retry status
                  </Button>
                </div>
              </InlineAlert>
            ) : statusQuery.isLoading ? (
              <div className="space-y-3">
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : (
              <>
                <div>
                  <div className="flex items-end justify-between">
                    <div>
                      <p className="text-3xl font-semibold tracking-tight">
                        {established}
                        <span className="ml-1 text-sm font-normal text-muted-foreground">
                          / {totalPeers} established
                        </span>
                      </p>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {percent}% of configured sessions are up
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="font-mono text-xs">
                        {formatNumber(totalReceived)} in
                      </p>
                      <p className="font-mono text-xs text-muted-foreground">
                        {formatNumber(totalSent)} out
                      </p>
                      <p className="mt-0.5 text-[9px] text-muted-foreground">
                        prefixes
                      </p>
                    </div>
                  </div>
                  <div
                    className="mt-3 flex h-2 overflow-hidden rounded-full bg-muted"
                    role="img"
                    aria-label={`${established} of ${totalPeers} BGP sessions established`}
                  >
                    <div
                      className="bg-emerald-500 transition-[width]"
                      style={{ width: `${percent}%` }}
                    />
                    {counts.negotiating > 0 && (
                      <div
                        className="bg-amber-500"
                        style={{
                          width: `${
                            totalPeers > 0
                              ? (counts.negotiating / totalPeers) * 100
                              : 0
                          }%`,
                        }}
                      />
                    )}
                    {counts.idle + counts.other > 0 && (
                      <div
                        className="bg-destructive/80"
                        style={{
                          width: `${
                            totalPeers > 0
                              ? ((counts.idle + counts.other) / totalPeers) * 100
                              : 0
                          }%`,
                        }}
                      />
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-3 divide-x divide-border/60 border-y border-border/60">
                  <div className="py-2 pr-3">
                    <p className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                      <span className="size-1.5 rounded-full bg-emerald-500" />
                      Established
                    </p>
                    <p className="mt-1 font-mono text-lg">{counts.established}</p>
                  </div>
                  <div className="px-3 py-2">
                    <p className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                      <span className="size-1.5 rounded-full bg-amber-500" />
                      Negotiating
                    </p>
                    <p className="mt-1 font-mono text-lg">{counts.negotiating}</p>
                  </div>
                  <div className="px-3 py-2">
                    <p className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                      <span className="size-1.5 rounded-full bg-destructive" />
                      Idle / other
                    </p>
                    <p className="mt-1 font-mono text-lg">
                      {counts.idle + counts.other}
                    </p>
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-3 text-[10px] text-muted-foreground">
                  <span className="flex items-center gap-1.5">
                    <Clock className="size-3" />
                    Collected{" "}
                    {status?.collected_at
                      ? formatRelative(status.collected_at)
                      : "pending"}
                  </span>
                  <span className="font-mono">
                    {status?.collected_at
                      ? formatDateTime(status.collected_at)
                      : "—"}
                  </span>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card className="gap-0 py-0">
            <CardHeader className="border-b border-border/60 px-5 py-3.5">
              <CardTitle className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-2">
                  <Layers className="size-4 text-primary" /> Global state
                </span>
                <Button
                  asChild
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-[10px]"
                >
                  <Link href="/bgp/settings/">
                    {writer ? "Edit" : "View"} <ArrowUpRight className="size-3" />
                  </Link>
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent className="divide-y divide-border/50 px-5 py-1">
              {[
                ["System AS", String(config.global.system_as ?? "—")],
                ["Router ID", config.global.router_id ?? "Not set"],
                [
                  "Log neighbor changes",
                  config.global.log_neighbor_changes ? "Enabled" : "Disabled",
                ],
                [
                  "Neighbors",
                  `${config.neighbors.length} configured · ${config.peer_groups.length} groups`,
                ],
                ["Managed families", config.supported_address_families.join(", ")],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="flex items-center justify-between gap-3 py-2.5 text-xs"
                >
                  <span className="text-muted-foreground">{label}</span>
                  <span className="truncate font-mono text-[11px]">{value}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card className="gap-0 py-0">
            <CardHeader className="border-b border-border/60 px-5 py-3.5">
              <CardTitle className="text-sm">Quick actions</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 p-0">
              {quickActions
                .filter((action) => !action.write || writer)
                .map((action) => (
                  <Link
                    key={action.title}
                    href={action.href}
                    className="group flex items-center gap-2 border-r border-b border-border/50 bg-background px-3.5 py-3 text-[11px] font-medium transition-colors hover:bg-muted/50"
                  >
                    <action.icon className="size-3.5 text-primary" />
                    <span className="flex-1">{action.title}</span>
                    <ArrowRight className="size-3 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                  </Link>
                ))}
              <Link
                href="/bgp/neighbors/"
                className="group flex items-center gap-2 border-r border-b border-border/50 bg-background px-3.5 py-3 text-[11px] font-medium transition-colors hover:bg-muted/50"
              >
                <Users className="size-3.5 text-primary" />
                <span className="flex-1">All neighbors</span>
                <ArrowRight className="size-3 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
              </Link>
            </CardContent>
          </Card>
        </div>
      </div>

      <Card variant="surface" className="gap-0 overflow-hidden py-0">
        <CardHeader className="flex-row items-start justify-between gap-3 border-b border-border/60 px-5 py-3.5">
          <div>
            <CardTitle className="flex items-center gap-2 text-sm">
              Peer sessions
              <Badge variant="muted" className="font-mono text-[9px]">
                {neighbors.length}
              </Badge>
            </CardTitle>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Configured neighbors with live session state from the device
            </p>
          </div>
          <div className="flex items-center gap-2">
            {writer && (
              <Button asChild size="sm" className="h-7 gap-1 text-[11px]">
                <Link href="/bgp/neighbors/">
                  Add neighbor <ArrowRight className="size-3" />
                </Link>
              </Button>
            )}
            <Button asChild variant="outline" size="sm" className="h-7 text-[11px]">
              <Link href="/bgp/neighbors/">Manage</Link>
            </Button>
          </div>
        </CardHeader>
        {neighbors.length === 0 ? (
          <div className="p-5">
            <EmptyState
              compact
              icon={RadioTower}
              title="No BGP neighbors configured"
              description="Add a peer to establish sessions and exchange routes."
              action={
                writer ? (
                  <Button asChild size="sm">
                    <Link href="/bgp/neighbors/">Add neighbor</Link>
                  </Button>
                ) : undefined
              }
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[880px] text-sm">
              <thead>
                <tr className="border-b border-border/60 bg-muted/25">
                  {[
                    "Neighbor",
                    "State",
                    "Remote AS",
                    "Uptime",
                    "Prefixes",
                    "Messages",
                    "Families",
                  ].map((label) => (
                    <th
                      key={label}
                      className="px-4 py-2.5 text-left text-[10px] font-semibold tracking-[0.12em] whitespace-nowrap text-muted-foreground uppercase"
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {neighbors.map((neighbor) => (
                  <PeerRow
                    key={neighbor.address}
                    neighbor={neighbor}
                    peer={statusByAddress.get(neighbor.address)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

export default function BgpOverviewPage() {
  const { selectedRouter } = useRouterSelection();
  const { user } = useAuth();
  const writer = canWrite(user?.role);

  return (
    <>
      <BgpPageHeading
        title="BGP overview"
        routerName={selectedRouter?.name}
        description="Live session health, global BGP state and peer status for the selected router."
        actions={
          <>
            <Button asChild variant="outline" size="sm">
              <Link href="/bgp/neighbors/">
                <RadioTower className="size-3.5" /> Neighbors
              </Link>
            </Button>
            <Button asChild size="sm">
              <Link href="/bgp/settings/">
                <SlidersHorizontal className="size-3.5" />
                {writer ? "Global settings" : "View settings"}
              </Link>
            </Button>
          </>
        }
      />

      <BgpRouterBoundary>
        {(router) => <Overview router={router} />}
      </BgpRouterBoundary>
    </>
  );
}
