"use client";

import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Cable,
  Filter,
  KeyRound,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Shield,
  Trash2,
  UsersRound,
} from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth";
import { errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import {
  queryKeys,
  useWireGuardInterface,
  useWireGuardInterfaces,
  useWireGuardStatus,
} from "@/lib/queries";
import { canWrite } from "@/lib/roles";
import type {
  Router,
  WireGuardInterface,
  WireGuardPeer,
  WireGuardStatus,
  WireGuardStatusPeer,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { RouterBoundary } from "@/components/router-boundary";
import {
  WireGuardInterfaceDeleteDialog,
  WireGuardPeerDeleteDialog,
} from "@/components/vpn/delete-dialogs";
import { WireGuardInterfaceFormDialog } from "@/components/vpn/interface-form-dialog";
import { WireGuardPeerFormDialog } from "@/components/vpn/peer-form-dialog";
import { RotateKeyDialog } from "@/components/vpn/rotate-key-dialog";
import {
  CopyButton,
  EnabledBadge,
  addressSummary,
  formatEndpoint,
  formatKeepalive,
  shortKey,
  wireGuardPath,
} from "@/components/vpn/shared";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Stat, StatStrip } from "@/components/ui/stat";
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

const IF_PARAM = "if";

function readIfParam(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(IF_PARAM);
}

/**
 * Only `if` is touched here; `?router=` is owned by RouterProvider and must
 * survive every interface selection. No dynamic route segment is used, so the
 * page stays statically exportable.
 */
function writeIfParam(name: string | null) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (name) {
    url.searchParams.set(IF_PARAM, name);
  } else {
    url.searchParams.delete(IF_PARAM);
  }
  window.history.replaceState(window.history.state, "", url.toString());
}

/* -------------------------------------------------------------------------- */
/* Small pieces                                                               */
/* -------------------------------------------------------------------------- */

function sortInterfaces(items: WireGuardInterface[]): WireGuardInterface[] {
  return [...items].sort((a, b) => a.name.localeCompare(b.name));
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

function SummaryRow({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border/50 py-2 text-xs last:border-0">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="max-w-[68%] text-right font-mono text-[11px] break-words">
        {value}
      </span>
    </div>
  );
}

function PublicKeyRow({ value }: { value: string | null }) {
  if (!value) {
    return (
      <SummaryRow
        label="Public key"
        value={<span className="text-muted-foreground">No valid private key</span>}
      />
    );
  }
  return (
    <div className="flex items-start justify-between gap-2 border-b border-border/50 py-1.5 text-xs last:border-0">
      <span className="shrink-0 py-0.5 text-muted-foreground">Public key</span>
      <span className="flex min-w-0 items-start justify-end gap-1">
        <span className="max-w-[34ch] text-right font-mono text-[10px] break-all sm:max-w-[46ch]">
          {value}
        </span>
        <CopyButton
          value={value}
          label="Copy interface public key"
          className="-my-1 shrink-0"
        />
      </span>
    </div>
  );
}

function InterfaceListItem({
  iface,
  selected,
  onSelect,
}: {
  iface: WireGuardInterface;
  selected: boolean;
  onSelect: () => void;
}) {
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
            {iface.name}
          </span>
          <EnabledBadge enabled={iface.enabled} className="text-[8px]" />
        </div>
        <p className="mt-0.5 line-clamp-1 text-[10px] leading-relaxed text-muted-foreground">
          {iface.description || "No description"}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[9px] text-muted-foreground">
          <span className="truncate">{addressSummary(iface.addresses)}</span>
          <span aria-hidden="true">·</span>
          <span>
            {iface.peer_count} peer{iface.peer_count === 1 ? "" : "s"}
          </span>
          {iface.port !== null && (
            <>
              <span aria-hidden="true">·</span>
              <span>:{iface.port}</span>
            </>
          )}
        </div>
      </button>
    </li>
  );
}

