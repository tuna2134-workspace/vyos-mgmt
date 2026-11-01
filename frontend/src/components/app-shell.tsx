"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ChevronRight, Menu, PanelLeft } from "lucide-react";

import { useAuth } from "@/lib/auth";
import { RouterProvider } from "@/lib/router-context";
import {
  FEATURE_MODULES,
  ROUTE_LABELS,
  isNavActive,
  moduleForPath,
} from "@/features/registry";
import { cn } from "@/lib/utils";
import { BootScreen } from "@/components/states";
import { ConnectionIndicator } from "@/components/connection-indicator";
import { SidebarContent } from "@/components/sidebar";
import { ThemeToggle } from "@/components/theme-toggle";
import { UserMenu } from "@/components/user-menu";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

function normalize(pathname: string): string {
  if (pathname === "/") return "/";
  return pathname.endsWith("/") ? pathname : `${pathname}/`;
}

interface Crumb {
  label: string;
  href: string;
}

function breadcrumbFor(pathname: string): Crumb[] {
  if (pathname === "/") return [{ label: "Dashboard", href: "/" }];

  const segments = pathname.split("/").filter(Boolean);
  const crumbs: Crumb[] = [];
  let href = "/";

  for (const segment of segments) {
    href = `${href}${segment}/`;
    let label = ROUTE_LABELS[segment];

    if (!label) {
      const module = FEATURE_MODULES.find((m) => m.href === href);
      if (module) {
        label = module.title;
      } else {
        const navItem = FEATURE_MODULES.flatMap((m) => m.nav).find(
          (item) => item.href === href,
        );
        label = navItem?.title ?? label;
      }
    }

    if (segment === "settings" && href === "/settings/") label = "Settings";
    crumbs.push({
      label: label ?? segment.replace(/-/g, " "),
      href,
    });
  }

  return crumbs;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { status, user } = useAuth();
  const pathname = normalize(usePathname() ?? "/");
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = React.useState(false);

  React.useEffect(() => {
    if (status !== "unauthenticated") return;
    const target = `${window.location.pathname}${window.location.search}`;
    const next =
      target !== "/" && !target.startsWith("/login")
        ? `?next=${encodeURIComponent(target)}`
        : "";
    // Replace rather than push so the back button does not bounce.
    const timeout = window.setTimeout(() => {
      router.replace(`/login/${next}`);
    }, 80);
    return () => window.clearTimeout(timeout);
  }, [status, router]);

  React.useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  React.useEffect(() => {
    const crumbs = breadcrumbFor(pathname);
    const current = crumbs[crumbs.length - 1];
    document.title = current
      ? `${current.label} · VyOS Control`
      : "VyOS Control · Network operations";
  }, [pathname]);

  if (status === "loading") {
    return <BootScreen label="Restoring your session" />;
  }

  if (status === "unauthenticated" || !user) {
    return <BootScreen label="Redirecting to sign in" />;
  }

  const crumbs = breadcrumbFor(pathname);
  const current = crumbs[crumbs.length - 1];
  const module = moduleForPath(pathname);

  return (
    <RouterProvider>
      <a
        href="#main-content"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to main content
      </a>

      <div className="min-h-dvh bg-background">
        <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 border-r border-sidebar-border bg-sidebar lg:block">
          <SidebarContent />
        </aside>

        <div className="flex min-h-dvh flex-col lg:pl-64">
          <header className="sticky top-0 z-30 border-b border-border/70 bg-background/80 backdrop-blur-xl supports-[backdrop-filter]:bg-background/65">
            <div className="flex h-14 items-center gap-2 px-3 sm:px-5 lg:px-8">
              <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8 lg:hidden"
                  onClick={() => setMobileOpen(true)}
                  aria-label="Open navigation menu"
                >
                  <Menu className="size-4" />
                </Button>
                <SheetContent
                  side="left"
                  className="w-[280px] border-sidebar-border bg-sidebar p-0 sm:max-w-[280px]"
                  showCloseButton
                >
                  <SheetHeader className="sr-only">
                    <SheetTitle>Navigation</SheetTitle>
                    <SheetDescription>
                      Main navigation and active router selection
                    </SheetDescription>
                  </SheetHeader>
                  <span className="sr-only">
                    <PanelLeft />
                  </span>
                  <SidebarContent onNavigate={() => setMobileOpen(false)} />
                </SheetContent>
              </Sheet>

              <div className="min-w-0 flex-1">
                <Breadcrumb className="hidden md:block">
                  <BreadcrumbList>
                    {pathname === "/" ? (
                      <BreadcrumbItem>
                        <BreadcrumbPage>Dashboard</BreadcrumbPage>
                      </BreadcrumbItem>
                    ) : (
                      <>
                        <BreadcrumbItem>
                          <BreadcrumbLink asChild>
                            <Link href="/">Dashboard</Link>
                          </BreadcrumbLink>
                        </BreadcrumbItem>
                        {crumbs.map((crumb, index) => {
                          const isLast = index === crumbs.length - 1;
                          return (
                            <React.Fragment key={crumb.href}>
                              <BreadcrumbSeparator />
                              <BreadcrumbItem>
                                {isLast ? (
                                  <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                                ) : (
                                  <BreadcrumbLink asChild>
                                    <Link href={crumb.href}>{crumb.label}</Link>
                                  </BreadcrumbLink>
                                )}
                              </BreadcrumbItem>
                            </React.Fragment>
                          );
                        })}
                      </>
                    )}
                  </BreadcrumbList>
                </Breadcrumb>
                <div className="flex min-w-0 items-center gap-2 md:hidden">
                  <span className="truncate text-sm font-semibold">
                    {current?.label ?? "Dashboard"}
                  </span>
                  {module && current?.label !== module.title && (
                    <span className="text-[10px] text-muted-foreground">
                      / {module.title}
                    </span>
                  )}
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-1.5">
                <ConnectionIndicator />
                <ThemeToggle />
                <div className="mx-1 hidden h-5 w-px bg-border sm:block" />
                <UserMenu />
              </div>
            </div>
            {module && (
              <div className="hidden border-t border-border/50 bg-background/40 md:block">
                <nav
                  aria-label={`${module.title} sections`}
                  className="flex items-center gap-1 overflow-x-auto px-5 lg:px-8"
                >
                  {module.nav.map((item) => {
                    const active = isNavActive(item.href, pathname);
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "relative flex h-9 items-center gap-1.5 px-2.5 text-[12px] font-medium whitespace-nowrap transition-colors",
                          active
                            ? "text-foreground after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-primary"
                            : "text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {item.title}
                        {active && <ChevronRight className="size-3 opacity-0" />}
                      </Link>
                    );
                  })}
                </nav>
              </div>
            )}
          </header>

          <main
            id="main-content"
            className="relative flex-1 px-3 py-5 sm:px-5 lg:px-8 lg:py-7"
          >
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-0 h-64 bg-grid bg-grid-fade opacity-[0.35] dark:opacity-25"
            />
            <div className="relative mx-auto w-full max-w-[1440px] space-y-6">
              {children}
            </div>
          </main>

          <footer className="border-t border-border/50 px-4 py-3.5 text-[11px] text-muted-foreground sm:px-6 lg:px-8">
            <div className="mx-auto flex max-w-[1440px] flex-col items-start justify-between gap-1 sm:flex-row sm:items-center">
              <span>
                VyOS Control · network operations console
              </span>
              <span className="font-mono text-[10px] text-muted-foreground/60">
                {user.role} · {user.username}
              </span>
            </div>
          </footer>
        </div>
      </div>
    </RouterProvider>
  );
}
