"use client";

import { useHealth } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { StatusDot } from "@/components/states";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function ConnectionIndicator({
  className,
  withLabel = true,
}: {
  className?: string;
  withLabel?: boolean;
}) {
  const health = useHealth();

  const state = health.isLoading
    ? { tone: "muted" as const, label: "Checking API", pulse: false }
    : health.isError
      ? { tone: "danger" as const, label: "API unreachable", pulse: false }
      : health.data?.status === "degraded" || health.data?.status === "error"
        ? { tone: "warning" as const, label: health.data?.status, pulse: true }
        : { tone: "success" as const, label: "API online", pulse: true };

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div
          className={cn(
            "flex h-8 cursor-default items-center gap-2 rounded-full border border-border/70 bg-background/50 px-2.5 text-[11px] font-medium text-muted-foreground",
            className,
          )}
          aria-live="polite"
        >
          <StatusDot tone={state.tone} pulse={state.pulse} />
          {withLabel && <span className="hidden sm:inline">{state.label}</span>}
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-64">
        <div className="space-y-1">
          <p className="font-medium">{state.label}</p>
          {health.data ? (
            <p className="text-[11px] opacity-80">
              VyOS Control {health.data.version} · {health.data.environment} ·
              database {health.data.database}
            </p>
          ) : health.isError ? (
            <p className="text-[11px] opacity-80">
              The browser could not reach the management API. Authentication
              calls will fail until it recovers.
            </p>
          ) : (
            <p className="text-[11px] opacity-80">Contacting management API…</p>
          )}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
