"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ChevronDown,
  LogOut,
  Settings,
  ShieldCheck,
  UsersRound,
} from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth";
import { initials } from "@/lib/format";
import { roleAtLeast } from "@/lib/roles";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function UserMenu() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const [signingOut, setSigningOut] = React.useState(false);

  if (!user) return null;

  const handleLogout = async () => {
    setSigningOut(true);
    try {
      await logout();
      toast.success("Signed out");
      router.replace("/login/");
    } finally {
      setSigningOut(false);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          className="h-9 gap-2 px-1.5 sm:px-2"
          aria-label={`Account menu for ${user.username}`}
        >
          <Avatar className="size-7 border border-border">
            <AvatarFallback className="bg-primary/15 text-[10px] font-semibold text-primary">
              {initials(user.username)}
            </AvatarFallback>
          </Avatar>
          <span className="hidden max-w-28 truncate text-[13px] font-medium sm:inline">
            {user.username}
          </span>
          <ChevronDown className="hidden size-3.5 text-muted-foreground sm:block" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="py-2">
          <div className="flex items-center gap-2.5">
            <Avatar className="size-8">
              <AvatarFallback className="bg-primary/15 text-[11px] font-semibold text-primary">
                {initials(user.username)}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0 space-y-0.5">
              <p className="truncate text-sm font-medium text-foreground">
                {user.username}
              </p>
              <p className="truncate text-[11px] font-normal text-muted-foreground">
                {user.email ?? "No email set"}
              </p>
            </div>
          </div>
          <Badge variant="secondary" className="mt-2 gap-1 capitalize">
            <ShieldCheck className="size-3" />
            {user.role}
          </Badge>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/settings/">
            <Settings /> Account settings
          </Link>
        </DropdownMenuItem>
        {roleAtLeast(user.role, "admin") && (
          <DropdownMenuItem asChild>
            <Link href="/settings/users/">
              <UsersRound /> User management
            </Link>
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          variant="destructive"
          disabled={signingOut}
          onSelect={(event) => {
            event.preventDefault();
            void handleLogout();
          }}
        >
          <LogOut />
          {signingOut ? "Signing out…" : "Sign out"}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
