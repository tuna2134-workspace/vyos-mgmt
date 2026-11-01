"use client";

import * as React from "react";
import {
  AlertTriangle,
  ArrowRight,
  CircleCheck,
  CircleSlash,
  Info,
  Loader2,
  RefreshCw,
  ShieldAlert,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";
import { errorMessage, isApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { roleAtLeast } from "@/lib/roles";
import type { Driver, Role } from "@/lib/types";

/* -------------------------------------------------------------------------- */
/* Page header                                                                */
/* -------------------------------------------------------------------------- */

export function PageHeader({
  title,
  description,
  actions,
  badge,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  badge?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-4 md:flex-row md:items-start md:justify-between",
        className,
      )}
    >
      <div className="min-w-0 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">
            {title}
          </h1>
          {badge}
        </div>
        {description && (
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {actions}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Alerts                                                                     */
/* -------------------------------------------------------------------------- */

type AlertTone = "error" | "warning" | "info" | "success";

const alertStyles: Record<AlertTone, { wrap: string; icon: LucideIcon }> = {
  error: {
    wrap: "border-destructive/30 bg-destructive/8 text-destructive",
    icon: AlertTriangle,
  },
  warning: {
    wrap: "border-amber-500/30 bg-amber-500/8 text-amber-700 dark:text-amber-300",
    icon: AlertTriangle,
  },
  info: {
    wrap: "border-primary/25 bg-primary/8 text-foreground",
    icon: Info,
  },
  success: {
    wrap: "border-emerald-500/25 bg-emerald-500/8 text-emerald-700 dark:text-emerald-300",
    icon: CircleCheck,
  },
};

export function InlineAlert({
  tone = "info",
  title,
  children,
  className,
  action,
}: {
  tone?: AlertTone;
  title?: string;
  children?: React.ReactNode;
  className?: string;
  action?: React.ReactNode;
}) {
  const style = alertStyles[tone];
  const Icon = style.icon;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-3 rounded-lg border px-3.5 py-3 text-sm",
        style.wrap,
        className,
      )}
    >
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1 space-y-1">
        {title && <p className="font-medium">{title}</p>}
        {children && (
          <div className="text-[13px] leading-relaxed opacity-90">{children}</div>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/** Standard API error block with retry. `message` is shown verbatim. */
export function ErrorPanel({
  error,
  title = "Could not load data",
  onRetry,
  className,
}: {
  error: unknown;
  title?: string;
  onRetry?: () => void;
  className?: string;
}) {
  const requestId = isApiError(error) ? error.requestId : null;
  const code = isApiError(error) ? error.code : null;

  return (
    <div
      className={cn(
        "flex flex-col items-start gap-3 rounded-xl border border-destructive/25 bg-destructive/5 p-5",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-destructive/10 text-destructive">
          <AlertTriangle className="size-4" />
        </div>
        <div className="space-y-1">
          <p className="text-sm font-medium text-foreground">{title}</p>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {errorMessage(error)}
          </p>
          <div className="flex flex-wrap items-center gap-2 pt-0.5">
            {code && (
              <code className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                {code}
              </code>
            )}
            {requestId && (
              <span className="text-[11px] text-muted-foreground/70">
                request {requestId.slice(0, 8)}
              </span>
            )}
          </div>
        </div>
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-3.5" />
          Retry
        </Button>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Empty state                                                                */
/* -------------------------------------------------------------------------- */

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
  compact = false,
}: {
  icon: LucideIcon;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/40 text-center",
        compact ? "px-6 py-8" : "px-6 py-14",
        className,
      )}
    >
      <div className="mb-4 flex size-11 items-center justify-center rounded-xl border border-border/80 bg-background/60 text-muted-foreground shadow-xs">
        <Icon className="size-5" />
      </div>
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      {description && (
        <p className="mt-1.5 max-w-md text-sm leading-relaxed text-muted-foreground">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Loading                                                                    */
/* -------------------------------------------------------------------------- */

export function BootScreen({ label = "Restoring session" }: { label?: string }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-background">
      <div className="relative">
        <div className="absolute inset-0 rounded-xl bg-primary/25 blur-xl" />
        <div className="relative flex size-12 items-center justify-center rounded-xl border border-border bg-card">
          <Loader2 className="size-5 animate-spin text-primary" />
        </div>
      </div>
      <p className="text-sm text-muted-foreground">{label}…</p>
    </div>
  );
}

export function StatSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <Card key={i} className="py-5">
          <CardHeader className="gap-3 px-5">
            <div className="flex items-center justify-between">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="size-7 rounded-md" />
            </div>
            <Skeleton className="h-8 w-20" />
            <Skeleton className="h-3 w-32" />
          </CardHeader>
        </Card>
      ))}
    </div>
  );
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Skeleton className="h-9 w-full max-w-sm" />
        <Skeleton className="h-9 w-28" />
      </div>
      <div className="overflow-hidden rounded-xl border">
        <div className="flex items-center gap-4 border-b bg-muted/40 px-4 py-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-3 flex-1" />
          ))}
        </div>
        {Array.from({ length: rows }).map((_, row) => (
          <div
            key={row}
            className="flex items-center gap-4 border-b px-4 py-3.5 last:border-0"
          >
            {Array.from({ length: 5 }).map((_, col) => (
              <Skeleton
                key={col}
                className={cn("h-4 flex-1", col === 0 && "max-w-40")}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function CardSkeletonGrid({ count = 4 }: { count?: number }) {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i}>
          <CardHeader className="gap-3">
            <div className="flex items-center justify-between">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-5 w-16 rounded-full" />
            </div>
            <Skeleton className="h-3 w-44" />
          </CardHeader>
          <CardContent className="space-y-3">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-4/5" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-4 animate-spin", className)} />;
}

/* -------------------------------------------------------------------------- */
/* Badges / indicators                                                        */
/* -------------------------------------------------------------------------- */

const dotTones = {
  success: "bg-emerald-500",
  danger: "bg-destructive",
  warning: "bg-amber-500",
  muted: "bg-muted-foreground/50",
  primary: "bg-primary",
} as const;

export function StatusDot({
  tone = "muted",
  pulse = false,
  className,
}: {
  tone?: keyof typeof dotTones;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block size-2 shrink-0 rounded-full",
        dotTones[tone],
        pulse && "animate-pulse-dot",
        className,
      )}
    />
  );
}

export function DriverBadge({ driver }: { driver: Driver }) {
  return (
    <Badge
      variant="outline"
      className="gap-1.5 border-border/80 bg-background/60 font-mono text-[10px] tracking-wide uppercase"
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          driver === "mock" ? "bg-amber-500" : "bg-primary",
        )}
      />
      {driver}
    </Badge>
  );
}

