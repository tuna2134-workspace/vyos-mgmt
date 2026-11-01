"use client";

import * as React from "react";
import Link from "next/link";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  CircleDot,
  Globe2,
  Layers,
  RadioTower,
  RefreshCw,
  Router as RouterIcon,
  ServerOff,
  ShieldCheck,
  Sparkles,
  Waypoints,
} from "lucide-react";

import { useAuth } from "@/lib/auth";
import { useRouterSelection } from "@/lib/router-context";
import { api } from "@/lib/api";
import { queryKeys, useAudit } from "@/lib/queries";
import { canWrite, isAdmin as isAdminRole } from "@/lib/roles";
import {
  formatLatency,
  formatNumber,
  formatRelative,
  humanizeAction,
} from "@/lib/format";
import type { BgpConfig, BgpStatus, SystemInfo } from "@/lib/types";
import { FEATURE_MODULES, modulesForRole } from "@/features/registry";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Stat, StatStrip } from "@/components/ui/stat";
import {
  CardSkeletonGrid,
  DriverBadge,
  EmptyState,
  ErrorPanel,
  InlineAlert,
  PageHeader,
  PeerStateBadge,
  StatSkeleton,
  StatusDot,
  VerdictBadge,
} from "@/components/states";

function RouterHealthCard({
  routerId,
  name,
  host,
  driver,
  description,
  system,
  status,
  config,
}: {
  routerId: string;
  name: string;
  host: string;
  driver: "pyvyos" | "mock";
  description: string | null;
  system: { data?: SystemInfo; isLoading: boolean; isError: boolean; error: unknown };
  status: { data?: BgpStatus; isLoading: boolean; isError: boolean; error: unknown };
  config: { data?: BgpConfig; isLoading: boolean };
}) {
  const reachable = system.data?.reachable === true;
  const configured = status.data?.configured ?? config.data?.configured ?? false;
  const established = status.data?.established_peers ?? 0;
  const totalPeers = status.data?.total_peers ?? 0;
  const networks = config.data?.networks.length ?? 0;

  return (
    <Card className="group gap-4 border-t border-border/70 px-0 py-4 transition-colors">
      <CardHeader className="gap-2 px-5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-[15px]">
              <span className="truncate">{name}</span>
              <DriverBadge driver={driver} />
            </CardTitle>
            <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
              {host}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <StatusDot
              tone={
                system.isLoading
                  ? "muted"
                  : system.isError || !reachable
                    ? "danger"
                    : "success"
              }
              pulse={reachable}
            />
            <span
              className={cn(
                "text-[11px] font-medium",
                system.isLoading
                  ? "text-muted-foreground"
                  : system.isError || !reachable
                    ? "text-destructive"
                    : "text-emerald-600 dark:text-emerald-300",
              )}
            >
              {system.isLoading
                ? "Checking"
                : system.isError || !reachable
                  ? "Unreachable"
                  : "Reachable"}
            </span>
          </div>
        </div>
        {description && (
          <p className="line-clamp-1 text-xs text-muted-foreground">
            {description}
          </p>
        )}
      </CardHeader>

      <CardContent className="space-y-3 px-5">
        <div className="grid grid-cols-2 divide-x divide-border/60 border-y border-border/60">
          <div className="py-2 pr-3">
            <p className="text-[9px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
              Version
            </p>
            {system.isLoading ? (
              <Skeleton className="mt-1 h-3.5 w-24" />
            ) : (
              <p className="mt-1 truncate text-[11px] font-medium">
                {system.data?.version ?? "Unknown"}
              </p>
            )}
          </div>
          <div className="py-2 pl-3">
            <p className="text-[9px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
              Latency
            </p>
            {system.isLoading ? (
              <Skeleton className="mt-1 h-3.5 w-14" />
            ) : (
              <p className="mt-1 font-mono text-[11px] font-medium">
                {formatLatency(system.data?.latency_ms ?? null)}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 border-b border-border/60 pb-2">
          <div className="flex items-center gap-2">
            <Waypoints className="size-3.5 text-muted-foreground" />
            <span className="text-[11px] font-medium">BGP</span>
          </div>
          {status.isLoading ? (
            <Skeleton className="h-3 w-24" />
          ) : status.isError ? (
            <Badge variant="warning" className="text-[10px]">
              Status unavailable
            </Badge>
          ) : !configured ? (
            <Badge variant="muted" className="text-[10px]">
              Not configured
            </Badge>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-muted-foreground">
                {networks} nets
              </span>
              <VerdictBadge
                ok={established === totalPeers && totalPeers > 0}
                labels={[
                  `${established}/${totalPeers} established`,
                  `${established}/${totalPeers} established`,
                ]}
              />
            </div>
          )}
        </div>

        {system.isError && (
          <p className="line-clamp-2 text-[10px] leading-relaxed text-destructive/80">
            {system.error instanceof Error
              ? system.error.message
              : "System information unavailable."}
          </p>
        )}

        <div className="flex items-center justify-between pt-0.5">
          <span className="text-[10px] text-muted-foreground">
            {reachable && system.data?.uptime
              ? `Uptime ${system.data.uptime}`
              : "Uptime unknown"}
          </span>
          <Button
            asChild
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-[11px] text-primary hover:text-primary"
          >
            <Link href={`/bgp/?router=${routerId}`}>
              Open BGP <ArrowRight className="size-3" />
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function AuditPreview({ enabled }: { enabled: boolean }) {
  const audit = useAudit(6, 0, { enabled });

  return (
    <Card className="gap-0 py-0">
      <CardHeader className="flex-row items-center justify-between gap-2 border-b border-border/70 px-5 py-4">
        <div>
          <CardTitle className="text-sm">Recent activity</CardTitle>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            Latest audited changes across the fleet
          </p>
        </div>
        <Button asChild variant="ghost" size="sm" className="h-7 text-[11px]">
          <Link href="/audit/">
            View all <ArrowUpRight className="size-3" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent className="p-0">
        {audit.isLoading ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3">
                <Skeleton className="size-7 rounded-full" />
                <div className="flex-1 space-y-1.5">
                  <Skeleton className="h-3 w-32" />
                  <Skeleton className="h-2.5 w-20" />
                </div>
                <Skeleton className="h-4 w-14" />
              </div>
            ))}
          </div>
        ) : audit.isError ? (
          <div className="p-5">
            <InlineAlert tone="warning" title="Audit log unavailable">
              {audit.error instanceof Error
                ? audit.error.message
                : "Could not load recent activity."}
            </InlineAlert>
          </div>
        ) : (audit.data?.items.length ?? 0) === 0 ? (
          <div className="px-5 py-8 text-center text-xs text-muted-foreground">
            No audited activity yet. Changes will appear here.
          </div>
        ) : (
          <ul className="divide-y divide-border/60">
            {audit.data?.items.map((entry) => (
              <li
                key={entry.id}
                className="flex items-start justify-between gap-3 px-5 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-[12px] font-medium">
                    {humanizeAction(entry.action)}
                  </p>
                  <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                    {entry.actor_username}
                    {entry.router_name ? ` · ${entry.router_name}` : ""} ·{" "}
                    {formatRelative(entry.created_at)}
                  </p>
                </div>
                <Badge
                  variant={
                    entry.status === "success" ? "success" : "destructive"
                  }
                  className="mt-0.5 text-[9px]"
                >
                  {entry.status}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const {
    routers,
    isLoading: routersLoading,
    isError: routersError,
    error: routersErrorObj,
    refetch: refetchRouters,
  } = useRouterSelection();
  const queryClient = useQueryClient();
  const admin = isAdminRole(user?.role);
  const writer = canWrite(user?.role);

  const systemQueries = useQueries({
    queries: routers.map((router) => ({
      queryKey: queryKeys.system(router.id),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api.get<SystemInfo>(`/routers/${router.id}/system`, signal),
      staleTime: 15_000,
      retry: 0,
      refetchInterval: 30_000,
    })),
  });

  const statusQueries = useQueries({
    queries: routers.map((router) => ({
      queryKey: queryKeys.bgpStatus(router.id),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api.get<BgpStatus>(`/routers/${router.id}/bgp/status`, signal),
      staleTime: 15_000,
      retry: 0,
      refetchInterval: 30_000,
    })),
  });

  const configQueries = useQueries({
    queries: routers.map((router) => ({
      queryKey: queryKeys.bgpConfig(router.id),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api.get<BgpConfig>(`/routers/${router.id}/bgp`, signal),
      staleTime: 30_000,
      retry: 0,
    })),
  });

  const loading =
    routersLoading ||
    systemQueries.some((q) => q.isPending) ||
    statusQueries.some((q) => q.isPending) ||
    configQueries.some((q) => q.isPending);

  const reachable = systemQueries.filter(
    (q) => q.data?.reachable === true,
  ).length;
  const established = statusQueries.reduce(
    (sum, q) => sum + (q.data?.established_peers ?? 0),
    0,
  );
  const totalPeers = statusQueries.reduce(
    (sum, q) => sum + (q.data?.total_peers ?? 0),
    0,
  );
  const prefixes = configQueries.reduce(
    (sum, q) => sum + (q.data?.networks.length ?? 0),
    0,
  );
  const lastUpdated = Math.max(
    0,
    ...statusQueries.map((q) => q.dataUpdatedAt),
    ...systemQueries.map((q) => q.dataUpdatedAt),
  );

  const refreshAll = () => {
    void queryClient.invalidateQueries({ queryKey: ["routers"] });
  };

  const bgpModule = FEATURE_MODULES.find((module) => module.key === "bgp") ?? FEATURE_MODULES[0];
  const modules = modulesForRole(user?.role);

  return (
    <>
      <PageHeader
        title="Network overview"
        description="Fleet health, BGP session state and recent operator activity — updated live from each router."
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={refreshAll}
              disabled={loading}
            >
              <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
              Refresh
            </Button>
            <Button asChild size="sm">
              <Link href="/bgp/">
                Open BGP <ArrowRight className="size-3.5" />
              </Link>
            </Button>
          </>
        }
        badge={
          routers.length > 0 ? (
            <Badge variant="outline" className="gap-1.5 font-mono text-[10px]">
              <StatusDot tone="success" pulse />
              live · 30s
            </Badge>
          ) : undefined
        }
      />

      {routersError ? (
        <ErrorPanel
          title="Could not load routers"
          error={routersErrorObj}
          onRetry={() => void refetchRouters()}
        />
      ) : routersLoading ? (
        <div className="space-y-5">
          <StatSkeleton />
          <CardSkeletonGrid count={3} />
        </div>
      ) : (
        <>
          {loading ? (
            <StatSkeleton />
          ) : (
            <StatStrip>
              <Stat
                label="Routers"
                value={formatNumber(routers.length)}
                hint={
                  <span className="flex items-center gap-1.5">
                    <span className="size-1.5 rounded-full bg-primary" />
                    Managed devices
                  </span>
                }
                icon={RouterIcon}
              />
              <Stat
                label="Reachable"
                value={`${reachable}/${routers.length}`}
                hint={
                  <span className="flex items-center gap-1.5">
                    <span className="size-1.5 rounded-full bg-emerald-500" />
                    {routers.length - reachable} unreachable
                  </span>
                }
                icon={Activity}
              />
              <Stat
                label="BGP sessions up"
                value={
                  <span>
                    {established}
                    <span className="text-base font-normal text-muted-foreground">
                      /{totalPeers}
                    </span>
                  </span>
                }
                hint={
                  <span className="flex items-center gap-1.5">
                    <span className="size-1.5 rounded-full bg-cyan-500" />
                    {totalPeers - established} down or in progress
                  </span>
                }
                icon={RadioTower}
              />
              <Stat
                label="Advertised prefixes"
                value={formatNumber(prefixes)}
                hint={
                  <span className="flex items-center gap-1.5">
                    <span className="size-1.5 rounded-full bg-emerald-500" />
                    Across{" "}
                    {configQueries.filter((q) => q.data?.configured).length}{" "}
                    BGP instances
                  </span>
                }
                icon={Globe2}
              />
            </StatStrip>
          )}

          {!routersLoading && routers.length === 0 ? (
            <EmptyState
              icon={ServerOff}
              title="No routers connected yet"
              description={
                admin
                  ? "Register your first VyOS router to start monitoring BGP sessions and advertising prefixes."
                  : "No routers have been registered. Ask an administrator to add one before BGP can be monitored."
              }
              action={
                admin ? (
                  <Button asChild>
                    <Link href="/routers/">
                      <RouterIcon className="size-4" /> Add your first router
                    </Link>
                  </Button>
                ) : (
                  <Button asChild variant="outline">
                    <Link href="/routers/">View routers</Link>
                  </Button>
                )
              }
            />
          ) : (
            <>
              <section className="space-y-3" aria-labelledby="router-health">
                <div className="flex items-end justify-between gap-3">
                  <div>
                    <h2
                      id="router-health"
                      className="text-sm font-semibold tracking-tight"
                    >
                      Router health
                    </h2>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      Per-device reachability and BGP session summary
                    </p>
                  </div>
                  <Button
                    asChild
                    variant="ghost"
                    size="sm"
                    className="h-7 text-[11px]"
                  >
                    <Link href="/routers/">
                      Manage routers <ArrowUpRight className="size-3" />
                    </Link>
                  </Button>
                </div>

                {loading && routers.length > 0 ? (
                  <CardSkeletonGrid count={Math.min(routers.length, 6)} />
                ) : (
                  <div className="grid gap-x-8 md:grid-cols-2 xl:grid-cols-3">
                    {routers.map((router, index) => (
                      <RouterHealthCard
                        key={router.id}
                        routerId={router.id}
                        name={router.name}
                        host={`${router.protocol}://${router.host}:${router.port}`}
                        driver={router.driver}
                        description={router.description}
                        system={systemQueries[index]}
                        status={statusQueries[index]}
                        config={configQueries[index]}
                      />
                    ))}
                  </div>
                )}
              </section>

              <div className="grid gap-5 lg:grid-cols-3">
                <div className="space-y-5 lg:col-span-2">
                  <section aria-labelledby="quick-actions" className="space-y-3">
                    <div>
                      <h2
                        id="quick-actions"
                        className="text-sm font-semibold tracking-tight"
                      >
                        Quick actions
                      </h2>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        Jump straight into common BGP operations
                      </p>
                    </div>
                    <div className="grid gap-px border-y border-border/70 bg-border/60 sm:grid-cols-2 xl:grid-cols-4">
                      {(writer
                        ? bgpModule.quickActions
                        : bgpModule.nav.slice(0, 3).map((item) => ({
                            title: item.title,
                            href: item.href,
                            icon: item.icon ?? Layers,
                          }))
                      ).map((action) => (
                        <Link
                          key={action.href}
                          href={action.href}
                          className="group flex items-start gap-3 bg-background p-3.5 transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                        >
                          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                            <action.icon className="size-4" />
                          </span>
                          <span className="min-w-0">
                            <span className="block text-[13px] font-medium">
                              {action.title}
                            </span>
                            <span className="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground">
                              Open <ArrowRight className="size-2.5" />
                            </span>
                          </span>
                        </Link>
                      ))}
                      {admin && (
                        <Link
                          href="/routers/"
                          className="group flex items-start gap-3 border-dashed border-border bg-background/50 p-3.5 transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none sm:border-l"
                        >
                          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                            <RouterIcon className="size-4" />
                          </span>
                          <span className="min-w-0">
                            <span className="block text-[13px] font-medium">
                              Add router
                            </span>
                            <span className="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground">
                              Admin <ArrowRight className="size-2.5" />
                            </span>
                          </span>
                        </Link>
                      )}
                    </div>
                  </section>

                  {bgpModule && (
                    <section aria-labelledby="modules" className="space-y-3">
                      <div>
                        <h2
                          id="modules"
                          className="text-sm font-semibold tracking-tight"
                        >
                          Feature modules
                        </h2>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          Enabled capabilities, generated from the feature
                          registry
                        </p>
                      </div>
                      <div className="space-y-3">
                        {modules.map((module) => (
                          <Card
                            key={module.key}
                            className="gap-0 overflow-hidden py-0"
                          >
                            <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-start sm:justify-between">
                              <div className="flex gap-3">
                                <div className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                                  <module.icon className="size-5" />
                                </div>
                                <div>
                                  <div className="flex items-center gap-2">
                                    <h3 className="text-sm font-semibold">
                                      {module.title}
                                    </h3>
                                    <Badge
                                      variant={
                                        module.status === "available"
                                          ? "success"
                                          : "muted"
                                      }
                                      className="text-[9px]"
                                    >
                                      {module.status === "available"
                                        ? "available"
                                        : "soon"}
                                    </Badge>
                                  </div>
                                  <p className="mt-1 max-w-xl text-xs leading-relaxed text-muted-foreground">
                                    {module.description}
                                  </p>
                                </div>
                              </div>
                              <Button asChild variant="outline" size="sm">
                                <Link href={module.href}>
                                  Open module <ArrowRight className="size-3.5" />
                                </Link>
                              </Button>
                            </div>
                            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border/70 px-5 py-3">
                              {module.nav.map((item) => (
                                <Link
                                  key={item.href}
                                  href={item.href}
                                  className="group flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
                                >
                                  {item.icon && (
                                    <item.icon className="size-3 text-muted-foreground group-hover:text-primary" />
                                  )}
                                  {item.title}
                                  <ArrowRight className="size-2.5 opacity-0 transition-opacity group-hover:opacity-100" />
                                </Link>
                              ))}
                            </div>
                          </Card>
                        ))}
                      </div>
                    </section>
                  )}

                  {!admin && (
                    <InlineAlert tone="info" title="Operator workspace">
                      You are signed in as a{" "}
                      <span className="font-medium capitalize">{user?.role}</span>.
                      {writer
                        ? " BGP changes are permitted and audited."
                        : " BGP configuration is read-only for your account."}{" "}
                      Audit and user management are restricted to administrators.
                    </InlineAlert>
                  )}
                </div>

                <div className="space-y-5">
                  {admin ? (
                    <AuditPreview enabled={admin} />
                  ) : (
                    <Card className="gap-0 py-0">
                      <CardHeader className="border-b border-border/70 px-5 py-4">
                        <CardTitle className="flex items-center gap-2 text-sm">
                          <ShieldCheck className="size-4 text-primary" />
                          Access scope
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-3 p-5 text-xs text-muted-foreground">
                        <p>
                          Your role is{" "}
                          <span className="font-medium text-foreground capitalize">
                            {user?.role}
                          </span>
                          . The API enforces the same limits shown in the UI.
                        </p>
                        <ul className="space-y-2">
                          <li className="flex items-center gap-2">
                            <CircleDot className="size-3 text-emerald-500" />
                            Read routers and BGP status
                          </li>
                          <li className="flex items-center gap-2">
                            <CircleDot
                              className={cn(
                                "size-3",
                                writer ? "text-emerald-500" : "text-muted-foreground",
                              )}
                            />
                            Change BGP configuration
                          </li>
                          <li className="flex items-center gap-2">
                            <CircleDot className="size-3 text-muted-foreground" />
                            Manage users and audit
                          </li>
                        </ul>
                      </CardContent>
                    </Card>
                  )}

                  <Card className="gap-0 overflow-hidden py-0">
                    <CardHeader className="border-b border-border/70 px-5 py-4">
                      <CardTitle className="flex items-center gap-2 text-sm">
                        <Sparkles className="size-4 text-primary" />
                        Fleet snapshot
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-2.5 p-5 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">
                          BGP configured
                        </span>
                        <span className="font-mono">
                          {configQueries.filter((q) => q.data?.configured).length}{" "}
                          / {routers.length}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">
                          Unreachable devices
                        </span>
                        <span className="font-mono">
                          {Math.max(0, routers.length - reachable)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">
                          Last status poll
                        </span>
                        <span className="font-mono text-[10px]">
                          {lastUpdated
                            ? formatRelative(new Date(lastUpdated).toISOString())
                            : "pending"}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-muted-foreground">Peer states</span>
                        <div className="flex flex-wrap items-center justify-end gap-1">
                          {statusQueries
                            .flatMap((q) => q.data?.peers ?? [])
                            .slice(0, 4)
                            .map((peer, i) => (
                              <React.Fragment key={`${peer.address}-${i}`}>
                                <PeerStateBadge state={peer.state} />
                              </React.Fragment>
                            ))}
                          {statusQueries.every(
                            (q) => (q.data?.peers.length ?? 0) === 0,
                          ) && (
                            <span className="text-[10px] text-muted-foreground">
                              no peers
                            </span>
                          )}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}