function PeerActionsMenu({
  peer,
  onEdit,
  onDelete,
}: {
  peer: WireGuardPeer;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Actions for peer ${peer.name}`}
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        <DropdownMenuItem onSelect={onEdit}>
          <Pencil /> Edit peer
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onSelect={onDelete}>
          <Trash2 /> Delete peer
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Shorten human-readable device output without pretending it is a timestamp. */
function compactHandshake(value: string | null): string {
  if (!value) return "No handshake";
  return value
    .replace(/(\d+)\s*seconds?\b/g, "$1s")
    .replace(/(\d+)\s*minutes?\b/g, "$1m")
    .replace(/(\d+)\s*hours?\b/g, "$1h")
    .replace(/(\d+)\s*days?\b/g, "$1d")
    .replace(/, /g, " ");
}

function LivePeerCell({
  live,
  status,
}: {
  live: WireGuardStatusPeer | null;
  status: WireGuardStatus | undefined;
}) {
  if (!status) {
    return <span className="text-[11px] text-muted-foreground">—</span>;
  }
  if (!live) {
    return (
      <span
        className="text-[10px] text-muted-foreground"
        title="The device did not report this public key in the interface summary"
      >
        not reported
      </span>
    );
  }
  return (
    <div className="w-[170px] text-[10px] leading-relaxed">
      <p
        className="truncate font-mono"
        title={live.latest_handshake || "No handshake reported"}
      >
        {compactHandshake(live.latest_handshake)}
      </p>
      <p className="truncate font-mono text-muted-foreground">
        ↓ {live.transfer_received || "—"} · ↑ {live.transfer_sent || "—"}
      </p>
    </div>
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

/* -------------------------------------------------------------------------- */
/* Page content                                                               */
/* -------------------------------------------------------------------------- */

function VpnContent({ router }: { router: Router }) {
  const { user } = useAuth();
  const writer = canWrite(user?.role);
  const queryClient = useQueryClient();

  // Read the query string in the initialiser so `?if=wg0` deep links open on
  // the right interface. The page paints after the auth gate, so this cannot
  // mismatch the prerendered shell.
  const [selectedName, setSelectedName] = React.useState<string | null>(() =>
    readIfParam(),
  );
  const [search, setSearch] = React.useState("");
  const [refreshing, setRefreshing] = React.useState(false);

  const [createOpen, setCreateOpen] = React.useState(false);
  const [editOpen, setEditOpen] = React.useState(false);
  const [rotateOpen, setRotateOpen] = React.useState(false);
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const [peerFormOpen, setPeerFormOpen] = React.useState(false);
  const [editingPeer, setEditingPeer] = React.useState<WireGuardPeer | null>(
    null,
  );
  const [deletingPeer, setDeletingPeer] = React.useState<WireGuardPeer | null>(
    null,
  );

  const interfacesQuery = useWireGuardInterfaces(router.id);
  const interfaces = React.useMemo(
    () => sortInterfaces(interfacesQuery.data?.items ?? []),
    [interfacesQuery.data],
  );

  const detailQuery = useWireGuardInterface(router.id, selectedName);
  const detail = detailQuery.data ?? null;

  // Polls every 15 s while an interface is selected. A configured but stopped
  // interface answers 200 with `error`; the table falls back to config data.
  const statusQuery = useWireGuardStatus(router.id, selectedName);
  const status = statusQuery.data;

  const liveByKey = React.useMemo(() => {
    const map = new Map<string, WireGuardStatusPeer>();
    for (const peer of status?.peers ?? []) map.set(peer.public_key, peer);
    return map;
  }, [status]);

  // Reconcile `?if=` with the loaded list. A valid deep link wins; otherwise
  // open the first interface so the page is immediately useful (and matches
  // the route-map / prefix-list master-detail behaviour).
  React.useEffect(() => {
    if (interfacesQuery.data === undefined) return;
    const isValid = (name: string | null): name is string =>
      !!name && interfaces.some((iface) => iface.name === name);
    const param = readIfParam();

    if (selectedName && !isValid(selectedName)) {
      const next = isValid(param)
        ? param
        : (interfaces[0]?.name ?? null);
      setSelectedName(next);
      writeIfParam(next);
      return;
    }
    if (!selectedName && interfaces.length > 0) {
      const next = isValid(param) ? param : interfaces[0].name;
      setSelectedName(next);
      writeIfParam(next);
    }
  }, [interfaces, interfacesQuery.data, selectedName]);

  // Browser back/forward changes ?if without a Next navigation.
  React.useEffect(() => {
    const onPopState = () => setSelectedName(readIfParam());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const closeDetailDialogs = React.useCallback(() => {
    setEditOpen(false);
    setRotateOpen(false);
    setDeleteOpen(false);
    setPeerFormOpen(false);
    setEditingPeer(null);
    setDeletingPeer(null);
  }, []);

  const selectInterface = (name: string) => {
    if (name !== selectedName) closeDetailDialogs();
    setSelectedName(name);
    writeIfParam(name);
  };

  const totalPeers = interfaces.reduce(
    (total, iface) => total + iface.peer_count,
    0,
  );
  const enabledInterfaces = interfaces.filter((iface) => iface.enabled).length;
  const liveHandshakes = (status?.peers ?? []).filter(
    (peer) => !!peer.latest_handshake && peer.latest_handshake !== "never",
  ).length;

  const filtered = React.useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return interfaces;
    return interfaces.filter((iface) =>
      [iface.name, iface.description ?? "", ...iface.addresses]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [interfaces, search]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.wireguard(router.id),
          exact: true,
        }),
        selectedName
          ? queryClient.invalidateQueries({
              queryKey: queryKeys.wireguardInterface(router.id, selectedName),
            })
          : Promise.resolve(),
        selectedName
          ? queryClient.invalidateQueries({
              queryKey: queryKeys.wireguardStatus(router.id, selectedName),
            })
          : Promise.resolve(),
      ]);
      toast.info("WireGuard refreshed");
    } finally {
      setRefreshing(false);
    }
  };

  const heading = (
    <PageHeader
      title="VPN"
      badge={
        <>
          <RouterBadge name={router.name} />
          <Badge variant="outline" className="text-[10px]">
            WireGuard
          </Badge>
        </>
      }
      description="WireGuard tunnels: interfaces, public keys and peers. Live handshakes and transfer counters are polled every 15 seconds for the selected interface."
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
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="size-4" /> New interface
            </Button>
          )}
        </>
      }
    />
  );

  const readOnlyAlert = !writer ? (
    <InlineAlert tone="info" title="Read-only access">
      Viewers can inspect WireGuard interfaces, public keys, peers and live
      handshakes. Creating, editing, rotating keys and deleting interfaces or
      peers requires the operator or administrator role.
    </InlineAlert>
  ) : null;

  if (interfacesQuery.isLoading) {
    return (
      <>
        {heading}
        <TableSkeleton rows={5} />
      </>
    );
  }

  if (interfacesQuery.isError && !interfacesQuery.data) {
    return (
      <>
        {heading}
        <ErrorPanel
          title={`Could not read WireGuard interfaces from ${router.name}`}
          error={interfacesQuery.error}
          onRetry={() => void interfacesQuery.refetch()}
        />
      </>
    );
  }

  if (interfaces.length === 0) {
    return (
      <>
        {heading}
        {readOnlyAlert}
        <EmptyState
          icon={Shield}
          title="No WireGuard interfaces"
          description={
            <>
              No <code className="font-mono text-[11px]">interfaces wireguard</code>{" "}
              interface exists on <strong>{router.name}</strong>. Create a
              tunnel, then add the remote peers and their public keys.
            </>
          }
          action={
            writer ? (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="size-4" /> Create interface
              </Button>
            ) : (
              <span className="text-xs text-muted-foreground">
                An operator or administrator can create WireGuard interfaces.
              </span>
            )
          }
        />

        <WireGuardInterfaceFormDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          routerId={router.id}
          iface={null}
          existingNames={[]}
          onCreated={(name) => selectInterface(name)}
        />
      </>
    );
  }

  const selectedInterface =
    interfaces.find((iface) => iface.name === selectedName) ?? null;
  const statusHint = !selectedName
    ? "Select an interface"
    : status?.error
      ? `Status error · ${status.name}`
      : status
        ? `${liveHandshakes}/${(status.peers ?? []).length} handshaked · ${formatRelative(status.collected_at)}`
        : statusQuery.isError
          ? "Live status unavailable"
          : "Reading live status…";

  return (
    <>
      {heading}
      {readOnlyAlert}

      {interfacesQuery.isError && (
        <InlineAlert tone="warning" title="Showing cached WireGuard data">
          The latest refresh failed: {errorMessage(interfacesQuery.error)}
        </InlineAlert>
      )}

      <StatStrip>
        <Stat
          label="Interfaces"
          value={interfaces.length}
          hint={`${enabledInterfaces} enabled`}
          icon={Cable}
        />
        <Stat
          label="Peers"
          value={totalPeers}
          hint={`across ${interfaces.length} interface${interfaces.length === 1 ? "" : "s"}`}
          icon={UsersRound}
        />
        <Stat
          label="Selected"
          value={selectedName ?? "None"}
          hint={
            selectedInterface
              ? `Port ${selectedInterface.port ?? "device default"} · ${selectedInterface.peer_count} peer${selectedInterface.peer_count === 1 ? "" : "s"}`
              : "Pick an interface below"
          }
          icon={Shield}
        />
        <Stat
          label="Live handshakes"
          value={selectedName && status ? liveHandshakes : "—"}
          hint={statusHint}
          icon={Activity}
          loading={!!selectedName && statusQuery.isLoading && !status}
        />
      </StatStrip>

      <div className="grid items-start gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Card className="gap-0 overflow-hidden py-0 lg:sticky lg:top-[6rem] lg:border-r lg:border-border/60">
          <div className="space-y-2 border-b border-border/70 p-3">
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search name, address…"
                className="h-8 pl-8 text-xs"
                aria-label="Search WireGuard interfaces"
              />
            </div>
            <div className="flex items-center justify-between text-[10px] text-muted-foreground">
              <span className="font-mono">
                {filtered.length}/{interfaces.length} interfaces
              </span>
              <span className="font-mono">{totalPeers} peers</span>
            </div>
          </div>

          {filtered.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <Filter className="mx-auto size-5 text-muted-foreground" />
              <p className="mt-2 text-sm font-medium">No interfaces match</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Adjust the search to see all {interfaces.length} interfaces.
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
              {filtered.map((iface) => (
                <InterfaceListItem
                  key={iface.name}
                  iface={iface}
                  selected={iface.name === selectedName}
                  onSelect={() => selectInterface(iface.name)}
                />
              ))}
            </ul>
          )}

          <div className="border-t border-border/70 p-3">
            <p className="text-[10px] leading-relaxed text-muted-foreground">
              The selected interface is stored in the URL as{" "}
              <code className="font-mono">?if=&lt;name&gt;</code> so links stay
              shareable. Private keys are never part of any URL.
            </p>
          </div>
        </Card>

        <div className="min-w-0 space-y-4">
          {!selectedName ? (
            <div className="rounded-xl border border-dashed border-border/70 px-6 py-14 text-center">
              <Shield className="mx-auto size-5 text-muted-foreground" />
              <p className="mt-2 text-sm font-semibold">
                Select a WireGuard interface
              </p>
              <p className="mx-auto mt-1 max-w-sm text-xs leading-relaxed text-muted-foreground">
                Pick an interface on the left to inspect its public key,
                addresses and peers, with live handshake and transfer counters.
              </p>
            </div>
          ) : detailQuery.isLoading && !detail ? (
            <div className="space-y-3">
              <Skeleton className="h-28 w-full rounded-xl" />
              <TableSkeleton rows={3} />
            </div>
          ) : detailQuery.isError && !detail ? (
            <ErrorPanel
              title={`Could not read ${selectedName} from ${router.name}`}
              error={detailQuery.error}
              onRetry={() => void detailQuery.refetch()}
            />
          ) : detail ? (
            <>
              <Card className="gap-0 overflow-hidden border-border/60 py-0">
                <div className="flex flex-col gap-3 border-b border-border/70 p-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="font-mono text-base font-semibold break-all">
                        {detail.name}
                      </h2>
                      <EnabledBadge enabled={detail.enabled} />
                      <Badge variant="outline" className="font-mono text-[9px]">
                        {detail.peer_count} peer
                        {detail.peer_count === 1 ? "" : "s"}
                      </Badge>
                      {status?.error && (
                        <Badge variant="warning" className="text-[9px]">
                          not running
                        </Badge>
                      )}
                    </div>
                    <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-muted-foreground">
                      {detail.description || "No description."}
                    </p>
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
                        onClick={() => setRotateOpen(true)}
                      >
                        <KeyRound className="size-3.5" /> Rotate key
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="text-destructive hover:text-destructive"
                        onClick={() => setDeleteOpen(true)}
                      >
                        <Trash2 className="size-3.5" /> Delete
                      </Button>
                    </div>
                  )}
                </div>

                <div className="grid gap-x-10 px-4 py-1 md:grid-cols-2">
                  <div>
                    <PublicKeyRow value={detail.public_key} />
                    <SummaryRow
                      label="Addresses"
                      value={
                        detail.addresses.length > 0 ? (
                          detail.addresses.join(", ")
                        ) : (
                          <span className="text-muted-foreground">None</span>
                        )
                      }
                    />
                    <SummaryRow
                      label="Listen port"
                      value={
                        detail.port ?? (
                          <span className="text-muted-foreground">
                            Device default
                          </span>
                        )
                      }
                    />
                  </div>
                  <div>
                    <SummaryRow
                      label="MTU"
                      value={
                        detail.mtu ?? (
                          <span className="text-muted-foreground">
                            Device default (1420)
                          </span>
                        )
                      }
                    />
                    <SummaryRow label="Peers" value={detail.peer_count} />
                    <SummaryRow
                      label="VyOS path"
                      value={wireGuardPath(detail.name)}
                    />
                  </div>
                </div>

                <div className="border-t border-border/60 px-4 py-2">
                  <p className="text-[10px] leading-relaxed text-muted-foreground">
                    {status
                      ? `Live status collected ${formatRelative(status.collected_at)} · polled every 15 seconds`
                      : statusQuery.isLoading
                        ? "Reading live status…"
                        : statusQuery.isError
                          ? "Live status unavailable; showing configuration only"
                          : "Live status pending"}{" "}
                    · private key is write-only
                  </p>
                </div>
              </Card>

              {detailQuery.isError && (
                <InlineAlert tone="warning" title="Showing cached interface data">
                  The latest refresh failed: {errorMessage(detailQuery.error)}
                </InlineAlert>
              )}

              {status?.error && (
                <InlineAlert
                  tone="warning"
                  title="WireGuard interface is not running"
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
                  {status.error} Peer rows keep the configured values; live
                  handshake and transfer columns are unavailable.
                </InlineAlert>
              )}

              {statusQuery.isError && !status && (
                <InlineAlert
                  tone="error"
                  title="Could not read live status"
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
                  {errorMessage(statusQuery.error)} Peer rows below show the
                  configured values.
                </InlineAlert>
              )}

              <Card variant="surface" className="gap-0 overflow-hidden py-0">
                <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/60 px-4 py-3">
                  <div className="min-w-0">
                    <h2 className="text-sm font-semibold">Peers</h2>
                    <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
                      Live columns come from{" "}
                      <code className="font-mono">
                        show interfaces wireguard {detail.name} summary
                      </code>{" "}
                      and are matched by public key.
                    </p>
                  </div>
                  {writer && (
                    <Button
                      size="sm"
                      onClick={() => {
                        setEditingPeer(null);
                        setPeerFormOpen(true);
                      }}
                    >
                      <Plus className="size-4" /> Add peer
                    </Button>
                  )}
                </div>

                {detail.peers.length === 0 ? (
                  <div className="p-4">
                    <EmptyState
                      compact
                      icon={UsersRound}
                      title="No peers on this interface"
                      description="Add the remote WireGuard public key, its allowed IP prefixes and, optionally, an endpoint and preshared key."
                      action={
                        writer ? (
                          <Button
                            size="sm"
                            onClick={() => {
                              setEditingPeer(null);
                              setPeerFormOpen(true);
                            }}
                          >
                            <Plus className="size-4" /> Add peer
                          </Button>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            An operator or administrator can add peers.
                          </span>
                        )
                      }
                    />
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[760px] table-fixed text-sm">
                      <caption className="sr-only">
                        WireGuard peers for {detail.name} on {router.name}
                      </caption>
                      <colgroup>
                        <col className="w-[16%]" />
                        <col className="w-[14%]" />
                        <col className="w-[19%]" />
                        <col className="w-[18%]" />
                        <col className="w-[25%]" />
                        <col className="w-[8%]" />
                      </colgroup>
                      <TableHead
                        columns={[
                          "Alias",
                          "Public key",
                          "Allowed IPs",
                          "Endpoint",
                          "Live",
                          "",
                        ]}
                      />
                      <tbody>
                        {detail.peers.map((peer) => {
                          const live = liveByKey.get(peer.public_key) ?? null;
                          return (
                            <tr
                              key={peer.name}
                              className="border-b border-border/60 align-top transition-colors last:border-0 hover:bg-muted/25"
                            >
                              <td className="px-3 py-3">
                                <p
                                  className="truncate font-mono text-[12px] font-medium"
                                  title={peer.name}
                                >
                                  {peer.name}
                                </p>
                                <p className="mt-0.5 line-clamp-2 text-[10px] leading-relaxed text-muted-foreground">
                                  {peer.description || "No description"}
                                </p>
                                <div className="mt-1 flex flex-wrap items-center gap-1">
                                  {peer.has_preshared_key && (
                                    <Badge
                                      variant="outline"
                                      className="font-mono text-[8px]"
                                      title="A preshared key is configured (write-only)"
                                    >
                                      psk
                                    </Badge>
                                  )}
                                  {!peer.enabled && (
                                    <Badge
                                      variant="muted"
                                      className="text-[8px]"
                                    >
                                      disabled
                                    </Badge>
                                  )}
                                </div>
                              </td>
                              <td className="px-3 py-3">
                                <div className="flex items-center gap-1.5">
                                  <span
                                    className="font-mono text-[10px] whitespace-nowrap"
                                    title={peer.public_key}
                                  >
                                    {shortKey(peer.public_key, 10)}
                                  </span>
                                  <CopyButton
                                    value={peer.public_key}
                                    label={`Copy public key for peer ${peer.name}`}
                                  />
                                </div>
                              </td>
                              <td
                                className="px-3 py-3"
                                title={peer.allowed_ips.join(", ")}
                              >
                                {peer.allowed_ips.length === 0 ? (
                                  <span className="text-[11px] text-muted-foreground">
                                    —
                                  </span>
                                ) : (
                                  <div className="space-y-0.5 font-mono text-[10px]">
                                    {peer.allowed_ips
                                      .slice(0, 2)
                                      .map((prefix) => (
                                        <p
                                          key={prefix}
                                          className="truncate whitespace-nowrap"
                                        >
                                          {prefix}
                                        </p>
                                      ))}
                                    {peer.allowed_ips.length > 2 && (
                                      <p className="text-[9px] text-muted-foreground">
                                        +{peer.allowed_ips.length - 2} more
                                      </p>
                                    )}
                                  </div>
                                )}
                              </td>
                              <td className="min-w-0 overflow-hidden px-3 py-3">
                                <p
                                  className="truncate font-mono text-[10px]"
                                  title={formatEndpoint(
                                    peer.endpoint,
                                    peer.endpoint_port,
                                  )}
                                >
                                  {formatEndpoint(
                                    peer.endpoint,
                                    peer.endpoint_port,
                                  )}
                                </p>
                                {peer.persistent_keepalive != null && (
                                  <p className="mt-0.5 truncate font-mono text-[9px] text-muted-foreground">
                                    keepalive {formatKeepalive(peer.persistent_keepalive)}
                                  </p>
                                )}
                              </td>
                              <td className="px-3 py-3">
                                <LivePeerCell live={live} status={status} />
                              </td>
                              <td className="px-3 py-3 text-right">
                                {writer ? (
                                  <PeerActionsMenu
                                    peer={peer}
                                    onEdit={() => {
                                      setEditingPeer(peer);
                                      setPeerFormOpen(true);
                                    }}
                                    onDelete={() => setDeletingPeer(peer)}
                                  />
                                ) : (
                                  <span className="text-[11px] text-muted-foreground">
                                    —
                                  </span>
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
            </>
          ) : null}
        </div>
      </div>

      <WireGuardInterfaceFormDialog
        key={`interface:${detail?.name ?? "new"}`}
        open={createOpen}
        onOpenChange={setCreateOpen}
        routerId={router.id}
        iface={null}
        existingNames={interfaces.map((iface) => iface.name)}
        onCreated={(name) => selectInterface(name)}
      />

      {detail && (
        <>
          <WireGuardInterfaceFormDialog
            key={`interface-edit:${detail.name}`}
            open={editOpen}
            onOpenChange={setEditOpen}
            routerId={router.id}
            iface={detail}
            existingNames={interfaces.map((iface) => iface.name)}
          />

          <RotateKeyDialog
            key={`rotate:${detail.name}`}
            open={rotateOpen}
            onOpenChange={setRotateOpen}
            routerId={router.id}
            iface={detail}
          />

          <WireGuardInterfaceDeleteDialog
            open={deleteOpen}
            onOpenChange={setDeleteOpen}
            routerId={router.id}
            iface={detail}
            onDeleted={(name) => {
              const remaining = interfaces.filter(
                (iface) => iface.name !== name,
              );
              const next = remaining[0]?.name ?? null;
              setSelectedName(next);
              writeIfParam(next);
              closeDetailDialogs();
            }}
          />
        </>
      )}

      {detail && (
        <WireGuardPeerFormDialog
          key={`peer:${detail.name}:${editingPeer?.name ?? "new"}`}
          open={peerFormOpen}
          onOpenChange={(open) => {
            setPeerFormOpen(open);
            if (!open) setEditingPeer(null);
          }}
          routerId={router.id}
          ifaceName={detail.name}
          peer={editingPeer}
        />
      )}

      {detail && (
        <WireGuardPeerDeleteDialog
          open={deletingPeer !== null}
          onOpenChange={(open) => {
            if (!open) setDeletingPeer(null);
          }}
          routerId={router.id}
          ifaceName={detail.name}
          peer={deletingPeer}
          onDeleted={() => setDeletingPeer(null)}
        />
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Route entry                                                                */
/* -------------------------------------------------------------------------- */

export default function VpnPage() {
  return (
    <RouterBoundary emptyDescription="Add a VyOS device before managing WireGuard tunnels.">
      {(router) => <VpnContent router={router} />}
    </RouterBoundary>
  );
}
