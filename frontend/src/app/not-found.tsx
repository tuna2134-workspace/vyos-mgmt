import Link from "next/link";
import { ArrowLeft, Compass } from "lucide-react";

import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center overflow-hidden px-6 text-center">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-grid bg-grid-fade opacity-40"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute top-1/4 left-1/2 size-[420px] -translate-x-1/2 rounded-full bg-primary/10 blur-[120px]"
      />
      <div className="relative flex flex-col items-center">
        <Logo />
        <div className="mt-10 flex size-14 items-center justify-center rounded-2xl border border-border bg-card shadow-lg">
          <Compass className="size-6 text-primary" />
        </div>
        <p className="mt-6 font-mono text-xs tracking-[0.3em] text-muted-foreground">
          ERROR 404
        </p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
          This route is not in the table
        </h1>
        <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
          The page you requested does not exist, or the static export has not
          published it. Check the address or return to the dashboard.
        </p>
        <div className="mt-7 flex flex-wrap items-center justify-center gap-2">
          <Button asChild>
            <Link href="/">
              <ArrowLeft className="size-4" />
              Back to dashboard
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/bgp/">Open BGP</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
