"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { PLATFORM_NAV, isNavActive, modulesForRole } from "@/features/registry";
import { useAuth } from "@/lib/auth";
import { useHealth } from "@/lib/queries";
import { roleAtLeast } from "@/lib/roles";
import { cn } from "@/lib/utils";
import { Logo } from "@/components/logo";
import { RouterSwitcher } from "@/components/router-switcher";
import { StatusDot } from "@/components/states";
import { Badge } from "@/components/ui/badge";

function NavLink({
  href,
  children,
  active,
  className,
  onNavigate,
}: {
  href: string;
  children: React.ReactNode;
  active: boolean;
  className?: string;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent/60 hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:outline-none",
        active &&
          "bg-sidebar-accent text-sidebar-foreground before:absolute before:top-1/2 before:left-0 before:h-4 before:w-0.5 before:-translate-y-1/2 before:rounded-full before:bg-primary",
        className,
      )}
    >
      {children}
    </Link>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-2.5 pt-5 pb-1.5 text-[10px] font-semibold tracking-[0.16em] text-muted-foreground/80 uppercase">
      {children}
    </p>
  );
}

export function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { user } = useAuth();
  const health = useHealth();
  const modules = React.useMemo(() => modulesForRole(user?.role), [user?.role]);

  const workspace = PLATFORM_NAV.filter(
    (item) => item.href === "/" || item.href === "/routers/",
  );
  const administration = PLATFORM_NAV.filter(
    (item) =>
      item.href !== "/" &&
      item.href !== "/routers/" &&
      (!item.roles || (user ? roleAtLeast(user.role, item.roles[0]) : false)),
  );

  return (
    <div className="flex h-full min-h-0 flex-col bg-sidebar text-sidebar-foreground">
      <div className="flex h-16 shrink-0 items-center border-b border-sidebar-border/70 px-4">
        <Link
          href="/"
          onClick={onNavigate}
          className="rounded-md focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:outline-none"
          aria-label="VyOS Control dashboard"
        >
          <Logo />
        </Link>
      </div>

      <div className="shrink-0 px-3 py-3">
        <RouterSwitcher />
      </div>

      <nav
        aria-label="Primary"
        className="min-h-0 flex-1 overflow-y-auto px-3 pb-4"
      >
        <SectionLabel>Workspace</SectionLabel>
        <div className="space-y-0.5">
          {workspace.map((item) => (
            <NavLink
              key={item.href}
              href={item.href}
              active={isNavActive(item.href, pathname)}
              onNavigate={onNavigate}
            >
              <item.icon className="size-4 text-muted-foreground group-data-[active=true]:text-primary" />
              {item.title}
            </NavLink>
          ))}
        </div>

        {modules.map((module) => (
          <div key={module.key}>
            <SectionLabel>{module.title}</SectionLabel>
            <div className="space-y-0.5">
              {module.nav.map((item) => {
                const active = isNavActive(item.href, pathname);
                return (
                  <NavLink
                    key={item.href}
                    href={item.href}
                    active={active}
                    onNavigate={onNavigate}
                  >
                    {item.icon ? (
                      <item.icon
                        className={cn(
                          "size-4",
                          active ? "text-primary" : "text-muted-foreground",
                        )}
                      />
                    ) : (
                      <span className="size-4" />
                    )}
                    <span className="truncate">{item.title}</span>
                    {module.status === "coming-soon" && (
                      <Badge variant="muted" className="ml-auto text-[9px]">
                        Soon
                      </Badge>
                    )}
                  </NavLink>
                );
              })}
            </div>
          </div>
        ))}

        {administration.length > 0 && (
          <>
            <SectionLabel>Administration</SectionLabel>
            <div className="space-y-0.5">
              {administration.map((item) => (
                <NavLink
                  key={item.href}
                  href={item.href}
                  active={isNavActive(item.href, pathname)}
                  onNavigate={onNavigate}
                >
                  <item.icon className="size-4 text-muted-foreground" />
                  {item.title}
                </NavLink>
              ))}
            </div>
          </>
        )}
      </nav>

      <div className="shrink-0 border-t border-sidebar-border/70 px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <StatusDot
              tone={
                health.isLoading
                  ? "muted"
                  : health.isError
                    ? "danger"
                    : "success"
              }
              pulse={!health.isLoading && !health.isError}
            />
            {health.isLoading
              ? "Checking API"
              : health.isError
                ? "API offline"
                : "API operational"}
          </div>
          <span className="font-mono text-[10px] text-muted-foreground/70">
            {health.data?.version ? `v${health.data.version}` : "v1"}
          </span>
        </div>
      </div>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 border-r border-sidebar-border bg-sidebar lg:block">
      <SidebarContent />
    </aside>
  );
}