const roleVariants: Record<Role, "default" | "secondary" | "warning"> = {
  admin: "default",
  operator: "secondary",
  viewer: "secondary",
};

export function RoleBadge({ role }: { role: Role }) {
  return (
    <Badge variant={roleVariants[role]} className="capitalize">
      {role}
    </Badge>
  );
}

export function PeerStateBadge({ state }: { state: string }) {
  const normalized = state.toLowerCase();
  const variant =
    normalized === "established"
      ? "success"
      : normalized === "idle"
        ? "destructive"
        : normalized === "active" ||
            normalized === "connect" ||
            normalized === "opensent" ||
            normalized === "openconfirm"
          ? "warning"
          : "muted";

  return (
    <Badge variant={variant} className="gap-1.5 font-mono">
      <span
        className={cn(
          "size-1.5 rounded-full",
          normalized === "established"
            ? "bg-emerald-500"
            : normalized === "idle"
              ? "bg-destructive"
              : normalized === "active" ||
                  normalized === "connect" ||
                  normalized === "opensent" ||
                  normalized === "openconfirm"
                ? "bg-amber-500"
                : "bg-muted-foreground",
        )}
      />
      {state || "Unknown"}
    </Badge>
  );
}

export function VerdictBadge({ ok, labels }: { ok: boolean; labels?: [string, string] }) {
  return (
    <Badge variant={ok ? "success" : "destructive"} className="gap-1.5">
      <span
        className={cn(
          "size-1.5 rounded-full",
          ok ? "bg-emerald-500" : "bg-destructive",
        )}
      />
      {ok ? (labels?.[0] ?? "Success") : (labels?.[1] ?? "Failed")}
    </Badge>
  );
}

/* -------------------------------------------------------------------------- */
/* Permissions                                                                */
/* -------------------------------------------------------------------------- */

export function RequireRole({
  role,
  children,
}: {
  role: Role;
  children: React.ReactNode;
}) {
  const { user } = useAuth();

  if (!roleAtLeast(user?.role, role)) {
    return (
      <div className="mx-auto flex max-w-xl flex-col items-center py-16 text-center">
        <div className="mb-4 flex size-12 items-center justify-center rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-300">
          <ShieldAlert className="size-5" />
        </div>
        <h2 className="text-lg font-semibold">Insufficient permissions</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          This area requires the <span className="font-medium uppercase">{role}</span>{" "}
          role. Ask an administrator if you need access.
        </p>
        <Button asChild variant="outline" className="mt-6">
          <a href="/">
            Back to dashboard <ArrowRight className="size-4" />
          </a>
        </Button>
      </div>
    );
  }

  return <>{children}</>;
}

export function ReadOnlyNote({ role }: { role?: Role }) {
  if (role && role !== "viewer") return null;
  return (
    <InlineAlert tone="info" title="Read-only access">
      Your account can inspect this configuration but cannot change it. BGP
      writes require the operator or administrator role.
    </InlineAlert>
  );
}

export function ForbiddenInline() {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
      <CircleSlash className="size-3.5" />
      Your role does not permit this action.
    </div>
  );
}
