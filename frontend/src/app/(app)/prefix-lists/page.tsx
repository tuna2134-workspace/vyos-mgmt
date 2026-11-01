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
  useDeletePrefixListRule,
  usePrefixLists,
} from "@/lib/queries";
import { canWrite } from "@/lib/roles";
import type {
  PrefixList,
  PrefixListFamily,
  PrefixListRule,
  Router,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { RouterBoundary } from "@/components/router-boundary";
import { RuleActionBadge } from "@/components/route-maps/summary";
import {
  FAMILY_LABEL,
  FAMILY_VYOS_PATH,
  PrefixListFamilyBadge,
  boundsLabel,
  prefixListRuleCounts,
  sortPrefixListRules,
  sortPrefixLists,
} from "@/components/prefix-lists/shared";
import {
  PrefixListCreateDialog,
  PrefixListDeleteDialog,
  PrefixListEditDialog,
} from "@/components/prefix-lists/prefix-list-dialogs";
import { PrefixListRuleFormDialog } from "@/components/prefix-lists/rule-form-dialog";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  EmptyState,
  ErrorPanel,
  InlineAlert,
  PageHeader,
  Spinner,
  TableSkeleton,
} from "@/components/states";

const FAMILY_PARAM = "family";
const LIST_PARAM = "list";
const FAMILIES: PrefixListFamily[] = ["ipv4", "ipv6"];

function isFamily(value: string | null): value is PrefixListFamily {
  return value === "ipv4" || value === "ipv6";
}

function readParams(): {
  family: PrefixListFamily | null;
  list: string | null;
} {
  if (typeof window === "undefined") return { family: null, list: null };
  const params = new URLSearchParams(window.location.search);
  const family = params.get(FAMILY_PARAM);
  return {
    family: isFamily(family) ? family : null,
    list: params.get(LIST_PARAM),
  };
}

function writeParams(next: {
  family?: PrefixListFamily | null;
  list?: string | null;
}) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if ("family" in next) {
    if (next.family) url.searchParams.set(FAMILY_PARAM, next.family);
    else url.searchParams.delete(FAMILY_PARAM);
  }
  if ("list" in next) {
    if (next.list) url.searchParams.set(LIST_PARAM, next.list);
    else url.searchParams.delete(LIST_PARAM);
  }
  window.history.replaceState(window.history.state, "", url.toString());
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

