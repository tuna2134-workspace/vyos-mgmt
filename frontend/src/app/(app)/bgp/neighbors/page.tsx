"use client";

import * as React from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Filter,
  MoreHorizontal,
  Pencil,
  Plus,
  RadioTower,
  RefreshCw,
  Search,
  Tags,
  Trash2,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth";
import {
  queryKeys,
  useBgpConfig,
  useBgpStatus,
  useDeleteNeighbor,
} from "@/lib/queries";
import { canWrite } from "@/lib/roles";
import { errorMessage } from "@/lib/api";
import type { BgpNeighbor, Router } from "@/lib/types";
import {
  AddressFamilyBadges,
  BgpPageHeading,
  BgpRouterBoundary,
  NoBgpConfigured,
  RouteMapPolicy,
} from "@/components/bgp/shared";
import { NeighborFormDialog } from "@/components/bgp/neighbor-form-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  EmptyState,
  ErrorPanel,
  InlineAlert,
  PeerStateBadge,
  Spinner,
  StatusDot,
  TableSkeleton,
} from "@/components/states";

type AfFilter = "all" | "ipv4-unicast" | "ipv6-unicast";
type StateFilter = "all" | "established" | "down";

function NeighborsContent({ router }: { router: Router }) {
  const { user } = useAuth();
  const writer = canWrite(user?.role);
  const queryClient = useQueryClient();
  const configQuery = useBgpConfig(router.id);
  const statusQuery = useBgpStatus(router.id);
  const deleteNeighbor = useDeleteNeighbor(router.id);

  const [search, setSearch] = React.useState("");
  const [afFilter, setAfFilter] = React.useState<AfFilter>("all");
  const [stateFilter, setStateFilter] = React.useState<StateFilter>("all");
  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<BgpNeighbor | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<string | null>(null);
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
    toast.info("Neighbors refreshed");
  };

  const config = configQuery.data;
  const peersByAddress = new Map(
    (statusQuery.data?.peers ?? []).map((peer) => [peer.address, peer]),
  );

  const filtered = React.useMemo(() => {
    const neighbors = config?.neighbors ?? [];
    const needle = search.trim().toLowerCase();
    return neighbors.filter((neighbor) => {
      const peer = peersByAddress.get(neighbor.address);
      if (
        afFilter !== "all" &&
        !neighbor.address_families[afFilter]
      ) {
        return false;
      }
      if (stateFilter === "established" && !peer?.established) return false;
      if (stateFilter === "down" && peer?.established) return false;
      if (!needle) return true;
      return [
        neighbor.address,
        neighbor.remote_as != null ? String(neighbor.remote_as) : "",
        neighbor.description ?? "",
        neighbor.peer_group ?? "",
        neighbor.update_source ?? "",
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [config?.neighbors, search, afFilter, stateFilter, peersByAddress]);

  const total = config?.neighbors.length ?? 0;
  const established = (statusQuery.data?.peers ?? []).filter(
    (peer) => peer.established,
  ).length;

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteNeighbor.mutateAsync(deleteTarget);
      toast.success("Neighbor removed", {
        description: `${deleteTarget} was deleted from the router configuration.`,
      });
      setDeleteTarget(null);
    } catch (error) {
      toast.error("Could not delete neighbor", {
        description: errorMessage(error),
      });
    }
  };

  const heading = (
    <BgpPageHeading
      title="BGP neighbors"
      routerName={router.name}
      description="Peer sessions, timers and per-address-family policy. Session state is collected live from the device."
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
          {writer && config?.configured && (
            <Button
              size="sm"
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              <Plus className="size-4" /> Add neighbor
            </Button>
          )}
        </>
      }
    />
  );

  if (configQuery.isLoading) {
    return (
      <>
        {heading}
        <TableSkeleton rows={7} />
      </>
    );
  }

  if (configQuery.isError && !config) {
    return (
      <>
        {heading}
        <ErrorPanel
          title={`Could not read BGP from ${router.name}`}
          error={configQuery.error}
          onRetry={() => void configQuery.refetch()}
        />
      </>
    );
  }

  if (!config) return <>{heading}</>;

  if (!config.configured) {
    return (
      <>
        {heading}
        <NoBgpConfigured router={router} />
      </>
    );
  }

  return (
    <>
      {heading}

      {!writer && (
        <InlineAlert tone="info" title="Read-only view">
          Viewers can inspect neighbors and live session state. BGP changes
          require the operator or administrator role.
        </InlineAlert>
      )}

      {statusQuery.isError && (
        <InlineAlert tone="warning" title="Live session state unavailable">
          Configuration is shown from the router's managed model.{" "}
          {statusQuery.error instanceof Error
            ? statusQuery.error.message
            : "Status collection failed."}
        </InlineAlert>
      )}

      <Card variant="surface" className="gap-0 overflow-hidden py-0">
        <div className="flex flex-col gap-3 border-b border-border/70 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative w-full max-w-xs">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search address, AS, description…"
                className="h-8 pl-8 text-xs"
                aria-label="Search neighbors"
              />
            </div>
            <Select
              value={afFilter}
              onValueChange={(value) => setAfFilter(value as AfFilter)}
            >
              <SelectTrigger
                size="sm"
                className="h-8 w-[132px] text-xs"
                aria-label="Filter by address family"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All families</SelectItem>
                <SelectItem value="ipv4-unicast">IPv4 unicast</SelectItem>
                <SelectItem value="ipv6-unicast">IPv6 unicast</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={stateFilter}
              onValueChange={(value) => setStateFilter(value as StateFilter)}
            >
              <SelectTrigger
                size="sm"
                className="h-8 w-[148px] text-xs"
                aria-label="Filter by session state"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Any state</SelectItem>
                <SelectItem value="established">Established</SelectItem>
                <SelectItem value="down">Not established</SelectItem>
              </SelectContent>
            </Select>
            <div className="ml-auto flex items-center gap-3 text-[11px] text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <StatusDot
                  tone={statusQuery.isError ? "warning" : "success"}
                  pulse={!statusQuery.isError}
                />
                {statusQuery.isError ? "status stale" : "live 15s"}
              </span>
              <span className="font-mono">
                {established}/{total} up
              </span>
              <span className="font-mono">
                {filtered.length}/{total} shown
              </span>
            </div>
          </div>
        </div>

        {total === 0 ? (
          <div className="p-5">
            <EmptyState
              compact
              icon={RadioTower}
              title="No BGP neighbors yet"
              description="Add a peer to start exchanging routes. Sessions will appear here with live state."
              action={
                writer ? (
                  <Button
                    size="sm"
                    onClick={() => {
                      setEditing(null);
                      setFormOpen(true);
                    }}
                  >
                    <Plus className="size-4" /> Add neighbor
                  </Button>
                ) : undefined
              }
            />
          </div>
        ) : filtered.length === 0 ? (
          <div className="px-4 py-12 text-center">
            <Filter className="mx-auto size-5 text-muted-foreground" />
            <p className="mt-2 text-sm font-medium">No neighbors match filters</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Adjust the search or clear the filters to see all {total}{" "}
              neighbors.
            </p>
            <Button
              variant="ghost"
              size="sm"
              className="mt-2"
              onClick={() => {
                setSearch("");
                setAfFilter("all");
                setStateFilter("all");
              }}
            >
              Clear filters
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1000px] text-sm">
              <thead>
                <tr className="border-b border-border/60 bg-muted/25">
                  {[
                    "Neighbor",
                    "Session",
                    "Remote AS",
                    "Peer group",
                    "Families",
                    "Timers",
                    "",
                  ].map((label, i) => (
                    <th
                      key={label || i}
                      className="px-4 py-2.5 text-left text-[10px] font-semibold tracking-[0.12em] whitespace-nowrap text-muted-foreground uppercase"
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((neighbor) => {
                  const peer = peersByAddress.get(neighbor.address);
                  return (
                    <tr
                      key={neighbor.address}
                      className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/25"
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-background text-muted-foreground">
                            <RadioTower className="size-3.5" />
                          </span>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="font-mono text-[12px] font-medium">
                                {neighbor.address}
                              </span>
                              {neighbor.shutdown && (
                                <Badge
                                  variant="destructive"
                                  className="text-[9px]"
                                >
                                  shutdown
                                </Badge>
                              )}
                              {neighbor.passive && (
                                <Badge variant="muted" className="text-[9px]">
                                  passive
                                </Badge>
                              )}
                            </div>
                            <p className="max-w-[240px] truncate text-[10px] text-muted-foreground">
                              {neighbor.description ??
                                (neighbor.update_source
                                  ? `source ${neighbor.update_source}`
                                  : "No description")}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <PeerStateBadge
                          state={peer?.state ?? "Unknown"}
                        />
                        {peer?.uptime && (
                          <p className="mt-1 font-mono text-[9px] text-muted-foreground">
                            up {peer.uptime}
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <p className="font-mono text-[11px]">
                          {neighbor.remote_as ?? "inherited"}
                        </p>
                        <p className="text-[9px] text-muted-foreground">
                          {neighbor.local_as
                            ? `local ${neighbor.local_as}`
                            : neighbor.ebgp_multihop
                              ? `multihop ${neighbor.ebgp_multihop}`
                              : "eBGP"}
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        {neighbor.peer_group ? (
                          <Badge variant="outline" className="gap-1 text-[10px]">
                            <Tags className="size-2.5" />
                            {neighbor.peer_group}
                          </Badge>
                        ) : (
                          <span className="text-[11px] text-muted-foreground">
                            —
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <AddressFamilyBadges
                          families={neighbor.address_families}
                        />
                        <RouteMapPolicy
                          families={neighbor.address_families}
                        />
                      </td>
                      <td className="px-4 py-3 font-mono text-[10px] text-muted-foreground">
                        {neighbor.timers
                          ? `${neighbor.timers.keepalive}/${neighbor.timers.holdtime}`
                          : "default"}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            asChild
                            variant="ghost"
                            size="sm"
                            className="h-7 gap-1 px-2 text-[11px]"
                          >
                            <Link href="/bgp/">
                              Status <ArrowRight className="size-3" />
                            </Link>
                          </Button>
                          {writer && (
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon-sm"
                                  aria-label={`Actions for ${neighbor.address}`}
                                >
                                  <MoreHorizontal className="size-4" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end" className="w-44">
                                <DropdownMenuItem
                                  onSelect={() => {
                                    setEditing(neighbor);
                                    setFormOpen(true);
                                  }}
                                >
                                  <Pencil /> Edit neighbor
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem
                                  variant="destructive"
                                  onSelect={() =>
                                    setDeleteTarget(neighbor.address)
                                  }
                                >
                                  <Trash2 /> Delete neighbor
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid gap-px border-y border-border/70 bg-border/60 sm:grid-cols-2 lg:grid-cols-3">
        <Link
          href="/bgp/peer-groups/"
          className="group flex items-center gap-3 bg-background px-4 py-3 transition-colors hover:bg-muted/40"
        >
          <span className="text-primary">
            <Tags className="size-4" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[12px] font-medium">Peer groups</span>
            <span className="block text-[10px] text-muted-foreground">
              {config.peer_groups.length} reusable templates
            </span>
          </span>
          <ArrowRight className="size-3.5 text-muted-foreground" />
        </Link>
        <Link
          href="/bgp/networks/"
          className="group flex items-center gap-3 bg-background px-4 py-3 transition-colors hover:bg-muted/40"
        >
          <span className="text-primary">
            <Users className="size-4" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[12px] font-medium">Advertised networks</span>
            <span className="block text-[10px] text-muted-foreground">
              {config.networks.length} prefixes announced
            </span>
          </span>
          <ArrowRight className="size-3.5 text-muted-foreground" />
        </Link>
        <Link
          href="/bgp/"
          className="group flex items-center gap-3 bg-background px-4 py-3 transition-colors hover:bg-muted/40"
        >
          <span className="text-primary">
            <RadioTower className="size-4" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[12px] font-medium">Session overview</span>
            <span className="block text-[10px] text-muted-foreground">
              {established} of {total} established
            </span>
          </span>
          <ArrowRight className="size-3.5 text-muted-foreground" />
        </Link>
      </div>

      {formOpen && (
        <NeighborFormDialog
          key={editing?.address ?? "create"}
          open={formOpen}
          onOpenChange={setFormOpen}
          routerId={router.id}
          neighbor={editing}
          peerGroups={config.peer_groups.map((group) => group.name)}
        />
      )}

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open && !deleteNeighbor.isPending) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete neighbor {deleteTarget}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              The peer session will be removed from the router and its
              configuration. Routes learned from this neighbor will be withdrawn.
              This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteNeighbor.isPending && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Spinner /> Removing neighbor…
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteNeighbor.isPending}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleteNeighbor.isPending}
              onClick={(event) => {
                event.preventDefault();
                void handleDelete();
              }}
            >
              <Trash2 className="size-4" /> Delete neighbor
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

export default function NeighborsPage() {
  return (
    <BgpRouterBoundary>
      {(router) => <NeighborsContent router={router} />}
    </BgpRouterBoundary>
  );
}
