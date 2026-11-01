"use client";

import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  CircleSlash,
  Filter,
  MoreHorizontal,
  Network,
  Pencil,
  Plus,
  RefreshCw,
  Route,
  Search,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth";
import { errorMessage } from "@/lib/api";
import { queryKeys, useStaticRoutes } from "@/lib/queries";
import { canWrite } from "@/lib/roles";
import type { Router, StaticRoute, StaticRouteFamily } from "@/lib/types";
import { cn } from "@/lib/utils";
import { RouterBoundary } from "@/components/router-boundary";
import {
  STATIC_FAMILY_LABEL,
  STATIC_FAMILY_VYOS_PATH,
  NextHopList,
  RouteTypeBadge,
  StaticFamilyBadge,
  distanceTagLabel,
  sortStaticRoutes,
  staticRouteCounts,
  staticRouteType,
} from "@/components/static-routes/shared";
import {
  StaticRouteDeleteDialog,
  StaticRouteFormDialog,
} from "@/components/static-routes/route-dialogs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Stat, StatStrip } from "@/components/ui/stat";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  EmptyState,
  ErrorPanel,
  InlineAlert,
  PageHeader,
  TableSkeleton,
} from "@/components/states";

/* -------------------------------------------------------------------------- */
/* URL state                                                                  */
/* -------------------------------------------------------------------------- */

const FAMILY_PARAM = "family";
const FAMILIES: StaticRouteFamily[] = ["ipv4", "ipv6"];

function isFamily(value: string | null): value is StaticRouteFamily {
  return value === "ipv4" || value === "ipv6";
}

function readFamilyParam(): StaticRouteFamily | null {
  if (typeof window === "undefined") return null;
  const value = new URLSearchParams(window.location.search).get(FAMILY_PARAM);
  return isFamily(value) ? value : null;
}

/**
 * Only touch `family`; `?router=` and any other parameter are preserved.
 * `window.history.replaceState` keeps the static export free of navigations.
 */
function writeFamilyParam(family: StaticRouteFamily) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.set(FAMILY_PARAM, family);
  window.history.replaceState(window.history.state, "", url.toString());
}

/* -------------------------------------------------------------------------- */
/* Small pieces                                                               */
/* -------------------------------------------------------------------------- */

function RouterBadge({ name }: { name: string }) {
  return (
    <Badge
      variant="outline"
      className="gap-1.5 border-primary/25 bg-primary/5 font-mono text-[10px]"
    >
      <span className="size-1.5 rounded-full bg-primary" />
      {name}
    </Badge>
  );
}

