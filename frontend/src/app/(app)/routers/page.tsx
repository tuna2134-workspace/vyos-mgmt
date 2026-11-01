"use client";

import * as React from "react";
import Link from "next/link";
import {
  CircleCheck,
  KeyRound,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Router as RouterIcon,
  Search,
  ServerOff,
  ShieldAlert,
  Trash2,
  Unplug,
  Zap,
} from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth";
import { useRouterSelection } from "@/lib/router-context";
import { useDeleteRouter } from "@/lib/queries";
import { errorMessage } from "@/lib/api";
import { formatDate, formatLatency, humanizeKey } from "@/lib/format";
import { isAdmin } from "@/lib/roles";
import type { Router, SystemInfo } from "@/lib/types";
import { RouterFormDialog } from "@/components/routers/router-form-dialog";
import { RouterTestDialog } from "@/components/routers/router-test-dialog";
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
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  EmptyState,
  ErrorPanel,
  InlineAlert,
  PageHeader,
  Spinner,
  TableSkeleton,
  DriverBadge,
  StatusDot,
} from "@/components/states";

function ApiKeyCell({ router }: { router: Router }) {
  if (router.driver === "mock") {
    return <span className="text-xs text-muted-foreground">Not required</span>;
  }
  return router.api_key_configured ? (
    <Badge variant="success" className="gap-1 text-[10px]">
      <KeyRound className="size-2.5" /> configured
    </Badge>
  ) : (
    <Badge variant="muted" className="text-[10px]">
      missing
    </Badge>
  );
}

