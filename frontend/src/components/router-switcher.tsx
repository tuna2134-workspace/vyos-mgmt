"use client";

import Link from "next/link";
import { Router as RouterIcon, Server, Settings2 } from "lucide-react";

import { useRouterSelection } from "@/lib/router-context";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";

export function RouterSwitcher({ compact = false }: { compact?: boolean }) {
  const {
    routers,
    selectedId,
    selectedRouter,
    selectRouter,
    isLoading,
    isError,
    hasRouters,
  } = useRouterSelection();

  if (isLoading) {
    return (
      <div className="space-y-2">
        {!compact && <Skeleton className="h-3 w-16" />}
        <Skeleton className="h-10 w-full rounded-lg" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="rounded-lg border border-destructive/25 bg-destructive/5 px-3 py-2.5 text-xs text-muted-foreground">
        Router list unavailable.
      </div>
    );
  }

  if (!hasRouters) {
    return (
      <div className="rounded-lg border border-dashed border-sidebar-border bg-sidebar-accent/40 px-3 py-3">
        <div className="flex items-center gap-2 text-xs font-medium text-sidebar-foreground">
          <Server className="size-3.5" /> No routers yet
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          Add a VyOS router to start monitoring BGP.
        </p>
        <Button
          asChild
          size="sm"
          variant="outline"
          className="mt-2.5 h-7 w-full text-[11px]"
        >
          <Link href="/routers/">Add router</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      {!compact && (
        <div className="flex items-center justify-between px-0.5">
          <span className="text-[10px] font-semibold tracking-[0.16em] text-muted-foreground uppercase">
            Active router
          </span>
          <Link
            href="/routers/"
            className="flex items-center gap-1 text-[10px] font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            <Settings2 className="size-3" />
            Manage
          </Link>
        </div>
      )}
      <Select
        value={selectedId ?? undefined}
        onValueChange={selectRouter}
        disabled={routers.length === 0}
      >
        <SelectTrigger
          aria-label="Select active router"
          className="h-10 w-full border-sidebar-border bg-sidebar-accent/40 text-left text-[13px] font-medium shadow-none hover:bg-sidebar-accent/70"
        >
          <div className="flex min-w-0 items-center gap-2">
            <RouterIcon className="size-4 shrink-0 text-primary" />
            <SelectValue placeholder="Select a router" />
          </div>
        </SelectTrigger>
        <SelectContent align="start" className="min-w-64">
          {routers.map((router) => (
            <SelectItem key={router.id} value={router.id} className="py-2">
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-[13px] font-medium">
                  {router.name}
                </span>
                <span className="truncate font-mono text-[10px] text-muted-foreground">
                  {router.protocol}://{router.host}:{router.port} · {router.driver}
                </span>
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {selectedRouter && !compact && (
        <div className="flex items-center justify-between px-0.5 text-[10px] text-muted-foreground">
          <span className="truncate font-mono">{selectedRouter.host}</span>
          <span className="capitalize">{selectedRouter.driver}</span>
        </div>
      )}
    </div>
  );
}
