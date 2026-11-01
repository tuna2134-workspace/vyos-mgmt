import * as React from "react";

import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Flat metric strip: hairline dividers only, no per-metric cards. Use this for
 * page-level KPIs so the content stays visually quieter than the data tables.
 */
export function StatStrip({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-2 gap-px border-y border-border/70 bg-border/60 xl:grid-cols-4",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  icon: Icon,
  loading,
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
  loading?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0 bg-background px-4 py-4 sm:px-5", className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
          {label}
        </span>
        {Icon && <Icon className="size-3.5 shrink-0 text-muted-foreground/70" />}
      </div>
      {loading ? (
        <Skeleton className="my-1.5 h-7 w-20" />
      ) : (
        <p className="mt-1.5 truncate text-2xl leading-none font-semibold tracking-tight tabular-nums">
          {value}
        </p>
      )}
      {hint && <div className="mt-2 text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  );
}
