"use client";

import * as React from "react";
import Link from "next/link";
import { RotateCcw, TriangleAlert } from "lucide-react";

import { errorMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";

export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    // Keep a console breadcrumb for ops; the UI stays friendly.
    console.error("Unhandled application error", error);
  }, [error]);

  return (
    <div className="flex min-h-dvh items-center justify-center px-6">
      <div className="w-full max-w-md rounded-xl border border-destructive/25 bg-card p-6 shadow-xl">
        <div className="flex size-10 items-center justify-center rounded-lg bg-destructive/10 text-destructive">
          <TriangleAlert className="size-5" />
        </div>
        <h1 className="mt-4 text-lg font-semibold">The console hit an error</h1>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
          {errorMessage(error)}
        </p>
        {error.digest && (
          <p className="mt-2 font-mono text-[11px] text-muted-foreground/70">
            digest {error.digest}
          </p>
        )}
        <div className="mt-5 flex gap-2">
          <Button onClick={reset}>
            <RotateCcw className="size-4" /> Try again
          </Button>
          <Button variant="outline" asChild>
            <Link href="/">Dashboard</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
