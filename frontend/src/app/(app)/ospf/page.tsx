"use client";

import * as React from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeftRight,
  Cable,
  Map as MapIcon,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  RadioTower,
  Route,
  SlidersHorizontal,
  Trash2,
  Waypoints,
} from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth";
import { errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import {
  queryKeys,
  useDeleteOspfInterface,
  useOspfConfig,
  useOspfStatus,
  useRouteMaps,
} from "@/lib/queries";
import { canWrite } from "@/lib/roles";
import type {
  OspfArea,
  OspfConfig,
  OspfInterface,
  OspfRedistribute,
  OspfStatus,
  OspfVersion,
  Router,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { RouterBoundary } from "@/components/router-boundary";
import {
  AREA_TYPE_LABEL,
  AreaTypeBadge,
  InterfaceFlags,
  LOG_ADJACENCY_LABEL,
  MetricTypeCell,
  NETWORK_TYPES,
  NETWORK_TYPE_LABEL,
  OSPF_VERSIONS,
  OspfNeighborStateBadge,
  REDISTRIBUTE_SOURCES,
  VERSION_LABEL,
  VERSION_NEIGHBOR_COMMAND,
  VERSION_VYOS_PATH,
  sourceLabel,
} from "@/components/ospf/shared";
import { OspfAreaDeleteDialog, OspfAreaFormDialog } from "@/components/ospf/area-dialogs";
import { OspfInterfaceFormDialog } from "@/components/ospf/interface-form-dialog";
import {
  OspfRedistributeDeleteDialog,
  OspfRedistributeFormDialog,
} from "@/components/ospf/redistribute-dialogs";
import { OspfSettingsPanel } from "@/components/ospf/settings-panel";
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Stat, StatStrip } from "@/components/ui/stat";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  EmptyState,
  ErrorPanel,
  InlineAlert,
  PageHeader,
  Spinner,
  TableSkeleton,
} from "@/components/states";

/* -------------------------------------------------------------------------- */
/* URL state                                                                  */
/* -------------------------------------------------------------------------- */

const VERSION_PARAM = "version";
const TAB_PARAM = "tab";

const SECTION_TABS = [
  "overview",
  "interfaces",
  "areas",
  "redistribution",
  "settings",
] as const;

type SectionTab = (typeof SECTION_TABS)[number];

const SECTION_LABEL: Record<SectionTab, string> = {
  overview: "Overview",
  interfaces: "Interfaces",
  areas: "Areas",
  redistribution: "Redistribution",
  settings: "Settings",
};

function isVersion(value: string | null): value is OspfVersion {
  return value === "v2" || value === "v3";
}

function isSectionTab(value: string | null): value is SectionTab {
  return SECTION_TABS.includes(value as SectionTab);
}

function readParams(): {
  version: OspfVersion;
  tab: SectionTab;
  versionParam: string | null;
  tabParam: string | null;
} {
  if (typeof window === "undefined") {
    return { version: "v2", tab: "overview", versionParam: null, tabParam: null };
  }
  const params = new URLSearchParams(window.location.search);
  const versionParam = params.get(VERSION_PARAM);
  const tabParam = params.get(TAB_PARAM);
  return {
    version: isVersion(versionParam) ? versionParam : "v2",
    tab: isSectionTab(tabParam) ? tabParam : "overview",
    versionParam,
    tabParam,
  };
}

/**
 * Only `version` and `tab` are touched here; `?router=` is owned by
 * RouterProvider and must survive every tab switch and version change.
 */
function writeParams(next: { version?: OspfVersion; tab?: SectionTab }) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (next.version) url.searchParams.set(VERSION_PARAM, next.version);
  if (next.tab) url.searchParams.set(TAB_PARAM, next.tab);
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

function OperationalStateBadge({
  config,
  status,
  statusLoading,
}: {
  config: OspfConfig;
  status: OspfStatus | undefined;
  statusLoading: boolean;
}) {
  if (!config.configured) {
    return (
      <Badge variant="muted" className="gap-1.5">
        <span className="size-1.5 rounded-full bg-muted-foreground/60" />
        Not configured
      </Badge>
    );
  }

  if (status?.error) {
    return (
      <Badge variant="warning" className="gap-1.5">
        <span className="size-1.5 rounded-full bg-amber-500" />
        Daemon not running
      </Badge>
    );
  }

  if (statusLoading) {
    return (
      <Badge variant="outline" className="gap-1.5">
        <span className="size-1.5 animate-pulse rounded-full bg-primary" />
        Checking neighbors…
      </Badge>
    );
  }

  if (status) {
    if (status.total_neighbors === 0) {
      return (
        <Badge variant="muted" className="gap-1.5">
          <span className="size-1.5 rounded-full bg-muted-foreground/60" />
          No neighbors
        </Badge>
      );
    }
    const allFull = status.full_neighbors === status.total_neighbors;
    return (
      <Badge variant={allFull ? "success" : "warning"} className="gap-1.5">
        <span
          className={
            allFull
              ? "size-1.5 rounded-full bg-emerald-500"
              : "size-1.5 rounded-full bg-amber-500"
          }
        />
        {status.full_neighbors}/{status.total_neighbors} full
      </Badge>
    );
  }

  return <Badge variant="default">Configured</Badge>;
}

function SummaryRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border/50 py-2 text-xs last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="max-w-[62%] text-right font-mono text-[11px] break-words">
        {value}
      </span>
    </div>
  );
}

function TableActionMenu({
  label,
  onEdit,
  onDelete,
}: {
  label: string;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${label}`}>
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        <DropdownMenuItem onSelect={onEdit}>
          <Pencil /> Edit
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onSelect={onDelete}>
          <Trash2 /> Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function TableHead({ columns }: { columns: string[] }) {
  return (
    <thead>
      <tr className="border-b border-border/60 bg-muted/25">
        {columns.map((label, index) => (
          <th
            key={label || index}
            scope="col"
            className="px-3 py-2.5 text-left text-[10px] font-semibold tracking-[0.12em] whitespace-nowrap text-muted-foreground uppercase"
          >
            {label}
          </th>
        ))}
      </tr>
    </thead>
  );
}

function DefaultInformationValue(config: OspfConfig): string {
  if (!config.global.default_information_originate) return "Off";
  return config.global.default_information_always
    ? "Originate + always"
    : "Originate";
}

/* -------------------------------------------------------------------------- */
/* Page content                                                               */
/* -------------------------------------------------------------------------- */

function OspfContent({ router }: { router: Router }) {
  const { user } = useAuth();
  const writer = canWrite(user?.role);
  const queryClient = useQueryClient();

  // Read the query string in the initialiser so deep links such as
  // `/ospf/?router=…&version=v3&tab=areas` open on the right tab. The page
  // only paints content after the auth gate, so this cannot cause a hydration
  // mismatch with the prerendered shell.
  const [version, setVersion] = React.useState<OspfVersion>(
    () => readParams().version,
  );
  const [tab, setTab] = React.useState<SectionTab>(() => readParams().tab);

  const [refreshing, setRefreshing] = React.useState(false);
  const [interfaceDialogOpen, setInterfaceDialogOpen] = React.useState(false);
  const [editingInterface, setEditingInterface] =
    React.useState<OspfInterface | null>(null);
  const [areaDialogOpen, setAreaDialogOpen] = React.useState(false);
  const [editingArea, setEditingArea] = React.useState<OspfArea | null>(null);
  const [redistributeDialogOpen, setRedistributeDialogOpen] =
    React.useState(false);
  const [editingRedistribution, setEditingRedistribution] =
    React.useState<OspfRedistribute | null>(null);
  const [deleteInterface, setDeleteInterface] =
    React.useState<OspfInterface | null>(null);
  const [deleteArea, setDeleteArea] = React.useState<OspfArea | null>(null);
  const [deleteRedistribution, setDeleteRedistribution] =
    React.useState<OspfRedistribute | null>(null);

  const configQuery = useOspfConfig(router.id, version);
  const config = configQuery.data;

  // Neighbor state is only needed on the overview; polling stops everywhere
  // else so other tabs do not hit the device on a timer.
  const statusQuery = useOspfStatus(router.id, version, {
    enabled: tab === "overview" && (config?.configured ?? false),
    poll: tab === "overview" ? 15_000 : false,
  });
  const status = statusQuery.data;

  const routeMapsQuery = useRouteMaps(router.id, {
    enabled: tab === "redistribution",
  });
  const routeMapNames = React.useMemo(
    () =>
      [...(routeMapsQuery.data?.items ?? [])]
        .map((routeMap) => routeMap.name)
        .sort((a, b) => a.localeCompare(b)),
    [routeMapsQuery.data],
  );

  const deleteInterfaceMutation = useDeleteOspfInterface(router.id, version);

  // Persist the defaults so the URL is always shareable, then keep the tabs in
  // sync with browser back/forward.
  React.useEffect(() => {
    const params = readParams();
    if (params.versionParam === null) writeParams({ version });
    if (params.tabParam === null) writeParams({ tab });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    const onPopState = () => {
      const params = readParams();
      setVersion(params.version);
      setTab(params.tab);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const closeDialogs = React.useCallback(() => {
    setInterfaceDialogOpen(false);
    setEditingInterface(null);
    setAreaDialogOpen(false);
    setEditingArea(null);
    setRedistributeDialogOpen(false);
    setEditingRedistribution(null);
    // Confirmation targets belong to the previous version's payload; a delete
    // must never be retargeted at the other OSPF process.
    setDeleteInterface(null);
    setDeleteArea(null);
    setDeleteRedistribution(null);
  }, []);

  const selectVersion = (next: OspfVersion) => {
    if (next === version) return;
    closeDialogs();
    setVersion(next);
    writeParams({ version: next });
  };

  const selectTab = (next: SectionTab) => {
    if (next === tab) return;
    setTab(next);
    writeParams({ tab: next });
  };

  const refresh = async () => {
    setRefreshing(true);
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.ospfConfig(router.id, version),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.ospfStatus(router.id, version),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.routeMaps(router.id),
      }),
    ]);
    setRefreshing(false);
    toast.info("OSPF refreshed");
  };

  const handleDeleteInterface = async () => {
    if (!deleteInterface) return;
    try {
      await deleteInterfaceMutation.mutateAsync(deleteInterface.name);
      toast.success("OSPF interface removed", {
        description: `${deleteInterface.name} no longer runs ${VERSION_LABEL[version]}.`,
      });
      setDeleteInterface(null);
    } catch (error) {
      toast.error("Could not remove interface", {
        description: errorMessage(error),
      });
    }
  };

  const heading = (
    <PageHeader
      title="OSPF"
      badge={
        <>
          <RouterBadge name={router.name} />
          {config && (
            <OperationalStateBadge
              config={config}
              status={status}
              statusLoading={
                tab === "overview" &&
                config.configured &&
                statusQuery.isLoading
              }
            />
          )}
        </>
      }
      description="OSPFv2 (IPv4) and OSPFv3 (IPv6) routing: process settings, areas, interface activation, redistribution and live neighbor health."
      actions={
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
      }
    />
  );

  const versionSwitch = (
    <div className="flex flex-wrap items-center justify-between gap-2 border-y border-border/60 py-2">
      <div
        role="group"
        aria-label="OSPF version"
        className="inline-flex items-center rounded-lg bg-muted/60 p-[3px]"
      >
        {OSPF_VERSIONS.map((value) => {
          const active = value === version;
          return (
            <button
              key={value}
              type="button"
              aria-pressed={active}
              onClick={() => selectVersion(value)}
              className={cn(
                "inline-flex h-7 items-center gap-2 rounded-md border px-3 text-[12px] font-medium whitespace-nowrap transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                active
                  ? "border-border bg-background text-foreground shadow-sm"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              <span className="font-mono text-[10px] uppercase">{value}</span>
              {VERSION_LABEL[value]}
            </button>
          );
        })}
      </div>
      <p className="font-mono text-[10px] text-muted-foreground">
        {VERSION_VYOS_PATH[version]} · {VERSION_NEIGHBOR_COMMAND[version]}
      </p>
    </div>
  );

  if (configQuery.isLoading) {
    return (
      <>
        {heading}
        {versionSwitch}
        <TableSkeleton rows={6} />
      </>
    );
  }

  if (configQuery.isError && !config) {
    return (
      <>
        {heading}
        {versionSwitch}
        <ErrorPanel
          title={`Could not read ${VERSION_LABEL[version]} from ${router.name}`}
          error={configQuery.error}
          onRetry={() => void configQuery.refetch()}
        />
      </>
    );
  }

  if (!config) {
    return (
      <>
        {heading}
        {versionSwitch}
      </>
    );
  }

  const configured = config.configured;
  const areas = config.areas;
  const interfaces = config.interfaces;
  const redistributions = config.redistributions;
  const stubAreas = areas.filter((area) => area.area_type !== "normal").length;
  const passiveInterfaces = interfaces.filter(
    (ospfInterface) => ospfInterface.passive,
  ).length;
  const supportedSources = config.supported_redistribute_sources.length
    ? config.supported_redistribute_sources
    : REDISTRIBUTE_SOURCES[version];
  const supportedNetworkTypes = config.supported_network_types.length
    ? config.supported_network_types
    : NETWORK_TYPES[version];
  const usedSources = redistributions.map((entry) => entry.source);
  const unusedSources = supportedSources.filter(
    (source) => !usedSources.includes(source),
  );
  const canAddInterface = writer && areas.length > 0;
  const canAddRedistribution = writer && unusedSources.length > 0;

  const statusHint = !configured
    ? "OSPF is not configured"
    : status
      ? `${status.full_neighbors} full / ${status.total_neighbors} total · updated ${formatRelative(status.collected_at)}`
      : statusQuery.isError
        ? "Neighbor status unavailable"
        : "Full / total neighbors";

  const neighborCard = (
    <Card variant="surface" className="gap-0 overflow-hidden py-0">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/60 px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">Neighbors</h2>
          <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
            {VERSION_NEIGHBOR_COMMAND[version]} · polled every 15 seconds while
            this tab is open
            {status ? ` · collected ${formatRelative(status.collected_at)}` : ""}
          </p>
        </div>
        {status && (
          <Badge
            variant={
              status.full_neighbors === status.total_neighbors &&
              status.total_neighbors > 0
                ? "success"
                : "muted"
            }
            className="font-mono text-[9px]"
          >
            {status.full_neighbors}/{status.total_neighbors} full
          </Badge>
        )}
      </div>

      {status?.error && (
        <div className="px-4 py-3">
          <InlineAlert
            tone="warning"
            title="OSPF daemon is not running"
            action={
              <Button
                variant="outline"
                size="sm"
                onClick={() => void statusQuery.refetch()}
              >
                <RefreshCw className="size-3.5" /> Retry
              </Button>
            }
          >
            {status.error}
          </InlineAlert>
        </div>
      )}

      {statusQuery.isError && !status && (
        <div className="px-4 py-3">
          <InlineAlert
            tone="error"
            title="Could not read neighbor status"
            action={
              <Button
                variant="outline"
                size="sm"
                onClick={() => void statusQuery.refetch()}
              >
                <RefreshCw className="size-3.5" /> Retry
              </Button>
            }
          >
            {errorMessage(statusQuery.error)}
          </InlineAlert>
        </div>
      )}

      {statusQuery.isLoading && !status ? (
        <div className="flex items-center gap-2 px-4 py-6 text-xs text-muted-foreground">
          <Spinner /> Reading the neighbor table…
        </div>
      ) : status && status.neighbors.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-sm">
            <caption className="sr-only">
              OSPF neighbors for {VERSION_LABEL[version]} on {router.name}
            </caption>
            <TableHead
              columns={[
                "Neighbor ID",
                "State",
                "Interface",
                "Address",
                "Dead time",
              ]}
            />
            <tbody>
              {status.neighbors.map((neighbor) => (
                <tr
                  key={`${neighbor.neighbor_id}:${neighbor.interface ?? ""}`}
                  className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/25"
                >
                  <td className="px-3 py-3">
                    <p className="font-mono text-[12px] font-medium">
                      {neighbor.neighbor_id}
                    </p>
                    <p className="mt-0.5 font-mono text-[9px] text-muted-foreground">
                      {neighbor.priority === null
                        ? "priority —"
                        : `priority ${neighbor.priority}`}
                    </p>
                  </td>
                  <td className="px-3 py-3">
                    <OspfNeighborStateBadge
                      state={neighbor.state}
                      established={neighbor.established}
                    />
                  </td>
                  <td className="px-3 py-3 font-mono text-[11px]">
                    {neighbor.interface ?? "—"}
                  </td>
                  <td className="px-3 py-3 font-mono text-[11px]">
                    {neighbor.address ?? "—"}
                  </td>
                  <td className="px-3 py-3 font-mono text-[11px] whitespace-nowrap">
                    {neighbor.dead_time ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : statusQuery.isError || status?.error ? null : (
        <div className="p-4">
          <EmptyState
            compact
            icon={RadioTower}
            title="No OSPF neighbors"
            description={
              <>
                No adjacencies are formed in this version. Check that at least
                two interfaces are active in the same area, are not passive, and
                share a common subnet and hello/dead timers.
              </>
            }
            action={
              writer ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => selectTab("interfaces")}
                >
                  <Cable className="size-4" /> Review interfaces
                </Button>
              ) : undefined
            }
          />
        </div>
      )}
    </Card>
  );

  const overviewSection = (
    <div className="space-y-4">
      <StatStrip>
        <Stat
          label="Router ID"
          value={configured ? (config.global.router_id ?? "Not set") : "Not configured"}
          hint={configured ? VERSION_VYOS_PATH[version] : "Configure under Settings"}
          icon={Waypoints}
        />
        <Stat
          label="Areas"
          value={areas.length}
          hint={`${stubAreas} stub / NSSA`}
          icon={MapIcon}
        />
        <Stat
          label="Interfaces"
          value={interfaces.length}
          hint={`${passiveInterfaces} passive`}
          icon={Cable}
        />
        <Stat
          label="Neighbors"
          value={status ? `${status.full_neighbors}/${status.total_neighbors}` : "—"}
          hint={statusHint}
          icon={RadioTower}
          loading={
            configured &&
            tab === "overview" &&
            statusQuery.isLoading &&
            !status
          }
        />
      </StatStrip>

      {!configured ? (
        <EmptyState
          icon={Waypoints}
          title={`${VERSION_LABEL[version]} is not configured`}
          description={
            <>
              No {VERSION_LABEL[version]} process exists on{" "}
              <strong>{router.name}</strong>. Start with global settings (router
              ID, reference bandwidth, default-information), then create areas
              and activate interfaces. A global-only process is valid.
            </>
          }
          action={
            writer ? (
              <Button onClick={() => selectTab("settings")}>
                <SlidersHorizontal className="size-4" /> Open settings
              </Button>
            ) : (
              <span className="text-xs text-muted-foreground">
                An operator or administrator can configure OSPF.
              </span>
            )
          }
        />
      ) : (
        <>
          <div className="grid gap-x-10 border-t border-border/60 md:grid-cols-2">
            <div>
              <SummaryRow
                label="Router ID"
                value={config.global.router_id ?? "Not set"}
              />
              <SummaryRow
                label="Log adjacency"
                value={LOG_ADJACENCY_LABEL[config.global.log_adjacency_changes]}
              />
              <SummaryRow
                label="Auto-cost reference"
                value={
                  config.global.auto_cost_reference_bandwidth === null
                    ? "Device default"
                    : `${config.global.auto_cost_reference_bandwidth} Mbps`
                }
              />
            </div>
            <div>
              <SummaryRow
                label="Default information"
                value={DefaultInformationValue(config)}
              />
              <SummaryRow
                label="Distance (global)"
                value={config.global.distance_global ?? "Device default"}
              />
              <SummaryRow label="Version" value={VERSION_LABEL[version]} />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t border-border/60 pt-3">
            {writer && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => selectTab("settings")}
              >
                <SlidersHorizontal className="size-3.5" /> Edit global settings
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => selectTab("areas")}
            >
              <MapIcon className="size-3.5" /> Areas
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => selectTab("interfaces")}
            >
              <Cable className="size-3.5" /> Interfaces
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link href={`/route-maps/?router=${router.id}`}>
                <Route className="size-3.5" /> Route maps
              </Link>
            </Button>
          </div>

          {neighborCard}
        </>
      )}
    </div>
  );

  const interfacesSection = (
    <div className="space-y-4">
      {!configured && (
        <InlineAlert tone="info" title={`${VERSION_LABEL[version]} is not configured`}>
          Activating an interface creates{" "}
          <code className="font-mono text-[11px]">
            {VERSION_VYOS_PATH[version]}
          </code>{" "}
          on the device. An area must exist first.
        </InlineAlert>
      )}

      {writer && areas.length === 0 && (
        <InlineAlert
          tone="info"
          title="Create an area first"
          action={
            <Button variant="outline" size="sm" onClick={() => selectTab("areas")}>
              <MapIcon className="size-3.5" /> Areas
            </Button>
          }
        >
          Every OSPF interface must reference an existing area. Areas are the
          routing domain unit; create one (area 0 is the backbone) before
          activating interfaces.
        </InlineAlert>
      )}

      <Card variant="surface" className="gap-0 overflow-hidden py-0">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/60 px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">OSPF interfaces</h2>
            <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
              Interfaces activate OSPF. Unset numeric fields use the device
              default.
            </p>
          </div>
          {writer && (
            <Button
              size="sm"
              onClick={() => {
                setEditingInterface(null);
                setInterfaceDialogOpen(true);
              }}
              disabled={!canAddInterface}
              title={
                canAddInterface
                  ? undefined
                  : "Create an area before activating an interface"
              }
            >
              <Plus className="size-4" /> Add interface
            </Button>
          )}
        </div>

        {interfaces.length === 0 ? (
          <div className="p-4">
            <EmptyState
              compact
              icon={Cable}
              title="No OSPF interfaces"
              description={
                areas.length === 0
                  ? "Create an area, then activate the interfaces that should form adjacencies."
                  : "Activate at least one interface in an area to start forming adjacencies. Interfaces that should not peer can be marked passive."
              }
              action={
                writer ? (
                  areas.length === 0 ? (
                    <Button size="sm" onClick={() => selectTab("areas")}>
                      <MapIcon className="size-4" /> Create an area
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      onClick={() => {
                        setEditingInterface(null);
                        setInterfaceDialogOpen(true);
                      }}
                    >
                      <Plus className="size-4" /> Add interface
                    </Button>
                  )
                ) : (
                  <span className="text-xs text-muted-foreground">
                    An operator or administrator can activate interfaces.
                  </span>
                )
              }
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <caption className="sr-only">
                OSPF interface activation for {VERSION_LABEL[version]} on{" "}
                {router.name}
              </caption>
              <TableHead
                columns={[
                  "Interface",
                  "Area",
                  "Network type",
                  "Cost",
                  "Hello / dead",
                  "Priority",
                  "Flags",
                  "",
                ]}
              />
              <tbody>
                {interfaces.map((ospfInterface) => (
                  <tr
                    key={ospfInterface.name}
                    className="border-b border-border/60 align-top transition-colors last:border-0 hover:bg-muted/25"
                  >
                    <td className="px-3 py-3 font-mono text-[12px] font-medium whitespace-nowrap">
                      {ospfInterface.name}
                    </td>
                    <td className="px-3 py-3 font-mono text-[11px]">
                      {ospfInterface.area_id ?? (
                        <Badge variant="warning" className="text-[9px]">
                          unassigned
                        </Badge>
                      )}
                    </td>
                    <td className="px-3 py-3 text-[11px] whitespace-nowrap">
                      {ospfInterface.network_type
                        ? (NETWORK_TYPE_LABEL[ospfInterface.network_type] ??
                          ospfInterface.network_type)
                        : "Default"}
                    </td>
                    <td className="px-3 py-3 font-mono text-[11px]">
                      {ospfInterface.cost ?? "—"}
                    </td>
                    <td className="px-3 py-3 font-mono text-[11px] whitespace-nowrap">
                      {ospfInterface.hello_interval ?? "—"} /{" "}
                      {ospfInterface.dead_interval ?? "—"}
                    </td>
                    <td className="px-3 py-3 font-mono text-[11px]">
                      {ospfInterface.priority ?? "—"}
                    </td>
                    <td className="px-3 py-3">
                      <InterfaceFlags
                        passive={ospfInterface.passive}
                        bfd={ospfInterface.bfd}
                        mtuIgnore={ospfInterface.mtu_ignore}
                      />
                    </td>
                    <td className="px-3 py-3 text-right">
                      {writer ? (
                        <TableActionMenu
                          label={`interface ${ospfInterface.name}`}
                          onEdit={() => {
                            setEditingInterface(ospfInterface);
                            setInterfaceDialogOpen(true);
                          }}
                          onDelete={() => setDeleteInterface(ospfInterface)}
                        />
                      ) : (
                        <span className="text-[11px] text-muted-foreground">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );

  const areasSection = (
    <div className="space-y-4">
      {!configured && (
        <InlineAlert tone="info" title={`${VERSION_LABEL[version]} is not configured`}>
          Creating an area creates{" "}
          <code className="font-mono text-[11px]">
            {VERSION_VYOS_PATH[version]}
          </code>{" "}
          on the device.
        </InlineAlert>
      )}

      <Card variant="surface" className="gap-0 overflow-hidden py-0">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/60 px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">Areas</h2>
            <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
              Area 0 is the backbone. Stub and NSSA areas can also suppress
              summary LSAs.
            </p>
          </div>
          {writer && (
            <Button
              size="sm"
              onClick={() => {
                setEditingArea(null);
                setAreaDialogOpen(true);
              }}
            >
              <Plus className="size-4" /> Add area
            </Button>
          )}
        </div>

        {areas.length === 0 ? (
          <div className="p-4">
            <EmptyState
              compact
              icon={MapIcon}
              title="No OSPF areas"
              description="Every interface needs an area. Create the backbone (0.0.0.0) first, then add any stub or NSSA areas this router should serve."
              action={
                writer ? (
                  <Button
                    size="sm"
                    onClick={() => {
                      setEditingArea(null);
                      setAreaDialogOpen(true);
                    }}
                  >
                    <Plus className="size-4" /> Create area
                  </Button>
                ) : (
                  <span className="text-xs text-muted-foreground">
                    An operator or administrator can create areas.
                  </span>
                )
              }
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <caption className="sr-only">
                OSPF areas for {VERSION_LABEL[version]} on {router.name}
              </caption>
              <TableHead
                columns={["Area ID", "Type", "Interfaces", ""]}
              />
              <tbody>
                {areas.map((area) => (
                  <tr
                    key={area.area_id}
                    className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/25"
                  >
                    <td className="px-3 py-3 font-mono text-[12px] font-medium whitespace-nowrap">
                      {area.area_id}
                    </td>
                    <td className="px-3 py-3">
                      <AreaTypeBadge
                        areaType={area.area_type}
                        noSummary={area.no_summary}
                      />
                    </td>
                    <td className="px-3 py-3">
                      <Badge
                        variant={area.interface_count > 0 ? "outline" : "muted"}
                        className="font-mono text-[9px]"
                        title={
                          area.interface_count > 0
                            ? "In use by interfaces; deletion is refused"
                            : "Unused"
                        }
                      >
                        {area.interface_count} interface
                        {area.interface_count === 1 ? "" : "s"}
                      </Badge>
                    </td>
                    <td className="px-3 py-3 text-right">
                      {writer ? (
                        <TableActionMenu
                          label={`area ${area.area_id}`}
                          onEdit={() => {
                            setEditingArea(area);
                            setAreaDialogOpen(true);
                          }}
                          onDelete={() => setDeleteArea(area)}
                        />
                      ) : (
                        <span className="text-[11px] text-muted-foreground">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="text-[10px] leading-relaxed text-muted-foreground">
        Area ranges, virtual links and authentication are not exposed yet. Area
        type legends: {AREA_TYPE_LABEL.normal} (full LSDB), {AREA_TYPE_LABEL.stub}{" "}
        (no externals) and {AREA_TYPE_LABEL.nssa} (type-7 externals).
      </p>
    </div>
  );

  const redistributionSection = (
    <div className="space-y-4">
      {!configured && (
        <InlineAlert tone="info" title={`${VERSION_LABEL[version]} is not configured`}>
          Adding redistribution creates{" "}
          <code className="font-mono text-[11px]">
            {VERSION_VYOS_PATH[version]}
          </code>{" "}
          on the device.
        </InlineAlert>
      )}

      {writer && unusedSources.length === 0 && (
        <InlineAlert tone="info" title="Every supported source is redistributed">
          Remove an existing entry before adding another. {VERSION_LABEL[version]}{" "}
          supports {supportedSources.map(sourceLabel).join(", ")}.
        </InlineAlert>
      )}

      <Card variant="surface" className="gap-0 overflow-hidden py-0">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/60 px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">Redistribution</h2>
            <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
              Import routes from other protocols. Referenced route maps are
              protected from deletion.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link href={`/route-maps/?router=${router.id}`}>
                <Route className="size-3.5" /> Manage route maps
              </Link>
            </Button>
            {writer && (
              <Button
                size="sm"
                onClick={() => {
                  setEditingRedistribution(null);
                  setRedistributeDialogOpen(true);
                }}
                disabled={!canAddRedistribution}
              >
                <Plus className="size-4" /> Add redistribution
              </Button>
            )}
          </div>
        </div>

        {redistributions.length === 0 ? (
          <div className="p-4">
            <EmptyState
              compact
              icon={ArrowLeftRight}
              title="No redistribution"
              description={`No external routes are imported into ${VERSION_LABEL[version]}. Redistribute connected, static or BGP routes here, optionally filtered by an existing route map.`}
              action={
                writer && canAddRedistribution ? (
                  <Button
                    size="sm"
                    onClick={() => {
                      setEditingRedistribution(null);
                      setRedistributeDialogOpen(true);
                    }}
                  >
                    <Plus className="size-4" /> Add redistribution
                  </Button>
                ) : undefined
              }
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <caption className="sr-only">
                OSPF redistribution for {VERSION_LABEL[version]} on{" "}
                {router.name}
              </caption>
              <TableHead
                columns={["Source", "Metric", "Metric type", "Route map", ""]}
              />
              <tbody>
                {redistributions.map((entry) => (
                  <tr
                    key={entry.source}
                    className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/25"
                  >
                    <td className="px-3 py-3">
                      <p className="text-[12px] font-medium">
                        {sourceLabel(entry.source)}
                      </p>
                    </td>
                    <td className="px-3 py-3 font-mono text-[11px]">
                      {entry.metric ?? "Default"}
                    </td>
                    <td className="px-3 py-3">
                      <MetricTypeCell metricType={entry.metric_type} />
                    </td>
                    <td className="px-3 py-3 font-mono text-[11px]">
                      {entry.route_map ?? (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-right">
                      {writer ? (
                        <TableActionMenu
                          label={`redistribution of ${sourceLabel(entry.source)}`}
                          onEdit={() => {
                            setEditingRedistribution(entry);
                            setRedistributeDialogOpen(true);
                          }}
                          onDelete={() => setDeleteRedistribution(entry)}
                        />
                      ) : (
                        <span className="text-[11px] text-muted-foreground">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="text-[10px] leading-relaxed text-muted-foreground">
        Route-map references participate in OSPF redistribution: a route map
        used here cannot be deleted until the entry is removed. OSPFv3 sources
        differ from OSPFv2 (RIPng instead of RIP).
      </p>
    </div>
  );

  return (
    <>
      {heading}

      {!writer && (
        <InlineAlert tone="info" title="Read-only access">
          Viewers can inspect OSPF configuration and neighbor state. Creating,
          editing and deleting areas, interfaces and redistribution entries
          requires the operator or administrator role; deleting a whole process
          requires the administrator role.
        </InlineAlert>
      )}

      {configQuery.isError && (
        <InlineAlert tone="warning" title="Showing cached OSPF configuration">
          The latest refresh failed: {errorMessage(configQuery.error)}
        </InlineAlert>
      )}

      {versionSwitch}

      <Tabs
        value={tab}
        onValueChange={(value) => {
          if (isSectionTab(value)) selectTab(value);
        }}
        className="gap-4"
      >
        <TabsList
          aria-label="OSPF sections"
          className="h-auto w-full flex-wrap justify-start gap-0.5 bg-muted/50 p-1"
        >
          {SECTION_TABS.map((section) => {
            const counts: Partial<Record<SectionTab, number>> = {
              interfaces: interfaces.length,
              areas: areas.length,
              redistribution: redistributions.length,
            };
            const count = counts[section];
            return (
              <TabsTrigger
                key={section}
                value={section}
                className="h-8 flex-none px-3 text-[12px]"
              >
                {SECTION_LABEL[section]}
                {count !== undefined && count > 0 && (
                  <Badge
                    variant="muted"
                    className="h-4 min-w-4 px-1 font-mono text-[9px]"
                  >
                    {count}
                  </Badge>
                )}
              </TabsTrigger>
            );
          })}
        </TabsList>

        <TabsContent value="overview" className="mt-1">
          {overviewSection}
        </TabsContent>
        <TabsContent value="interfaces" className="mt-1">
          {interfacesSection}
        </TabsContent>
        <TabsContent value="areas" className="mt-1">
          {areasSection}
        </TabsContent>
        <TabsContent value="redistribution" className="mt-1">
          {redistributionSection}
        </TabsContent>
        <TabsContent value="settings" className="mt-1">
          <OspfSettingsPanel router={router} config={config} />
        </TabsContent>
      </Tabs>

      <OspfInterfaceFormDialog
        key={`interface:${version}:${editingInterface?.name ?? "new"}`}
        open={interfaceDialogOpen}
        onOpenChange={(open) => {
          setInterfaceDialogOpen(open);
          if (!open) setEditingInterface(null);
        }}
        routerId={router.id}
        version={version}
        areas={areas}
        supportedNetworkTypes={supportedNetworkTypes}
        ospfInterface={editingInterface}
        onGoToAreas={() => {
          setInterfaceDialogOpen(false);
          setEditingInterface(null);
          selectTab("areas");
        }}
      />

      <OspfAreaFormDialog
        key={`area:${version}:${editingArea?.area_id ?? "new"}`}
        open={areaDialogOpen}
        onOpenChange={(open) => {
          setAreaDialogOpen(open);
          if (!open) setEditingArea(null);
        }}
        routerId={router.id}
        version={version}
        area={editingArea}
      />

      <OspfAreaDeleteDialog
        open={deleteArea !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteArea(null);
        }}
        routerId={router.id}
        version={version}
        area={deleteArea}
        usedByInterfaces={
          deleteArea
            ? interfaces
                .filter(
                  (ospfInterface) =>
                    ospfInterface.area_id === deleteArea.area_id,
                )
                .map((ospfInterface) => ospfInterface.name)
            : []
        }
      />

      <OspfRedistributeFormDialog
        key={`redistribution:${version}:${editingRedistribution?.source ?? "new"}`}
        open={redistributeDialogOpen}
        onOpenChange={(open) => {
          setRedistributeDialogOpen(open);
          if (!open) setEditingRedistribution(null);
        }}
        routerId={router.id}
        version={version}
        redistribution={editingRedistribution}
        supportedSources={supportedSources}
        existingSources={usedSources}
        routeMapNames={routeMapNames}
      />

      <OspfRedistributeDeleteDialog
        open={deleteRedistribution !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteRedistribution(null);
        }}
        routerId={router.id}
        version={version}
        redistribution={deleteRedistribution}
      />

      <AlertDialog
        open={deleteInterface !== null}
        onOpenChange={(open) => {
          if (!open && !deleteInterfaceMutation.isPending) {
            setDeleteInterface(null);
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <Trash2 className="size-4 text-destructive" />
              Remove OSPF from {deleteInterface?.name}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              The interface entry is deleted from{" "}
              <code className="font-mono text-[11px]">
                {VERSION_VYOS_PATH[version]}
              </code>
              . Adjacencies on this interface drop immediately; the VyOS
              interface itself and its IP addressing are untouched.
            </AlertDialogDescription>
          </AlertDialogHeader>

          {deleteInterface?.area_id && (
            <p className="text-[11px] text-muted-foreground">
              Area <span className="font-mono">{deleteInterface.area_id}</span>{" "}
              loses this activation. Once it has no interfaces left, the area
              itself can be deleted.
            </p>
          )}

          {deleteInterfaceMutation.isPending && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Spinner /> Removing interface…
            </div>
          )}

          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteInterfaceMutation.isPending}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleteInterfaceMutation.isPending}
              onClick={(event) => {
                event.preventDefault();
                void handleDeleteInterface();
              }}
            >
              <Trash2 className="size-4" /> Remove interface
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Route entry                                                                */
/* -------------------------------------------------------------------------- */

export default function OspfPage() {
  return (
    <RouterBoundary emptyDescription="Add a VyOS device before configuring or monitoring OSPF.">
      {(router) => <OspfContent router={router} />}
    </RouterBoundary>
  );
}
