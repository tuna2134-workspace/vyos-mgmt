"use client";

import * as React from "react";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clipboard,
  RefreshCw,
  ScrollText,
} from "lucide-react";
import { toast } from "sonner";

import { useAudit } from "@/lib/queries";
import { formatDateTime, formatRelative, humanizeAction } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
  PageHeader,
  RequireRole,
  TableSkeleton,
} from "@/components/states";

function AuditAdmin() {
  const [limit, setLimit] = React.useState(20);
  const [offset, setOffset] = React.useState(0);
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const audit = useAudit(limit, offset);

  const total = audit.data?.total ?? 0;
  const items = audit.data?.items ?? [];
  const page = Math.floor(offset / limit) + 1;
  const pageCount = Math.max(1, Math.ceil(total / limit));
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + items.length, total);

  const toggle = (id: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const changeLimit = (value: string) => {
    setLimit(Number(value));
    setOffset(0);
  };

  const copyDetails = async (details: Record<string, unknown> | null) => {
    if (!details) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(details, null, 2));
      toast.success("Details copied");
    } catch {
      toast.error("Clipboard unavailable");
    }
  };

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Immutable record of console activity across routers, BGP objects and accounts."
        badge={
          <Badge variant="outline" className="font-mono text-[10px]">
            {total} {total === 1 ? "event" : "events"}
          </Badge>
        }
        actions={
          <>
            <Select value={String(limit)} onValueChange={changeLimit}>
              <SelectTrigger size="sm" className="h-8 w-[128px] text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="20">20 per page</SelectItem>
                <SelectItem value="50">50 per page</SelectItem>
                <SelectItem value="100">100 per page</SelectItem>
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void audit.refetch()}
              disabled={audit.isFetching}
            >
              <RefreshCw
                className={audit.isFetching ? "size-3.5 animate-spin" : "size-3.5"}
              />
              Refresh
            </Button>
          </>
        }
      />

      {audit.isError ? (
        <ErrorPanel
          title="Could not load the audit log"
          error={audit.error}
          onRetry={() => void audit.refetch()}
        />
      ) : audit.isLoading ? (
        <TableSkeleton rows={8} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={ScrollText}
          title="No audit events yet"
          description="Configuration changes, connection tests, sign-ins and account updates will appear here."
        />
      ) : (
        <Card variant="surface" className="gap-0 overflow-hidden py-0">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-sm">
              <thead>
                <tr className="border-b border-border/60 bg-muted/25">
                  <th className="w-8 px-3 py-2.5" aria-label="Expand" />
                  {["Time", "Actor", "Action", "Router", "Resource", "Status"].map(
                    (label) => (
                      <th
                        key={label}
                        className="px-4 py-2.5 text-left text-[10px] font-semibold tracking-[0.12em] whitespace-nowrap text-muted-foreground uppercase"
                      >
                        {label}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {items.map((entry) => {
                  const isOpen = expanded.has(entry.id);
                  return (
                    <React.Fragment key={entry.id}>
                      <tr
                        className={cn(
                          "border-b border-border/60 transition-colors hover:bg-muted/25",
                          isOpen && "bg-muted/20",
                        )}
                      >
                        <td className="px-3 py-3">
                          <button
                            type="button"
                            onClick={() => toggle(entry.id)}
                            aria-expanded={isOpen}
                            aria-label={`${isOpen ? "Hide" : "Show"} details for ${entry.action}`}
                            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                          >
                            <ChevronDown
                              className={cn(
                                "size-3.5 transition-transform",
                                isOpen && "rotate-180",
                              )}
                            />
                          </button>
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-[11px] font-medium">
                            {formatRelative(entry.created_at)}
                          </p>
                          <p className="font-mono text-[9px] text-muted-foreground">
                            {formatDateTime(entry.created_at)}
                          </p>
                        </td>
                        <td className="px-4 py-3 font-mono text-[11px]">
                          {entry.actor_username}
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-[11px] font-medium">
                            {humanizeAction(entry.action)}
                          </p>
                          <p className="font-mono text-[9px] text-muted-foreground">
                            {entry.action}
                          </p>
                        </td>
                        <td className="px-4 py-3 text-[11px]">
                          {entry.router_name ?? (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-[10px] text-muted-foreground">
                            {entry.resource_type ?? "—"}
                          </p>
                          {entry.resource_id && (
                            <p className="max-w-[180px] truncate font-mono text-[9px]">
                              {entry.resource_id}
                            </p>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <Badge
                            variant={
                              entry.status === "success"
                                ? "success"
                                : "destructive"
                            }
                            className="text-[9px]"
                          >
                            {entry.status}
                          </Badge>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="border-b border-border/60 bg-muted/10">
                          <td colSpan={7} className="px-4 py-3">
                            <div className="grid gap-3 lg:grid-cols-[1.6fr_1fr]">
                              <div className="min-w-0">
                                <div className="mb-1.5 flex items-center justify-between">
                                  <p className="text-[9px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
                                    Details
                                  </p>
                                  {entry.details && (
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="h-6 gap-1 px-1.5 text-[10px]"
                                      onClick={() => void copyDetails(entry.details)}
                                    >
                                      <Clipboard className="size-3" /> Copy JSON
                                    </Button>
                                  )}
                                </div>
                                <pre className="max-h-56 overflow-auto rounded-lg border border-border/70 bg-background/60 p-3 font-mono text-[10px] leading-relaxed">
                                  {entry.details
                                    ? JSON.stringify(entry.details, null, 2)
                                    : "No additional details recorded."}
                                </pre>
                              </div>
                              <dl className="space-y-2 rounded-lg border border-border/60 bg-card p-3 text-[10px]">
                                {[
                                  ["Event ID", entry.id],
                                  ["Request ID", entry.request_id ?? "—"],
                                  ["Resource", entry.resource_type ?? "—"],
                                  ["Resource ID", entry.resource_id ?? "—"],
                                  ["Router ID", entry.router_id ?? "—"],
                                  ["Timestamp", entry.created_at],
                                ].map(([label, value]) => (
                                  <div
                                    key={label}
                                    className="flex items-start justify-between gap-3"
                                  >
                                    <dt className="text-muted-foreground">
                                      {label}
                                    </dt>
                                    <dd className="max-w-[68%] truncate text-right font-mono">
                                      {value}
                                    </dd>
                                  </div>
                                ))}
                              </dl>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="flex flex-col items-start justify-between gap-3 border-t border-border/70 p-4 sm:flex-row sm:items-center">
            <p className="text-[11px] text-muted-foreground">
              Showing {rangeStart}–{rangeEnd} of {total} events · page {page} of{" "}
              {pageCount}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={offset === 0 || audit.isFetching}
                onClick={() => setOffset(Math.max(0, offset - limit))}
              >
                <ChevronLeft className="size-3.5" /> Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={
                  offset + limit >= total || audit.isFetching
                }
                onClick={() => setOffset(offset + limit)}
              >
                Next <ChevronRight className="size-3.5" />
              </Button>
            </div>
          </div>
        </Card>
      )}

      <p className="text-[11px] text-muted-foreground">
        Audit records are append-only and written by the API. Expand a row for
        the structured change payload and correlation IDs.
      </p>
    </>
  );
}

export default function AuditPage() {
  return (
    <RequireRole role="admin">
      <AuditAdmin />
    </RequireRole>
  );
}
