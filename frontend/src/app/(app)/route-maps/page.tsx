"use client";

import * as React from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  Filter,
  ListFilter,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Route,
  Search,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth";
import { errorMessage } from "@/lib/api";
import {
  queryKeys,
  useDeleteRouteMapRule,
  usePrefixLists,
  useRouteMaps,
} from "@/lib/queries";
import { canWrite } from "@/lib/roles";
import type { RouteMap, RouteMapRule, Router } from "@/lib/types";
import { cn } from "@/lib/utils";
import { RouterBoundary } from "@/components/router-boundary";
import {
  MatchSummaryCell,
  RuleActionBadge,
  RuleBehavior,
  SetSummaryCell,
  ruleCounts,
} from "@/components/route-maps/summary";
import { RuleFormDialog } from "@/components/route-maps/rule-form-dialog";
import {
  RouteMapCreateDialog,
  RouteMapDeleteDialog,
  RouteMapEditDialog,
} from "@/components/route-maps/route-map-dialogs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  EmptyState,
  ErrorPanel,
  InlineAlert,
  PageHeader,
  Spinner,
  TableSkeleton,
} from "@/components/states";

const MAP_PARAM = "map";

function readMapParam(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(MAP_PARAM);
}

function writeMapParam(name: string | null) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (name) {
    url.searchParams.set(MAP_PARAM, name);
  } else {
    url.searchParams.delete(MAP_PARAM);
  }
  window.history.replaceState(window.history.state, "", url.toString());
}

function sortByName(items: RouteMap[]): RouteMap[] {
  return [...items].sort((a, b) => a.name.localeCompare(b.name));
}

function sortRules(rules: RouteMapRule[]): RouteMapRule[] {
  return [...rules].sort((a, b) => a.number - b.number);
}

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

function CountChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "permit" | "deny";
}) {
  return (
    <span
      className={cn(
        "font-mono text-[9px]",
        tone === "permit" && "text-emerald-600 dark:text-emerald-300",
        tone === "deny" && "text-destructive",
        !tone && "text-muted-foreground",
      )}
    >
      {value} {label}
    </span>
  );
}

function RouteMapListItem({
  routeMap,
  selected,
  onSelect,
}: {
  routeMap: RouteMap;
  selected: boolean;
  onSelect: () => void;
}) {
  const counts = ruleCounts(routeMap.rules);
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        className={cn(
          "w-full border-l-2 px-3 py-2.5 text-left transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
          selected
            ? "border-primary bg-primary/[0.06]"
            : "border-transparent hover:bg-muted/40",
        )}
      >
        <div className="flex items-start justify-between gap-2">
          <span className="font-mono text-[12px] font-medium break-all">
            {routeMap.name}
          </span>
          {routeMap.in_use ? (
            <Badge variant="success" className="text-[8px]">
              in use
            </Badge>
          ) : (
            <Badge variant="muted" className="text-[8px]">
              unused
            </Badge>
          )}
        </div>
        <p className="mt-0.5 line-clamp-2 text-[10px] leading-relaxed text-muted-foreground">
          {routeMap.description || "No description"}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <CountChip label="rules" value={counts.total} />
          <CountChip label="permit" value={counts.permit} tone="permit" />
          <CountChip label="deny" value={counts.deny} tone="deny" />
        </div>
      </button>
    </li>
  );
}