function RoutesTable({
  routes,
  writer,
  onEdit,
  onDelete,
}: {
  routes: StaticRoute[];
  writer: boolean;
  onEdit: (route: StaticRoute) => void;
  onDelete: (route: StaticRoute) => void;
}) {
  return (
    <Table className="min-w-[720px]">
      <TableHeader>
        <TableRow className="bg-muted/25 hover:bg-muted/25">
          <TableHead>Prefix</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Next hops</TableHead>
          <TableHead className="hidden sm:table-cell">
            Distance / Tag
          </TableHead>
          <TableHead className="hidden lg:table-cell">Description</TableHead>
          <TableHead className="w-12 text-right">
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {routes.map((route) => {
          const type = staticRouteType(route);
          return (
            <TableRow key={`${route.family}:${route.prefix}`} className="align-top">
              <TableCell>
                <span className="font-mono text-[12px] font-medium break-all">
                  {route.prefix}
                </span>
                {route.description && (
                  <p className="mt-1 max-w-[240px] truncate text-[10px] text-muted-foreground lg:hidden">
                    {route.description}
                  </p>
                )}
              </TableCell>
              <TableCell>
                <RouteTypeBadge type={type} />
              </TableCell>
              <TableCell className="max-w-[320px] whitespace-normal">
                <NextHopList hops={route.next_hops} />
              </TableCell>
              <TableCell className="hidden sm:table-cell">
                <span
                  className={cn(
                    "font-mono text-[11px]",
                    type === "gateway"
                      ? "text-muted-foreground"
                      : "text-foreground",
                  )}
                >
                  {distanceTagLabel(route)}
                </span>
              </TableCell>
              <TableCell className="hidden max-w-[220px] lg:table-cell">
                <span
                  className="line-clamp-2 text-[11px] leading-relaxed text-muted-foreground"
                  title={route.description ?? undefined}
                >
                  {route.description || "—"}
                </span>
              </TableCell>
              <TableCell className="text-right">
                {writer ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Actions for ${route.prefix}`}
                      >
                        <MoreHorizontal className="size-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-40">
                      <DropdownMenuItem onSelect={() => onEdit(route)}>
                        <Pencil /> Edit route
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        variant="destructive"
                        onSelect={() => onDelete(route)}
                      >
                        <Trash2 /> Delete route
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : (
                  <span className="text-[11px] text-muted-foreground">—</span>
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/* -------------------------------------------------------------------------- */
/* Page                                                                       */
/* -------------------------------------------------------------------------- */

function StaticRoutesContent({ router }: { router: Router }) {
  const { user } = useAuth();
  const writer = canWrite(user?.role);
  const queryClient = useQueryClient();
  const routesQuery = useStaticRoutes(router.id);

  // Read ?family= in the initialiser so a deep link (e.g. the registry quick
  // actions) paints the right tab. Tabs render only after the query resolves,
  // so this cannot cause a hydration mismatch with the prerendered shell.
  const [family, setFamily] = React.useState<StaticRouteFamily>(
    () => readFamilyParam() ?? "ipv4",
  );
  const [search, setSearch] = React.useState("");
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editingRoute, setEditingRoute] = React.useState<StaticRoute | null>(
    null,
  );
  const [deleteTarget, setDeleteTarget] = React.useState<StaticRoute | null>(
    null,
  );
  const [refreshing, setRefreshing] = React.useState(false);

  const routes = React.useMemo(
    () => sortStaticRoutes(routesQuery.data?.items ?? []),
    [routesQuery.data],
  );

  const byFamily = React.useMemo<Record<StaticRouteFamily, StaticRoute[]>>(
    () => ({
      ipv4: routes.filter((route) => route.family === "ipv4"),
      ipv6: routes.filter((route) => route.family === "ipv6"),
    }),
    [routes],
  );

  const familyRoutes = byFamily[family];
  const counts = React.useMemo(
    () => staticRouteCounts(familyRoutes),
    [familyRoutes],
  );
  const nextHopCount = React.useMemo(
    () =>
      familyRoutes.reduce(
        (total, route) => total + route.next_hops.length,
        0,
      ),
    [familyRoutes],
  );

  // Write the default family so links stay shareable.
  React.useEffect(() => {
    if (!readFamilyParam()) writeFamilyParam(family);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Browser back/forward changes ?family without a Next navigation.
  React.useEffect(() => {
    const onPopState = () => {
      const next = readFamilyParam();
      if (next) setFamily(next);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const selectFamily = (next: StaticRouteFamily) => {
    if (next === family) return;
    setFamily(next);
    writeFamilyParam(next);
  };

  const openCreate = () => {
    setEditingRoute(null);
    setDialogOpen(true);
  };

  const openEdit = (route: StaticRoute) => {
    setEditingRoute(route);
    setDialogOpen(true);
  };

  const filtered = React.useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return familyRoutes;
    return familyRoutes.filter((route) => {
      const hopText = route.next_hops
        .flatMap((hop) => [hop.address ?? "", hop.interface ?? ""])
        .join(" ");
      return [route.prefix, route.description ?? "", hopText]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [familyRoutes, search]);

  const refresh = async () => {
    setRefreshing(true);
    await queryClient.invalidateQueries({
      queryKey: queryKeys.staticRoutes(router.id),
      exact: true,
    });
    setRefreshing(false);
    toast.info("Static routes refreshed");
  };

  const heading = (
    <PageHeader
      title="Static routes"
      badge={<RouterBadge name={router.name} />}
      description="IPv4 and IPv6 static routes: unicast gateway routes with one or more next hops, plus blackhole and reject routes for traffic that must be discarded."
      actions={
        <>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refresh()}
            disabled={refreshing}
          >
            <RefreshCw
              className={refreshing ? "size-3.5 animate-spin" : "size-3.5"}
            />
            Refresh
          </Button>
          {writer && (
            <Button size="sm" onClick={openCreate}>
              <Plus className="size-4" /> New route
            </Button>
          )}
        </>
      }
    />
  );

  const readOnlyBanner = !writer && (
    <InlineAlert tone="info" title="Read-only access">
      Viewers can inspect static routes and their next hops. Creating, editing
      and deleting IPv4/IPv6 static routes requires the operator or
      administrator role.
    </InlineAlert>
  );

  if (routesQuery.isLoading) {
    return (
      <>
        {heading}
        <TableSkeleton rows={6} />
      </>
    );
  }

  if (routesQuery.isError && !routesQuery.data) {
    return (
      <>
        {heading}
        <ErrorPanel
          title={`Could not read static routes from ${router.name}`}
          error={routesQuery.error}
          onRetry={() => void routesQuery.refetch()}
        />
      </>
    );
  }

  const otherFamily: StaticRouteFamily = family === "ipv4" ? "ipv6" : "ipv4";

  return (
    <>
      {heading}

      {readOnlyBanner}

      {routesQuery.isError && (
        <InlineAlert tone="warning" title="Showing cached static routes">
          The latest refresh failed: {errorMessage(routesQuery.error)}
        </InlineAlert>
      )}

      <Tabs
        value={family}
        onValueChange={(value) => {
          if (isFamily(value)) selectFamily(value);
        }}
        className="gap-3"
      >
        <TabsList
          aria-label="Static route address family"
          className="grid w-full grid-cols-2 bg-muted/60 sm:w-fit"
        >
          {FAMILIES.map((value) => (
            <TabsTrigger key={value} value={value} className="gap-2 px-4">
              {STATIC_FAMILY_LABEL[value]}
              <Badge
                variant={family === value ? "default" : "muted"}
                className="h-4 min-w-4 px-1 font-mono text-[9px]"
              >
                {byFamily[value].length}
              </Badge>
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value={family} className="mt-1 space-y-4">
          <StatStrip>
            <Stat
              label="Total"
              value={counts.total}
              hint={
                <span className="font-mono text-[10px]">
                  {STATIC_FAMILY_VYOS_PATH[family]}
                </span>
              }
              icon={Route}
            />
            <Stat
              label="Unicast"
              value={counts.unicast}
              hint={`${nextHopCount} next ${nextHopCount === 1 ? "hop" : "hops"}`}
              icon={Network}
            />
            <Stat
              label="Blackhole"
              value={counts.blackhole}
              hint="Silently dropped"
              icon={CircleSlash}
            />
            <Stat
              label="Reject"
              value={counts.reject}
              hint="ICMP unreachable"
              icon={Ban}
            />
          </StatStrip>

          {familyRoutes.length === 0 ? (
            <EmptyState
              icon={Route}
              title={`No ${STATIC_FAMILY_LABEL[family]} static routes`}
              description={
                <>
                  This router has no routes under{" "}
                  <code className="font-mono text-[11px]">
                    {STATIC_FAMILY_VYOS_PATH[family]}
                  </code>
                  .{" "}
                  {byFamily[otherFamily].length > 0
                    ? `Switch to the ${STATIC_FAMILY_LABEL[otherFamily]} tab to see the routes that exist.`
                    : "Create a gateway route with one or more next hops, or discard traffic with a blackhole/reject route."}
                </>
              }
              action={
                writer ? (
                  <Button onClick={openCreate}>
                    <Plus className="size-4" /> Create{" "}
                    {STATIC_FAMILY_LABEL[family]} static route
                  </Button>
                ) : (
                  <span className="text-xs text-muted-foreground">
                    An operator or administrator can create static routes.
                  </span>
                )
              }
            />
          ) : (
            <Card variant="surface" className="gap-0 overflow-hidden py-0">
              <div className="flex flex-col gap-2 border-b border-border/70 p-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="relative w-full sm:max-w-sm">
                  <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search prefix, description or next hop…"
                    className="h-8 pl-8 text-xs"
                    aria-label={`Search ${STATIC_FAMILY_LABEL[family]} static routes`}
                  />
                </div>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-muted-foreground">
                  <span className="font-mono">
                    {filtered.length}/{familyRoutes.length} routes
                  </span>
                  <span aria-hidden="true">·</span>
                  <span className="font-mono">
                    {STATIC_FAMILY_VYOS_PATH[family]}
                  </span>
                </div>
              </div>

              {filtered.length === 0 ? (
                <div className="px-4 py-10 text-center">
                  <Filter className="mx-auto size-5 text-muted-foreground" />
                  <p className="mt-2 text-sm font-medium">
                    No static routes match
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Adjust the search to see all {familyRoutes.length}{" "}
                    {STATIC_FAMILY_LABEL[family]} routes.
                  </p>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mt-2"
                    onClick={() => setSearch("")}
                  >
                    Clear search
                  </Button>
                </div>
              ) : (
                <RoutesTable
                  routes={filtered}
                  writer={writer}
                  onEdit={openEdit}
                  onDelete={(route) => setDeleteTarget(route)}
                />
              )}
            </Card>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-3">
            <p className="max-w-2xl text-[10px] leading-relaxed text-muted-foreground">
              Prefixes are canonical (host bits zero) and family-specific;
              duplicate family + prefix pairs are refused. Blackhole and reject
              routes carry an optional distance (1–255) and tag (1–4294967295)
              instead of next hops. BFD, SRv6 segments, VRF leaking, non-main
              routing tables and multicast (mroute) are not exposed yet.
            </p>
            <div className="flex items-center gap-2">
              <StaticFamilyBadge family={family} />
              <Badge variant="outline" className="font-mono text-[9px]">
                {familyRoutes.length} configured
              </Badge>
            </div>
          </div>
        </TabsContent>
      </Tabs>

      <StaticRouteFormDialog
        key={`static-route:${editingRoute ? `${editingRoute.family}:${editingRoute.prefix}` : `new:${family}`}`}
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open) setEditingRoute(null);
        }}
        routerId={router.id}
        family={family}
        route={editingRoute}
        onSaved={(saved) => {
          // A route created for the other family would otherwise be invisible.
          selectFamily(saved.family);
          setSearch("");
        }}
      />

      <StaticRouteDeleteDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        routerId={router.id}
        route={deleteTarget}
        onDeleted={(deleted) => {
          if (
            editingRoute?.family === deleted.family &&
            editingRoute?.prefix === deleted.prefix
          ) {
            setEditingRoute(null);
          }
        }}
      />
    </>
  );
}

export default function StaticRoutesPage() {
  return (
    <RouterBoundary emptyDescription="Add a VyOS device before managing static routes.">
      {(router) => <StaticRoutesContent router={router} />}
    </RouterBoundary>
  );
}