export default function RoutersPage() {
  const { user } = useAuth();
  const admin = isAdmin(user?.role);
  const {
    routers,
    selectedId,
    selectRouter,
    isLoading,
    isError,
    error,
    refetch,
  } = useRouterSelection();

  const deleteRouter = useDeleteRouter();
  const [query, setQuery] = React.useState("");
  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Router | null>(null);
  const [testTarget, setTestTarget] = React.useState<Router | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<Router | null>(null);
  const [testResults, setTestResults] = React.useState<
    Record<string, SystemInfo>
  >({});

  const filtered = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return routers;
    return routers.filter((router) =>
      [router.name, router.host, router.driver, router.description ?? ""]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [routers, query]);

  const openCreate = () => {
    setEditing(null);
    setFormOpen(true);
  };

  const openEdit = (router: Router) => {
    setEditing(router);
    setFormOpen(true);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteRouter.mutateAsync(deleteTarget.id);
      toast.success("Router removed", {
        description: `${deleteTarget.name} was removed from the control plane. The device itself was not changed.`,
      });
      setDeleteTarget(null);
    } catch (error) {
      toast.error("Could not remove router", {
        description: errorMessage(error),
      });
    }
  };

  return (
    <>
      <PageHeader
        title="Routers"
        description={
          admin
            ? "Register VyOS devices, verify connectivity and manage connection credentials."
            : "VyOS devices registered in this control plane. Connection tests are available to every role."
        }
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void refetch();
                toast.info("Router list refreshed");
              }}
            >
              <RefreshCw className="size-3.5" /> Refresh
            </Button>
            {admin && (
              <Button size="sm" onClick={openCreate}>
                <Plus className="size-4" /> Add router
              </Button>
            )}
          </>
        }
        badge={
          <Badge variant="outline" className="font-mono text-[10px]">
            {routers.length} {routers.length === 1 ? "device" : "devices"}
          </Badge>
        }
      />

      {!admin && (
        <InlineAlert tone="info" title="Administrator access required">
          Router creation, editing and deletion are restricted to administrators.
          You can run connection tests and select the active router.
        </InlineAlert>
      )}

      {isError ? (
        <ErrorPanel
          title="Could not load routers"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : isLoading ? (
        <TableSkeleton />
      ) : routers.length === 0 ? (
        <EmptyState
          icon={ServerOff}
          title="No routers registered"
          description={
            admin
              ? "Add a VyOS device to begin. Use the mock driver to explore the console without hardware."
              : "No devices are registered yet. Ask an administrator to add one."
          }
          action={
            admin ? (
              <Button onClick={openCreate}>
                <Plus className="size-4" /> Add your first router
              </Button>
            ) : (
              <Button asChild variant="outline">
                <Link href="/">Back to dashboard</Link>
              </Button>
            )
          }
        />
      ) : (
        <Card variant="surface" className="gap-0 overflow-hidden py-0">
          <div className="flex flex-col gap-3 border-b border-border/70 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative w-full max-w-xs">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search name, host or driver…"
                className="h-8 pl-8 text-xs"
                aria-label="Search routers"
              />
            </div>
            <p className="text-[11px] text-muted-foreground">
              {filtered.length} of {routers.length} shown · active router is
              highlighted
            </p>
          </div>

          {filtered.length === 0 ? (
            <div className="px-4 py-12 text-center">
              <p className="text-sm font-medium">No routers match “{query}”</p>
              <Button
                variant="ghost"
                size="sm"
                className="mt-2"
                onClick={() => setQuery("")}
              >
                Clear search
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[880px] text-sm">
                <thead>
                  <tr className="border-b border-border/70 bg-muted/30">
                    {[
                      "Router",
                      "Driver",
                      "Endpoint",
                      "API key",
                      "Last test",
                      "Updated",
                      "",
                    ].map((label, i) => (
                      <th
                        key={label || i}
                        scope="col"
                        className="px-4 py-2.5 text-left text-[10px] font-semibold tracking-[0.12em] whitespace-nowrap text-muted-foreground uppercase"
                      >
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((router) => {
                    const result = testResults[router.id];
                    const active = router.id === selectedId;
                    return (
                      <tr
                        key={router.id}
                        className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/25"
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-background text-muted-foreground">
                              <RouterIcon className="size-3.5" />
                            </span>
                            <div className="min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span className="truncate text-[13px] font-medium">
                                  {router.name}
                                </span>
                                {active && (
                                  <Badge
                                    variant="default"
                                    className="gap-1 text-[9px]"
                                  >
                                    <StatusDot tone="primary" /> active
                                  </Badge>
                                )}
                              </div>
                              <p className="truncate text-[10px] text-muted-foreground">
                                {router.description ||
                                  humanizeKey(router.driver)}
                              </p>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <DriverBadge driver={router.driver} />
                        </td>
                        <td className="px-4 py-3">
                          <p className="font-mono text-[11px]">
                            {router.host}:{router.port}
                          </p>
                          <p className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                            <span className="uppercase">{router.protocol}</span>
                            <span aria-hidden="true">·</span>
                            <span>
                              TLS {router.verify_tls ? "verified" : "unverified"}
                            </span>
                          </p>
                        </td>
                        <td className="px-4 py-3">
                          <ApiKeyCell router={router} />
                        </td>
                        <td className="px-4 py-3">
                          {result ? (
                            <div className="space-y-0.5">
                              <span className="flex items-center gap-1.5 text-[11px] font-medium">
                                <StatusDot
                                  tone={
                                    result.reachable ? "success" : "danger"
                                  }
                                />
                                {result.reachable ? "Reachable" : "Failed"}
                              </span>
                              <span className="block font-mono text-[10px] text-muted-foreground">
                                {result.reachable
                                  ? formatLatency(result.latency_ms)
                                  : "no response"}
                              </span>
                            </div>
                          ) : (
                            <span className="text-[11px] text-muted-foreground">
                              Not tested
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-[11px] text-muted-foreground">
                          {formatDate(router.updated_at)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 gap-1 px-2 text-[11px]"
                              onClick={() => setTestTarget(router)}
                            >
                              <Zap className="size-3" /> Test
                            </Button>
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon-sm"
                                  aria-label={`Actions for ${router.name}`}
                                >
                                  <MoreHorizontal className="size-4" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end" className="w-48">
                                <DropdownMenuLabel>
                                  {router.name}
                                </DropdownMenuLabel>
                                <DropdownMenuItem
                                  onSelect={() => setTestTarget(router)}
                                >
                                  <Unplug /> Test connection
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                  disabled={active}
                                  onSelect={() => {
                                    selectRouter(router.id);
                                    toast.success(
                                      `${router.name} is now the active router`,
                                    );
                                  }}
                                >
                                  <CircleCheck /> Set as active
                                </DropdownMenuItem>
                                {admin && (
                                  <>
                                    <DropdownMenuSeparator />
                                    <DropdownMenuItem
                                      onSelect={() => openEdit(router)}
                                    >
                                      <Pencil /> Edit router
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                      variant="destructive"
                                      onSelect={() => setDeleteTarget(router)}
                                    >
                                      <Trash2 /> Delete router
                                    </DropdownMenuItem>
                                  </>
                                )}
                              </DropdownMenuContent>
                            </DropdownMenu>
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
      )}

      {admin && (
        <div className="flex items-start gap-2.5 rounded-lg border border-border/70 bg-card px-4 py-3 text-[11px] text-muted-foreground">
          <ShieldAlert className="mt-0.5 size-3.5 shrink-0" />
          Deleting a router removes it from this console only. No configuration
          on the VyOS device is changed. The mock driver is intended for demos
          and tests.
        </div>
      )}

      {formOpen && (
        <RouterFormDialog
          key={editing?.id ?? "create"}
          open={formOpen}
          onOpenChange={setFormOpen}
          router={editing}
          onSaved={(saved, created) => {
            if (created) selectRouter(saved.id);
          }}
        />
      )}

      <RouterTestDialog
        open={!!testTarget}
        onOpenChange={(open) => {
          if (!open) setTestTarget(null);
        }}
        router={testTarget}
        onResult={(routerId, info) =>
          setTestResults((current) => ({ ...current, [routerId]: info }))
        }
      />

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open && !deleteRouter.isPending) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {deleteTarget?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              This removes the router from the control plane, including its
              stored API key and BGP views. The device configuration is not
              touched. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteRouter.isPending && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Spinner /> Removing router…
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteRouter.isPending}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleteRouter.isPending}
              onClick={(event) => {
                event.preventDefault();
                void handleDelete();
              }}
            >
              <Trash2 className="size-4" /> Delete router
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