function PrefixListItem({
  prefixList,
  selected,
  onSelect,
}: {
  prefixList: PrefixList;
  selected: boolean;
  onSelect: () => void;
}) {
  const counts = prefixListRuleCounts(prefixList.rules);
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
            {prefixList.name}
          </span>
          {prefixList.in_use ? (
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
          {prefixList.description || "No description"}
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
  prefixList,
  writer,
  onEdit,
  onDelete,
}: {
  prefixList: PrefixList;
  writer: boolean;
  onEdit: (rule: PrefixListRule) => void;
  onDelete: (rule: PrefixListRule) => void;
}) {
  const rules = sortPrefixListRules(prefixList.rules);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-border/60 bg-muted/25">
            {["Seq", "Action", "Prefix", "ge / le", "Description", ""].map(
              (label, index) => (
                <th
                  key={label || index}
                  className="px-3 py-2.5 text-left text-[10px] font-semibold tracking-[0.12em] whitespace-nowrap text-muted-foreground uppercase"
                >
                  {label}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {rules.map((rule) => (
            <tr
              key={rule.number}
              className="border-b border-border/60 align-top transition-colors last:border-0 hover:bg-muted/25"
            >
              <td className="px-3 py-3 font-mono text-[12px] font-medium whitespace-nowrap">
                {rule.number}
              </td>
              <td className="px-3 py-3">
                <RuleActionBadge action={rule.action} />
              </td>
              <td className="px-3 py-3 font-mono text-[12px] break-all">
                {rule.prefix}
              </td>
              <td className="px-3 py-3 whitespace-nowrap">
                <span
                  className={cn(
                    "font-mono text-[11px]",
                    rule.ge === null && rule.le === null
                      ? "text-muted-foreground"
                      : "text-foreground",
                  )}
                >
                  {boundsLabel(rule)}
                </span>
              </td>
              <td className="max-w-[220px] px-3 py-3 text-[11px] leading-relaxed text-muted-foreground">
                {rule.description || "—"}
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

function PrefixListsContent({ router }: { router: Router }) {
  const { user } = useAuth();
  const writer = canWrite(user?.role);
  const queryClient = useQueryClient();
  const prefixListsQuery = usePrefixLists(router.id);

  // Read ?family= in the initialiser so a deep link such as
  // `?family=ipv6&list=X` reconciles against the right family on the first
  // pass. The page only paints the tabs after the query resolves, so this
  // cannot cause a hydration mismatch with the prerendered shell.
  const [family, setFamily] = React.useState<PrefixListFamily>(
    () => readParams().family ?? "ipv4",
  );
  const [selectedName, setSelectedName] = React.useState<string | null>(null);
  const [search, setSearch] = React.useState("");
  const [createOpen, setCreateOpen] = React.useState(false);
  const [editOpen, setEditOpen] = React.useState(false);
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const [ruleFormOpen, setRuleFormOpen] = React.useState(false);
  const [editingRule, setEditingRule] = React.useState<PrefixListRule | null>(
    null,
  );
  const [ruleDeleteTarget, setRuleDeleteTarget] =
    React.useState<PrefixListRule | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);

  const deleteRule = useDeletePrefixListRule(router.id);

  const prefixLists = React.useMemo(
    () => sortPrefixLists(prefixListsQuery.data?.items ?? []),
    [prefixListsQuery.data],
  );

  const byFamily = React.useMemo<Record<PrefixListFamily, PrefixList[]>>(
    () => ({
      ipv4: prefixLists.filter((item) => item.family === "ipv4"),
      ipv6: prefixLists.filter((item) => item.family === "ipv6"),
    }),
    [prefixLists],
  );

  const familyLists = byFamily[family];

  // Write the default family so links stay shareable.
  React.useEffect(() => {
    if (!readParams().family) writeParams({ family });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reconcile ?list=: explicit selection > query string > first in the family.
  React.useEffect(() => {
    if (familyLists.length === 0) {
      if (selectedName !== null) setSelectedName(null);
      if (readParams().list !== null) writeParams({ list: null });
      return;
    }

    const param = readParams().list;
    const valid = (name: string | null) =>
      !!name && familyLists.some((item) => item.name === name);

    const next = valid(selectedName)
      ? (selectedName as string)
      : valid(param)
        ? (param as string)
        : familyLists[0].name;

    if (next !== selectedName) setSelectedName(next);
    if (next !== param) writeParams({ list: next });
  }, [familyLists, selectedName]);

  // Browser back/forward changes ?family / ?list without a Next navigation.
  React.useEffect(() => {
    const onPopState = () => {
      const param = readParams();
      if (param.family) setFamily(param.family);
      setSelectedName(param.list);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const selectedList =
    familyLists.find((item) => item.name === selectedName) ??
    familyLists[0] ??
    null;

  const selectList = (name: string) => {
    setSelectedName(name);
    writeParams({ list: name });
  };

  const selectFamily = (next: PrefixListFamily) => {
    if (next === family) return;
    setFamily(next);
    writeParams({ family: next });
  };

  // A list created for the other family would otherwise be invisible.
  const revealList = (created: PrefixList) => {
    setFamily(created.family);
    setSelectedName(created.name);
    writeParams({ family: created.family, list: created.name });
  };

  const filtered = React.useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return familyLists;
    return familyLists.filter((item) =>
      [item.name, item.description ?? ""]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [familyLists, search]);

  const refresh = async () => {
    setRefreshing(true);
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.prefixLists(router.id),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.routeMaps(router.id),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.bgpConfig(router.id),
      }),
    ]);
    setRefreshing(false);
    toast.info("Prefix lists refreshed");
  };

  const handleDeleteRule = async () => {
    if (!ruleDeleteTarget || !selectedList) return;
    try {
      await deleteRule.mutateAsync({
        family: selectedList.family,
        name: selectedList.name,
        number: ruleDeleteTarget.number,
      });
      toast.success(`Rule ${ruleDeleteTarget.number} deleted`, {
        description: `${selectedList.name} saved on the router.`,
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
      title="Prefix lists"
      badge={<RouterBadge name={router.name} />}
      description="IPv4 and IPv6 prefix-list policy objects used by route-map match conditions and BGP prefix filters. Select a list to inspect or edit its permit/deny rules."
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
          <Button variant="outline" size="sm" asChild>
            <Link href="/route-maps/">
              <Route className="size-3.5" /> Route maps
            </Link>
          </Button>
          {writer && (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="size-4" /> New prefix list
            </Button>
          )}
        </>
      }
    />
  );

  const readOnlyBanner = !writer && (
    <InlineAlert tone="info" title="Read-only access">
      Viewers can inspect prefix lists and their rules. Creating, editing and
      deleting prefix lists requires the operator or administrator role.
    </InlineAlert>
  );

  if (prefixListsQuery.isLoading) {
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

  if (prefixListsQuery.isError && !prefixListsQuery.data) {
    return (
      <>
        {heading}
        <ErrorPanel
          title={`Could not read prefix lists from ${router.name}`}
          error={prefixListsQuery.error}
          onRetry={() => void prefixListsQuery.refetch()}
        />
      </>
    );
  }

  if (prefixLists.length === 0) {
    return (
      <>
        {heading}
        {readOnlyBanner}
        <EmptyState
          icon={ListFilter}
          title="No prefix lists configured"
          description={
            <>
              Prefix lists hold ordered permit/deny rules that match route
              prefixes. Route-map match conditions reference them by name, so
              create a list before wiring it into BGP import/export policy.
            </>
          }
          action={
            writer ? (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="size-4" /> Create prefix list
              </Button>
            ) : (
              <span className="text-xs text-muted-foreground">
                An operator or administrator can create prefix lists.
              </span>
            )
          }
        />
        <PrefixListCreateDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          routerId={router.id}
          family={family}
          onCreated={revealList}
        />
      </>
    );
  }

  const selectedCounts = selectedList
    ? prefixListRuleCounts(selectedList.rules)
    : null;

  return (
    <>
      {heading}

      {readOnlyBanner}

      {prefixListsQuery.isError && (
        <InlineAlert tone="warning" title="Showing cached prefix lists">
          The latest refresh failed: {errorMessage(prefixListsQuery.error)}
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
          aria-label="Prefix-list address family"
          className="grid w-full grid-cols-2 bg-muted/60 sm:w-fit"
        >
          {FAMILIES.map((value) => (
            <TabsTrigger key={value} value={value} className="gap-2 px-4">
              {FAMILY_LABEL[value]}
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
          {familyLists.length === 0 ? (
            <EmptyState
              icon={ListFilter}
              title={`No ${FAMILY_LABEL[family]} prefix lists`}
              description={
                <>
                  This router has no objects under{" "}
                  <code className="font-mono text-[11px]">
                    {FAMILY_VYOS_PATH[family]}
                  </code>
                  . {byFamily[family === "ipv4" ? "ipv6" : "ipv4"].length > 0
                    ? `Switch to the ${FAMILY_LABEL[family === "ipv4" ? "ipv6" : "ipv4"]} tab to see the lists that exist.`
                    : "Create one to start matching prefixes."}
                </>
              }
              action={
                writer ? (
                  <Button onClick={() => setCreateOpen(true)}>
                    <Plus className="size-4" /> Create {FAMILY_LABEL[family]}{" "}
                    prefix list
                  </Button>
                ) : (
                  <span className="text-xs text-muted-foreground">
                    An operator or administrator can create prefix lists.
                  </span>
                )
              }
            />
          ) : (
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
                      aria-label={`Search ${FAMILY_LABEL[family]} prefix lists`}
                    />
                  </div>
                  <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                    <span className="font-mono">
                      {filtered.length}/{familyLists.length}{" "}
                      {FAMILY_LABEL[family]} lists
                    </span>
                    <span className="font-mono">
                      {familyLists.filter((item) => item.in_use).length} in use
                    </span>
                  </div>
                </div>

                {filtered.length === 0 ? (
                  <div className="px-4 py-10 text-center">
                    <Filter className="mx-auto size-5 text-muted-foreground" />
                    <p className="mt-2 text-sm font-medium">
                      No prefix lists match
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Adjust the search to see all {familyLists.length}{" "}
                      {FAMILY_LABEL[family]} lists.
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
                    {filtered.map((item) => (
                      <PrefixListItem
                        key={`${item.family}:${item.name}`}
                        prefixList={item}
                        selected={selectedList?.name === item.name}
                        onSelect={() => selectList(item.name)}
                      />
                    ))}
                  </ul>
                )}

                <div className="border-t border-border/70 p-3">
                  <p className="text-[10px] leading-relaxed text-muted-foreground">
                    Names link route-map policy to this table. The selected list is
                    stored in the URL as{" "}
                    <code className="font-mono">?family=&lt;ipv4|ipv6&gt;</code> and{" "}
                    <code className="font-mono">?list=&lt;name&gt;</code> so links
                    are shareable.
                  </p>
                </div>
              </Card>

              <div className="min-w-0 space-y-4">
                {selectedList && selectedCounts ? (
                  <>
                    <Card className="gap-0 overflow-hidden border-t border-border/70 py-0">
                      <div className="flex flex-col gap-3 border-b border-border/70 p-4 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <h2 className="font-mono text-base font-semibold break-all">
                              {selectedList.name}
                            </h2>
                            <PrefixListFamilyBadge family={selectedList.family} />
                            {selectedList.in_use ? (
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
                            {selectedList.description || "No description."}
                          </p>
                          <p className="mt-1 font-mono text-[10px] text-muted-foreground/80">
                            {FAMILY_VYOS_PATH[selectedList.family]}
                          </p>

                          {selectedList.in_use &&
                            selectedList.used_by.length > 0 && (
                              <Collapsible>
                                <CollapsibleTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="mt-1.5 h-6 gap-1 px-1.5 text-[10px] text-muted-foreground"
                                  >
                                    Referenced by {selectedList.used_by.length}{" "}
                                    {selectedList.used_by.length === 1
                                      ? "entry"
                                      : "entries"}
                                    <ChevronDown className="size-3" />
                                  </Button>
                                </CollapsibleTrigger>
                                <CollapsibleContent>
                                  <ul className="mt-1 space-y-1 rounded-md border border-border/60 bg-muted/25 px-2.5 py-2 font-mono text-[10px] break-all text-muted-foreground">
                                    {selectedList.used_by.map((reference) => (
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

                      {selectedList.rules.length === 0 ? (
                        <div className="p-5">
                          <EmptyState
                            compact
                            icon={ListFilter}
                            title="No rules in this prefix list"
                            description={
                              <>
                                An empty prefix list matches nothing. Add a permit or
                                deny rule with a {FAMILY_LABEL[selectedList.family]}{" "}
                                prefix to start filtering.
                              </>
                            }
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
                          prefixList={selectedList}
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
                        href="/route-maps/"
                        className="group flex items-center gap-2.5 py-1 transition-colors hover:text-primary"
                      >
                        <span className="text-primary">
                          <Route className="size-4" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-[12px] font-medium">
                            Use in a route-map match
                          </span>
                          <span className="block text-[10px] text-muted-foreground">
                            New rules offer these names as suggestions
                          </span>
                        </span>
                      </Link>
                      <Link
                        href="/bgp/neighbors/"
                        className="group flex items-center gap-2.5 py-1 transition-colors hover:text-primary"
                      >
                        <span className="text-primary">
                          <ShieldAlert className="size-4" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-[12px] font-medium">
                            BGP import/export policy
                          </span>
                          <span className="block text-[10px] text-muted-foreground">
                            Neighbor and peer-group address-family settings
                          </span>
                        </span>
                      </Link>
                    </div>
                  </>
                ) : (
                  <Card className="p-6 text-center text-sm text-muted-foreground">
                    Select a prefix list to inspect its rules.
                  </Card>
                )}
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>

      <PrefixListCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        routerId={router.id}
        family={family}
        onCreated={revealList}
      />
      <PrefixListEditDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        routerId={router.id}
        prefixList={selectedList}
      />
      <PrefixListDeleteDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        routerId={router.id}
        prefixList={selectedList}
        onDeleted={(deleted) => {
          const remaining = byFamily[deleted.family].filter(
            (item) => item.name !== deleted.name,
          );
          const next = remaining[0]?.name ?? null;
          setSelectedName(next);
          writeParams({ family: deleted.family, list: next });
        }}
      />
      {selectedList && (
        <PrefixListRuleFormDialog
          key={`${selectedList.family}:${selectedList.name}:${editingRule?.number ?? "new"}`}
          open={ruleFormOpen}
          onOpenChange={(open) => {
            setRuleFormOpen(open);
            if (!open) setEditingRule(null);
          }}
          routerId={router.id}
          prefixList={selectedList}
          rule={editingRule}
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
              <span className="font-mono">{selectedList?.name}</span>. The
              device re-evaluates the policy on commit; route-map matches using
              this list are unaffected.
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

export default function PrefixListsPage() {
  return (
    <RouterBoundary emptyDescription="Add a VyOS device before managing prefix lists.">
      {(router) => <PrefixListsContent router={router} />}
    </RouterBoundary>
  );
}
