"use client";

import * as React from "react";
import Link from "next/link";
import { Plus, ServerOff } from "lucide-react";

import { useRouterSelection } from "@/lib/router-context";
import type { Router } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorPanel, TableSkeleton } from "@/components/states";

/**
 * Renders the router-dependent part of a feature page: handles router loading,
 * router-list errors and the "no routers" state, and calls children with the
 * selected router.
 *
 * Feature-specific wrappers (e.g. `BgpRouterBoundary`) only need to customize
 * the empty-state copy.
 */
export function RouterBoundary({
  children,
  loading,
  emptyDescription = "Add a VyOS device before configuring or monitoring it.",
}: {
  children: (router: Router) => React.ReactNode;
  loading?: React.ReactNode;
  emptyDescription?: React.ReactNode;
}) {
  const {
    routers,
    selectedRouter,
    isLoading,
    isError,
    error,
    refetch,
  } = useRouterSelection();

  if (isLoading) return <>{loading ?? <TableSkeleton />}</>;

  if (isError) {
    return (
      <ErrorPanel
        title="Could not load routers"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }

  if (routers.length === 0) {
    return (
      <EmptyState
        icon={ServerOff}
        title="No routers registered"
        description={emptyDescription}
        action={
          <Button asChild>
            <Link href="/routers/">
              <Plus className="size-4" /> Add a router
            </Link>
          </Button>
        }
      />
    );
  }

  if (!selectedRouter) {
    return <>{loading ?? <TableSkeleton />}</>;
  }

  // Remount page content when the active router changes. This resets dialogs,
  // filters and form state so a submission can never target the previous
  // router by accident.
  return (
    <React.Fragment key={selectedRouter.id}>
      {children(selectedRouter)}
    </React.Fragment>
  );
}
