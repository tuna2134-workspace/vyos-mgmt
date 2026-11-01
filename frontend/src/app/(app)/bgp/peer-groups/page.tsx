"use client";

import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Tags,
  Trash2,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth";
import { queryKeys, useBgpConfig, useDeletePeerGroup } from "@/lib/queries";
import { canWrite } from "@/lib/roles";
import { errorMessage } from "@/lib/api";
import type { BgpPeerGroup, Router } from "@/lib/types";
import {
  AddressFamilyBadges,
  BgpPageHeading,
  BgpRouterBoundary,
  NoBgpConfigured,
} from "@/components/bgp/shared";
import { PeerGroupFormDialog } from "@/components/bgp/peer-group-form-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Stat, StatStrip } from "@/components/ui/stat";
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
  EmptyState,
  ErrorPanel,
  InlineAlert,
  Spinner,
  TableSkeleton,
} from "@/components/states";

function GroupsContent({ router }: { router: Router }) {
  const { user } = useAuth();
  const writer = canWrite(user?.role);
  const queryClient = useQueryClient();
  const configQuery = useBgpConfig(router.id);
  const deleteGroup = useDeletePeerGroup(router.id);

  const [open, setOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<BgpPeerGroup | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<BgpPeerGroup | null>(
    null,
  );
  const [refreshing, setRefreshing] = React.useState(false);

  const config = configQuery.data;
  const groups = config?.peer_groups ?? [];
  const neighborCount = config?.neighbors.length ?? 0;

  const refresh = async () => {
    setRefreshing(true);
    await queryClient.invalidateQueries({
      queryKey: queryKeys.bgpConfig(router.id),
    });
    setRefreshing(false);
  };

  const usage = (group: BgpPeerGroup) =>
    (config?.neighbors ?? []).filter(
      (neighbor) => neighbor.peer_group === group.name,
    ).length;

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteGroup.mutateAsync(deleteTarget.name);
      toast.success("Peer group deleted", {
        description: `${deleteTarget.name} was removed from the configuration.`,
      });
      setDeleteTarget(null);
    } catch (error) {
      toast.error("Could not delete peer group", {
        description: errorMessage(error),
      });
    }
  };

  const heading = (
    <BgpPageHeading
      title="Peer groups"
      routerName={router.name}
      description="Reusable session templates. Neighbors inherit the group's remote AS, transport settings and address-family policy."
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
                setOpen(true);
              }}
            >
              <Plus className="size-4" /> Create peer group
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
        <TableSkeleton rows={5} />
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
          Viewers can inspect peer groups. Changes require the operator or
          administrator role.
        </InlineAlert>
      )}

      <StatStrip className="grid-cols-1 sm:grid-cols-3 xl:grid-cols-3">
        <Stat label="Peer groups" value={groups.length} hint="Reusable templates" />
        <Stat label="Neighbors" value={neighborCount} hint="Configured sessions" />
        <Stat
          label="Grouped sessions"
          value={config.neighbors.filter((neighbor) => neighbor.peer_group).length}
          hint="Neighbors inheriting a group"
        />
      </StatStrip>

      <Card variant="surface" className="gap-0 overflow-hidden py-0">
        {groups.length === 0 ? (
          <div className="p-5">
            <EmptyState
              compact
              icon={Tags}
              title="No peer groups"
              description="Group neighbors that share the same remote AS and policy to keep configuration consistent."
              action={
                writer ? (
                  <Button
                    size="sm"
                    onClick={() => {
                      setEditing(null);
                      setOpen(true);
                    }}
                  >
                    <Plus className="size-4" /> Create peer group
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
                    "Peer group",
                    "Remote AS",
                    "Families",
                    "Transport",
                    "Password",
                    "Used by",
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
                {groups.map((group) => {
                  const used = usage(group);
                  return (
                    <tr
                      key={group.name}
                      className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/25"
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-background text-muted-foreground">
                            <Tags className="size-3.5" />
                          </span>
                          <div className="min-w-0">
                            <p className="font-mono text-[12px] font-medium">
                              {group.name}
                            </p>
                            <p className="max-w-[240px] truncate text-[10px] text-muted-foreground">
                              {group.description ?? "No description"}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 font-mono text-[11px]">
                        {group.remote_as ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        <AddressFamilyBadges
                          families={group.address_families}
                        />
                      </td>
                      <td className="px-4 py-3">
                        <p className="font-mono text-[10px]">
                          {group.update_source ?? "default source"}
                        </p>
                        <p className="text-[9px] text-muted-foreground">
                          {group.ebgp_multihop
                            ? `multihop ${group.ebgp_multihop}`
                            : "direct eBGP"}
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        {group.password_configured ? (
                          <Badge variant="success" className="text-[9px]">
                            configured
                          </Badge>
                        ) : (
                          <span className="text-[10px] text-muted-foreground">
                            none
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className="flex items-center gap-1.5 text-[11px]">
                          <Users className="size-3 text-muted-foreground" />
                          {used} {used === 1 ? "neighbor" : "neighbors"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        {writer && (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                aria-label={`Actions for ${group.name}`}
                              >
                                <MoreHorizontal className="size-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-48">
                              <DropdownMenuItem
                                onSelect={() => {
                                  setEditing(group);
                                  setOpen(true);
                                }}
                              >
                                <Pencil /> Edit peer group
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                variant="destructive"
                                onSelect={() => setDeleteTarget(group)}
                              >
                                <Trash2 /> Delete peer group
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {open && (
        <PeerGroupFormDialog
          key={editing?.name ?? "create"}
          open={open}
          onOpenChange={setOpen}
          routerId={router.id}
          group={editing}
        />
      )}

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(next) => {
          if (!next && !deleteGroup.isPending) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete peer group {deleteTarget?.name}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              {deleteTarget && usage(deleteTarget) > 0
                ? `${usage(deleteTarget)} neighbor(s) reference this group. Reassign them before deleting to avoid a broken configuration. `
                : ""}
              The peer group will be removed from the device. This cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteGroup.isPending && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Spinner /> Deleting peer group…
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteGroup.isPending}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleteGroup.isPending}
              onClick={(event) => {
                event.preventDefault();
                void handleDelete();
              }}
            >
              <Trash2 className="size-4" /> Delete group
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

export default function PeerGroupsPage() {
  return (
    <BgpRouterBoundary>
      {(router) => <GroupsContent router={router} />}
    </BgpRouterBoundary>
  );
}
