"use client";

import * as React from "react";
import { usePathname } from "next/navigation";

import { useRouters } from "@/lib/queries";
import type { Router } from "@/lib/types";

const STORAGE_KEY = "vyos-mgmt:selected-router";

interface RouterContextValue {
  routers: Router[];
  selectedId: string | null;
  selectedRouter: Router | null;
  selectRouter: (id: string) => void;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => void;
  hasRouters: boolean;
}

const RouterContext = React.createContext<RouterContextValue | null>(null);

function readStoredId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredId(id: string) {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // localStorage can be unavailable in hardened browsers; selection still
    // works for the current page.
  }
}

function readQueryRouter(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("router");
}

function replaceQueryRouter(id: string | null) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (id) {
    url.searchParams.set("router", id);
  } else {
    url.searchParams.delete("router");
  }
  window.history.replaceState(window.history.state, "", url.toString());
}

export function RouterProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const routersQuery = useRouters();
  const routers = routersQuery.data?.items ?? [];
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  const selectRouter = React.useCallback((id: string) => {
    setSelectedId(id);
    writeStoredId(id);
    replaceQueryRouter(id);
  }, []);

  // Reconcile selection whenever routers arrive or the route changes:
  // explicit ?router=<id> > current selection > localStorage > first router.
  React.useEffect(() => {
    if (!routersQuery.isSuccess) return;

    const available = new Set(routers.map((router) => router.id));
    const queryId = readQueryRouter();
    const storedId = readStoredId();

    if (queryId && available.has(queryId)) {
      if (queryId !== selectedId) {
        setSelectedId(queryId);
        writeStoredId(queryId);
      }
      return;
    }

    if (selectedId && available.has(selectedId)) {
      // Keep shareable links in sync when navigating between module pages,
      // which drop the query string.
      if (queryId !== selectedId) replaceQueryRouter(selectedId);
      return;
    }

    if (storedId && available.has(storedId)) {
      setSelectedId(storedId);
      return;
    }

    const fallback = routers[0]?.id ?? null;
    setSelectedId(fallback);
    if (fallback) writeStoredId(fallback);
    // Keep the URL in sync so links remain shareable.
    if (fallback && queryId !== fallback) replaceQueryRouter(fallback);
  }, [routers, routersQuery.isSuccess, selectedId, pathname]);

  // Browser back/forward can change ?router without a Next navigation.
  React.useEffect(() => {
    const onPopState = () => {
      const queryId = readQueryRouter();
      if (queryId && routers.some((r) => r.id === queryId)) {
        setSelectedId(queryId);
        writeStoredId(queryId);
      }
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [routers]);

  // If the selected router disappears (deleted), fall back gracefully.
  React.useEffect(() => {
    if (!routersQuery.isSuccess || !selectedId) return;
    if (routers.length === 0) {
      setSelectedId(null);
      replaceQueryRouter(null);
      return;
    }
    if (!routers.some((r) => r.id === selectedId)) {
      const fallback = routers[0].id;
      setSelectedId(fallback);
      writeStoredId(fallback);
      replaceQueryRouter(fallback);
    }
  }, [routers, routersQuery.isSuccess, selectedId]);

  const selectedRouter =
    routers.find((router) => router.id === selectedId) ?? null;

  const refetch = React.useCallback(() => {
    void routersQuery.refetch();
  }, [routersQuery]);

  const value = React.useMemo<RouterContextValue>(
    () => ({
      routers,
      selectedId,
      selectedRouter,
      selectRouter,
      isLoading: routersQuery.isLoading,
      isError: routersQuery.isError,
      error: routersQuery.error,
      refetch,
      hasRouters: routers.length > 0,
    }),
    [
      routers,
      selectedId,
      selectedRouter,
      selectRouter,
      routersQuery.isLoading,
      routersQuery.isError,
      routersQuery.error,
      refetch,
    ],
  );

  return (
    <RouterContext.Provider value={value}>{children}</RouterContext.Provider>
  );
}

export function useRouterSelection(): RouterContextValue {
  const context = React.useContext(RouterContext);
  if (!context) {
    throw new Error("useRouterSelection must be used within a RouterProvider");
  }
  return context;
}
