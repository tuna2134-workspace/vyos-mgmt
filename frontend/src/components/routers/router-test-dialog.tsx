"use client";

import * as React from "react";
import { Loader2, RadioTower, RefreshCw, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import { ApiError, errorMessage } from "@/lib/api";
import { useTestRouter } from "@/lib/queries";
import { formatLatency } from "@/lib/format";
import type { Router, SystemInfo } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DriverBadge, InlineAlert, Spinner, StatusDot } from "@/components/states";

export function RouterTestDialog({
  open,
  onOpenChange,
  router,
  onResult,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  router: Router | null;
  onResult?: (routerId: string, info: SystemInfo) => void;
}) {
  const testMutation = useTestRouter();
  const [state, setState] = React.useState<{
    loading: boolean;
    info: SystemInfo | null;
    error: unknown;
  }>({ loading: false, info: null, error: null });
  const requestRef = React.useRef(0);

  const run = React.useCallback(async () => {
    if (!router) return;
    const requestId = ++requestRef.current;
    setState({ loading: true, info: null, error: null });
    try {
      const info = await testMutation.mutateAsync(router.id);
      if (requestRef.current !== requestId) return;
      setState({ loading: false, info, error: null });
      onResult?.(router.id, info);
      if (info.reachable) {
        toast.success(`Connection to ${router.name} is healthy`, {
          description: `Latency ${formatLatency(info.latency_ms)} · ${info.version ?? "version unknown"}`,
        });
      } else {
        toast.error(`Could not reach ${router.name}`, {
          description: info.error ?? "The device did not respond.",
        });
      }
    } catch (error) {
      if (requestRef.current !== requestId) return;
      setState({ loading: false, info: null, error });
      toast.error("Connection test failed", {
        description: errorMessage(error),
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router?.id]);

  React.useEffect(() => {
    if (open && router) {
      void run();
    }
    if (!open) {
      requestRef.current += 1;
      setState({ loading: false, info: null, error: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, router?.id]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <RadioTower className="size-4 text-primary" />
            Connection test
          </DialogTitle>
          <DialogDescription>
            Probing {router?.name} at{" "}
            <span className="font-mono">
              {router?.protocol}://{router?.host}:{router?.port}
            </span>
          </DialogDescription>
        </DialogHeader>

        {state.loading ? (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-muted/20 py-10">
            <div className="flex size-10 items-center justify-center rounded-full border border-primary/25 bg-primary/10 text-primary">
              <Spinner className="size-5" />
            </div>
            <p className="text-sm font-medium">Contacting device…</p>
            <p className="text-xs text-muted-foreground">
              Fetching system identity and version
            </p>
          </div>
        ) : state.error ? (
          <div className="space-y-3">
            <InlineAlert
              tone="error"
              title={
                state.error instanceof ApiError && state.error.isNetworkError
                  ? "API unreachable"
                  : "Connection test failed"
              }
            >
              {errorMessage(state.error)}
            </InlineAlert>
            <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
              <TriangleAlert className="size-3.5 shrink-0" />
              Check the host, port and protocol, then confirm the router allows
              API access from this control plane.
            </div>
          </div>
        ) : state.info ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-lg border border-border px-3.5 py-3">
              <div className="flex items-center gap-2">
                <StatusDot
                  tone={state.info.reachable ? "success" : "danger"}
                  pulse={state.info.reachable}
                />
                <span className="text-sm font-medium">
                  {state.info.reachable ? "Reachable" : "Unreachable"}
                </span>
              </div>
              <DriverBadge driver={state.info.driver} />
            </div>

            {state.info.reachable ? (
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border/60">
                <InfoCell label="Hostname" value={state.info.hostname ?? "—"} mono />
                <InfoCell
                  label="Latency"
                  value={formatLatency(state.info.latency_ms)}
                  mono
                  accent
                />
                <InfoCell
                  label="Version"
                  value={state.info.version ?? "Unknown"}
                  className="col-span-2"
                  mono
                />
                <InfoCell
                  label="Uptime"
                  value={state.info.uptime || "—"}
                  className="col-span-2"
                  mono
                />
              </dl>
            ) : (
              <InlineAlert tone="error" title="Router did not respond">
                {state.info.error ??
                  "The device returned an error. Check the API service and credentials."}
              </InlineAlert>
            )}
          </div>
        ) : null}

        <DialogFooter>
          <Button variant="outline" onClick={() => void run()} disabled={state.loading}>
            {state.loading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCw className="size-4" />
            )}
            Test again
          </Button>
          <Button onClick={() => onOpenChange(false)}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function InfoCell({
  label,
  value,
  mono,
  accent,
  className,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  accent?: boolean;
  className?: string;
}) {
  return (
    <div className={`bg-card px-3.5 py-2.5 ${className ?? ""}`}>
      <dt className="text-[9px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
        {label}
      </dt>
      <dd
        className={`mt-0.5 truncate text-[12px] font-medium ${mono ? "font-mono" : ""} ${
          accent ? "text-emerald-600 dark:text-emerald-300" : ""
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