function RulesTable({
  routeMap,
  writer,
  onEdit,
  onDelete,
}: {
  routeMap: RouteMap;
  writer: boolean;
  onEdit: (rule: RouteMapRule) => void;
  onDelete: (rule: RouteMapRule) => void;
}) {
  const rules = sortRules(routeMap.rules);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b border-border/60 bg-muted/25">
            {["Rule", "Action", "Match", "Set actions", ""].map((label, index) => (
              <th
                key={label || index}
                className="px-3 py-2.5 text-left text-[10px] font-semibold tracking-[0.12em] whitespace-nowrap text-muted-foreground uppercase"
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rules.map((rule) => (
            <tr
              key={rule.number}
              className="border-b border-border/60 align-top transition-colors last:border-0 hover:bg-muted/25"
            >
              <td className="max-w-[170px] px-3 py-3">
                <p className="font-mono text-[12px] font-medium">{rule.number}</p>
                <p className="mt-0.5 text-[10px] leading-relaxed break-words text-muted-foreground">
                  {rule.description || "No description"}
                </p>
              </td>
              <td className="px-3 py-3">
                <RuleActionBadge action={rule.action} />
                <div className="mt-1.5">
                  <RuleBehavior rule={rule} />
                </div>
              </td>
              <td className="px-3 py-3">
                <MatchSummaryCell match={rule.match} />
              </td>
              <td className="px-3 py-3">
                <SetSummaryCell set={rule.set} />
              </td>
              <td className="px-3 py-3 text-right">
                {writer ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Actions for rule ${rule.number}`}
                      >
                        <MoreHorizontal className="size-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-40">
                      <DropdownMenuItem onSelect={() => onEdit(rule)}>
                        <Pencil /> Edit rule
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        variant="destructive"
                        onSelect={() => onDelete(rule)}
                      >
                        <Trash2 /> Delete rule
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : (
                  <span className="text-[11px] text-muted-foreground">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RouteMapsContent({ router }: { router: Router }) {
  const { user } = useAuth();
  const writer = canWrite(user?.role);
  const queryClient = useQueryClient();
  const routeMapsQuery = useRouteMaps(router.id);
  // Existing prefix-list names feed the route-map match datalists.
  const prefixListsQuery = usePrefixLists(router.id);

  const [search, setSearch] = React.useState("");
  const [selectedName, setSelectedName] = React.useState<string | null>(null);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [editOpen, setEditOpen] = React.useState(false);
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const [ruleFormOpen, setRuleFormOpen] = React.useState(false);
  const [editingRule, setEditingRule] = React.useState<RouteMapRule | null>(
    null,
  );
  const [ruleDeleteTarget, setRuleDeleteTarget] =
    React.useState<RouteMapRule | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);

  const deleteRule = useDeleteRouteMapRule(router.id);

  const routeMaps = React.useMemo(
    () => sortByName(routeMapsQuery.data?.items ?? []),
    [routeMapsQuery.data],
  );

  const prefixListNames = React.useMemo(() => {
    const items = prefixListsQuery.data?.items ?? [];
    return {
      ipv4: items
        .filter((item) => item.family === "ipv4")
        .map((item) => item.name),
      ipv6: items
        .filter((item) => item.family === "ipv6")
        .map((item) => item.name),
    };
  }, [prefixListsQuery.data]);

  // Reconcile the ?map= selection: explicit selection > query string > first.
  // Keeps the URL shareable without introducing a dynamic route segment.
  React.useEffect(() => {
    if (routeMaps.length === 0) {
      if (selectedName !== null) setSelectedName(null);
      writeMapParam(null);
      return;
    }
    const param = readMapParam();
    const valid = (name: string | null) =>
      !!name && routeMaps.some((map) => map.name === name);

    const next = valid(selectedName)
      ? (selectedName as string)
      : valid(param)
        ? (param as string)
        : routeMaps[0].name;

    if (next !== selectedName) setSelectedName(next);
    if (next !== param) writeMapParam(next);
  }, [routeMaps, selectedName]);

  // Browser back/forward changes ?map without a Next navigation.
  React.useEffect(() => {
    const onPopState = () => {
      const param = readMapParam();
      if (param) setSelectedName(param);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const selectedMap =
    routeMaps.find((map) => map.name === selectedName) ?? routeMaps[0] ?? null;

  const selectMap = (name: string) => {
    setSelectedName(name);
    writeMapParam(name);
  };

  const filtered = React.useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return routeMaps;
    return routeMaps.filter((map) =>
      [map.name, map.description ?? ""]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [routeMaps, search]);

  const refresh = async () => {
    setRefreshing(true);
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.routeMaps(router.id),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.bgpConfig(router.id),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.prefixLists(router.id),
      }),
    ]);
    setRefreshing(false);
    toast.info("Route maps refreshed");
  };

  const handleDeleteRule = async () => {
    if (!ruleDeleteTarget || !selectedMap) return;
    try {
      await deleteRule.mutateAsync({
        name: selectedMap.name,
        number: ruleDeleteTarget.number,
      });
      toast.success(`Rule ${ruleDeleteTarget.number} deleted`, {
        description: `${selectedMap.name} saved on the router.`,
      });
      setRuleDeleteTarget(null);
    } catch (error) {
      toast.error("Could not delete rule", {
        description: errorMessage(error),
      });
    }
  };

  const heading = (
    <PageHeader
      title="Route maps"
      badge={<RouterBadge name={router.name} />}
      description="Policy rules for BGP import/export filtering, OSPF redistribution and path-attribute changes. Select a route map to inspect or edit its rules."
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
          <Button
            variant="outline"
            size="sm"
            asChild
          >
            <Link href="/bgp/neighbors/">
              <ShieldAlert className="size-3.5" /> BGP policy
            </Link>
          </Button>
          {writer && (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="size-4" /> New route map
            </Button>
          )}
        </>
      }
    />
  );

  if (routeMapsQuery.isLoading) {
    return (
      <>
        {heading}
        <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
          <Card className="gap-0 overflow-hidden py-0">
            <div className="space-y-2 border-b border-border/70 p-3">
              <Skeleton className="h-8 w-full" />
            </div>
            <div className="space-y-3 p-3">
              {Array.from({ length: 5 }).map((_, index) => (
                <div key={index} className="space-y-1.5">
                  <Skeleton className="h-3.5 w-28" />
                  <Skeleton className="h-2.5 w-40" />
                </div>
              ))}
            </div>
          </Card>
          <TableSkeleton rows={6} />
        </div>
      </>
    );
  }

  if (routeMapsQuery.isError && !routeMapsQuery.data) {
    return (
      <>
        {heading}
        <ErrorPanel
          title={`Could not read route maps from ${router.name}`}
          error={routeMapsQuery.error}
          onRetry={() => void routeMapsQuery.refetch()}
        />
      </>
    );
  }

  if (routeMaps.length === 0) {
    return (
      <>
        {heading}
        {!writer && (
          <InlineAlert tone="info" title="Read-only access">
            Viewers can inspect route maps and their rules. Creating, editing
            and deleting route maps requires the operator or administrator
            role.
          </InlineAlert>
        )}
        <EmptyState
          icon={Route}
          title="No route maps configured"
          description={
            <>
              Route maps hold ordered permit/deny rules that can match prefixes,
              AS paths, communities and other attributes. BGP neighbors and peer
              groups reference them as import/export policy.
            </>
          }
          action={
            writer ? (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="size-4" /> Create route map
              </Button>
            ) : (
              <span className="text-xs text-muted-foreground">
                An operator or administrator can create route maps.
              </span>
            )
          }
        />
        <RouteMapCreateDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          routerId={router.id}
        />
      </>
    );
  }

  const selectedCounts = selectedMap ? ruleCounts(selectedMap.rules) : null;

  return (
    <>
      {heading}

      {!writer && (
        <InlineAlert tone="info" title="Read-only access">
          Viewers can inspect route maps and their rules. Creating, editing and
          deleting route maps requires the operator or administrator role.
        </InlineAlert>
      )}

      {routeMapsQuery.isError && (
        <InlineAlert tone="warning" title="Showing cached route maps">
          The latest refresh failed: {errorMessage(routeMapsQuery.error)}
        </InlineAlert>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        <Card className="gap-0 overflow-hidden border-border/60 py-0 lg:sticky lg:top-[6rem] lg:border-r">
          <div className="space-y-2 border-b border-border/70 p-3">
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search name or description…"
                className="h-8 pl-8 text-xs"
                aria-label="Search route maps"
              />
            </div>
            <div className="flex items-center justify-between text-[10px] text-muted-foreground">
              <span className="font-mono">
                {filtered.length}/{routeMaps.length} route maps
              </span>
              <span className="font-mono">
                {routeMaps.filter((map) => map.in_use).length} in use
              </span>
            </div>
          </div>

          {filtered.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <Filter className="mx-auto size-5 text-muted-foreground" />
              <p className="mt-2 text-sm font-medium">No route maps match</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Adjust the search to see all {routeMaps.length} route maps.
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
            <ul className="max-h-[360px] divide-y divide-border/50 overflow-y-auto lg:max-h-[560px]">
              {filtered.map((routeMap) => (
                <RouteMapListItem
                  key={routeMap.name}
                  routeMap={routeMap}
                  selected={selectedMap?.name === routeMap.name}
                  onSelect={() => selectMap(routeMap.name)}
                />
              ))}
            </ul>
          )}

          <div className="border-t border-border/70 p-3">
            <p className="text-[10px] leading-relaxed text-muted-foreground">
              Names link BGP policy to this table. The selected route map is
              stored in the URL as{" "}
              <code className="font-mono">?map=&lt;name&gt;</code> so links are
              shareable.
            </p>
          </div>
        </Card>

        <div className="min-w-0 space-y-4">
          {selectedMap && selectedCounts ? (
            <>
              <Card className="gap-0 overflow-hidden border-t border-border/70 py-0">
                <div className="flex flex-col gap-3 border-b border-border/70 p-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="font-mono text-base font-semibold break-all">
                        {selectedMap.name}
                      </h2>
                      {selectedMap.in_use ? (
                        <Badge variant="success" className="text-[9px]">
                          in use
                        </Badge>
                      ) : (
                        <Badge variant="muted" className="text-[9px]">
                          unused
                        </Badge>
                      )}
                      <Badge
                        variant="outline"
                        className="font-mono text-[9px]"
                      >
                        {selectedCounts.total} rules
                      </Badge>
                      <Badge
                        variant="outline"
                        className="border-emerald-500/25 font-mono text-[9px] text-emerald-600 dark:text-emerald-300"
                      >
                        {selectedCounts.permit} permit
                      </Badge>
                      <Badge
                        variant="outline"
                        className="border-destructive/25 font-mono text-[9px] text-destructive"
                      >
                        {selectedCounts.deny} deny
                      </Badge>
                    </div>
                    <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-muted-foreground">
                      {selectedMap.description || "No description."}
                    </p>

                    {selectedMap.in_use && selectedMap.used_by.length > 0 && (
                      <Collapsible>
                        <CollapsibleTrigger asChild>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="mt-1.5 h-6 gap-1 px-1.5 text-[10px] text-muted-foreground"
                          >
                            Referenced by {selectedMap.used_by.length}{" "}
                            {selectedMap.used_by.length === 1 ? "entry" : "entries"}
                            <ChevronDown className="size-3" />
                          </Button>
                        </CollapsibleTrigger>
                        <CollapsibleContent>
                          <ul className="mt-1 space-y-1 rounded-md border border-border/60 bg-muted/25 px-2.5 py-2 font-mono text-[10px] break-all text-muted-foreground">
                            {selectedMap.used_by.map((reference) => (
                              <li key={reference}>{reference}</li>
                            ))}
                          </ul>
                        </CollapsibleContent>
                      </Collapsible>
                    )}
                  </div>

                  {writer && (
                    <div className="flex shrink-0 flex-wrap items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setEditOpen(true)}
                      >
                        <Pencil className="size-3.5" /> Edit
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="text-destructive hover:text-destructive"
                        onClick={() => setDeleteOpen(true)}
                      >
                        <Trash2 className="size-3.5" /> Delete
                      </Button>
                      <Button
                        size="sm"
                        onClick={() => {
                          setEditingRule(null);
                          setRuleFormOpen(true);
                        }}
                      >
                        <Plus className="size-4" /> Add rule
                      </Button>
                    </div>
                  )}
                </div>

                {selectedMap.rules.length === 0 ? (
                  <div className="p-5">
                    <EmptyState
                      compact
                      icon={ListFilter}
                      title="No rules in this route map"
                      description="Without rules the route map matches nothing. Add a rule with a match condition and a permit or deny action."
                      action={
                        writer ? (
                          <Button
                            size="sm"
                            onClick={() => {
                              setEditingRule(null);
                              setRuleFormOpen(true);
                            }}
                          >
                            <Plus className="size-4" /> Add first rule
                          </Button>
                        ) : undefined
                      }
                    />
                  </div>
                ) : (
                  <RulesTable
                    routeMap={selectedMap}
                    writer={writer}
                    onEdit={(rule) => {
                      setEditingRule(rule);
                      setRuleFormOpen(true);
                    }}
                    onDelete={(rule) => setRuleDeleteTarget(rule)}
                  />
                )}
              </Card>

              <div className="grid gap-3 border-t border-border/70 pt-3 sm:grid-cols-2">
                <Link
                  href="/bgp/neighbors/"
                  className="group flex items-center gap-2.5 py-1 transition-colors hover:text-primary"
                >
                  <span className="text-primary">
                    <ShieldAlert className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[12px] font-medium">
                      Apply as BGP import/export policy
                    </span>
                    <span className="block text-[10px] text-muted-foreground">
                      Neighbor and peer-group address-family settings
                    </span>
                  </span>
                </Link>
                <Link
                  href="/bgp/"
                  className="group flex items-center gap-2.5 py-1 transition-colors hover:text-primary"
                >
                  <span className="text-primary">
                    <Route className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[12px] font-medium">
                      BGP overview
                    </span>
                    <span className="block text-[10px] text-muted-foreground">
                      Session health and peer policy summary
                    </span>
                  </span>
                </Link>
              </div>
            </>
          ) : (
            <Card className="p-6 text-center text-sm text-muted-foreground">
              Select a route map to inspect its rules.
            </Card>
          )}
        </div>
      </div>

      <RouteMapCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        routerId={router.id}
      />
      <RouteMapEditDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        routerId={router.id}
        routeMap={selectedMap}
      />
      <RouteMapDeleteDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        routerId={router.id}
        routeMap={selectedMap}
        onDeleted={() => {
          const remaining = routeMaps.filter(
            (map) => map.name !== selectedMap?.name,
          );
          const next = remaining[0]?.name ?? null;
          setSelectedName(next);
          writeMapParam(next);
        }}
      />
      {selectedMap && (
        <RuleFormDialog
          key={`${selectedMap.name}:${editingRule?.number ?? "new"}`}
          open={ruleFormOpen}
          onOpenChange={(open) => {
            setRuleFormOpen(open);
            if (!open) setEditingRule(null);
          }}
          routerId={router.id}
          routeMap={selectedMap}
          rule={editingRule}
          prefixListNames={prefixListNames}
        />
      )}

      <AlertDialog
        open={!!ruleDeleteTarget}
        onOpenChange={(open) => {
          if (!open && !deleteRule.isPending) setRuleDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete rule {ruleDeleteTarget?.number}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              The rule will be removed from{" "}
              <span className="font-mono">{selectedMap?.name}</span>. BGP policy
              evaluation changes immediately after the commit.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteRule.isPending && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Spinner /> Deleting rule…
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteRule.isPending}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleteRule.isPending}
              onClick={(event) => {
                event.preventDefault();
                void handleDeleteRule();
              }}
            >
              <Trash2 className="size-4" /> Delete rule
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

export default function RouteMapsPage() {
  return (
    <RouterBoundary emptyDescription="Add a VyOS device before managing route maps.">
      {(router) => <RouteMapsContent router={router} />}
    </RouterBoundary>
  );
}
