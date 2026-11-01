"use client";

import * as React from "react";
import {
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  UserCheck,
  UserRound,
  UsersRound,
  UserX,
} from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/lib/auth";
import { useDeleteUser, useUsers } from "@/lib/queries";
import { errorMessage } from "@/lib/api";
import { formatDate, formatDateTime, formatRelative, initials } from "@/lib/format";
import type { User } from "@/lib/types";
import { UserFormDialog } from "@/components/users/user-form-dialog";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Stat, StatStrip } from "@/components/ui/stat";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  EmptyState,
  ErrorPanel,
  InlineAlert,
  PageHeader,
  RequireRole,
  RoleBadge,
  Spinner,
  TableSkeleton,
} from "@/components/states";

function UsersAdmin() {
  const { user, refresh } = useAuth();
  const usersQuery = useUsers();
  const deleteUser = useDeleteUser();
  const [search, setSearch] = React.useState("");
  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<User | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<User | null>(null);

  const users = usersQuery.data?.items ?? [];
  const activeAdmins = users.filter(
    (candidate) => candidate.role === "admin" && candidate.is_active,
  ).length;

  const filtered = React.useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return users;
    return users.filter((candidate) =>
      [candidate.username, candidate.email ?? "", candidate.role]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [users, search]);

  const handleDelete = async () => {
    if (!deleteTarget || !user) return;
    try {
      await deleteUser.mutateAsync(deleteTarget.id);
      toast.success("User deleted", {
        description: `${deleteTarget.username} can no longer sign in.`,
      });
      setDeleteTarget(null);
    } catch (error) {
      toast.error("Could not delete user", {
        description: errorMessage(error),
      });
    }
  };

  const isLastActiveAdmin = (candidate: User) =>
    candidate.role === "admin" &&
    candidate.is_active &&
    activeAdmins <= 1;

  const deletingSelf = !!deleteTarget && deleteTarget.id === user?.id;
  const deletingLastAdmin =
    !!deleteTarget && isLastActiveAdmin(deleteTarget);
  const deleteBlocked = deletingSelf || deletingLastAdmin;

  return (
    <>
      <PageHeader
        title="User management"
        description="Console accounts and roles. The API blocks deleting yourself or removing the last active administrator."
        badge={
          <Badge variant="outline" className="font-mono text-[10px]">
            {users.length} {users.length === 1 ? "account" : "accounts"}
          </Badge>
        }
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void usersQuery.refetch()}
              disabled={usersQuery.isFetching}
            >
              <RefreshCw
                className={
                  usersQuery.isFetching ? "size-3.5 animate-spin" : "size-3.5"
                }
              />
              Refresh
            </Button>
            <Button
              size="sm"
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              <Plus className="size-4" /> Create user
            </Button>
          </>
        }
      />

      <StatStrip className="grid-cols-1 sm:grid-cols-3 xl:grid-cols-3">
        <Stat
          label="Accounts"
          value={users.length}
          hint="Console users"
          icon={UsersRound}
        />
        <Stat
          label="Active admins"
          value={activeAdmins}
          hint="Accounts with full access"
          icon={ShieldCheck}
        />
        <Stat
          label="Active accounts"
          value={users.filter((candidate) => candidate.is_active).length}
          hint="Can sign in"
          icon={UserCheck}
        />
      </StatStrip>

      {usersQuery.isError ? (
        <ErrorPanel
          title="Could not load users"
          error={usersQuery.error}
          onRetry={() => void usersQuery.refetch()}
        />
      ) : usersQuery.isLoading ? (
        <TableSkeleton rows={5} />
      ) : (
        <Card variant="surface" className="gap-0 overflow-hidden py-0">
          <div className="flex flex-col gap-3 border-b border-border/70 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative w-full max-w-xs">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search users or roles…"
                className="h-8 pl-8 text-xs"
                aria-label="Search users"
              />
            </div>
            <p className="text-[11px] text-muted-foreground">
              {filtered.length} of {users.length} accounts
            </p>
          </div>

          {users.length === 0 ? (
            <div className="p-5">
              <EmptyState
                compact
                icon={UserRound}
                title="No accounts"
                description="Create the first console account."
              />
            </div>
          ) : filtered.length === 0 ? (
            <div className="px-4 py-12 text-center">
              <p className="text-sm font-medium">No accounts match “{search}”</p>
              <Button
                variant="ghost"
                size="sm"
                className="mt-2"
                onClick={() => setSearch("")}
              >
                Clear search
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[880px] text-sm">
                <thead>
                  <tr className="border-b border-border/60 bg-muted/25">
                    {[
                      "User",
                      "Role",
                      "Status",
                      "Last sign-in",
                      "Created",
                      "",
                    ].map((label, i) => (
                      <th
                        key={label || i}
                        className="px-4 py-2.5 text-left text-[10px] font-semibold tracking-[0.12em] whitespace-nowrap text-muted-foreground uppercase"
                      >
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((candidate) => {
                    const self = candidate.id === user?.id;
                    return (
                      <tr
                        key={candidate.id}
                        className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/25"
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2.5">
                            <Avatar className="size-8 border border-border">
                              <AvatarFallback className="bg-primary/10 text-[10px] font-semibold text-primary">
                                {initials(candidate.username)}
                              </AvatarFallback>
                            </Avatar>
                            <div className="min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span className="font-mono text-[12px] font-medium">
                                  {candidate.username}
                                </span>
                                {self && (
                                  <Badge
                                    variant="secondary"
                                    className="text-[9px]"
                                  >
                                    you
                                  </Badge>
                                )}
                              </div>
                              <p className="max-w-[240px] truncate text-[10px] text-muted-foreground">
                                {candidate.email ?? "No email"}
                              </p>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <RoleBadge role={candidate.role} />
                        </td>
                        <td className="px-4 py-3">
                          <Badge
                            variant={
                              candidate.is_active ? "success" : "muted"
                            }
                            className="gap-1 text-[9px]"
                          >
                            <span
                              className={`size-1.5 rounded-full ${
                                candidate.is_active
                                  ? "bg-emerald-500"
                                  : "bg-muted-foreground/60"
                              }`}
                            />
                            {candidate.is_active ? "active" : "disabled"}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          <p className="text-[11px]">
                            {formatRelative(candidate.last_login_at)}
                          </p>
                          <p className="text-[9px] text-muted-foreground">
                            {formatDateTime(candidate.last_login_at)}
                          </p>
                        </td>
                        <td className="px-4 py-3 text-[11px] text-muted-foreground">
                          {formatDate(candidate.created_at)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                aria-label={`Actions for ${candidate.username}`}
                              >
                                <MoreHorizontal className="size-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-48">
                              <DropdownMenuItem
                                onSelect={() => {
                                  setEditing(candidate);
                                  setFormOpen(true);
                                }}
                              >
                                <Pencil /> Edit account
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                variant="destructive"
                                disabled={self || isLastActiveAdmin(candidate)}
                                onSelect={() => setDeleteTarget(candidate)}
                              >
                                <Trash2 /> Delete account
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <InlineAlert tone="info" title="Role model">
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          <span>
            <span className="font-medium">Viewer</span> — read-only
          </span>
          <span>
            <span className="font-medium">Operator</span> — BGP configuration
          </span>
          <span>
            <span className="font-medium">Admin</span> — routers, users, audit,
            BGP teardown
          </span>
        </span>
      </InlineAlert>

      {formOpen && user && (
        <UserFormDialog
          key={editing?.id ?? "create"}
          open={formOpen}
          onOpenChange={setFormOpen}
          target={editing}
          currentUserId={user.id}
          onSaved={(saved) => {
            if (saved.id === user.id) {
              void refresh();
            }
          }}
        />
      )}

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(next) => {
          if (!next && !deleteUser.isPending) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete {deleteTarget?.username}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              {deletingSelf
                ? "You cannot delete your own account."
                : deletingLastAdmin
                  ? "This is the last active administrator and cannot be deleted."
                  : "The account will be removed and can no longer sign in. This cannot be undone."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteUser.isPending && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Spinner /> Deleting account…
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteUser.isPending}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleteUser.isPending || deleteBlocked}
              onClick={(event) => {
                event.preventDefault();
                void handleDelete();
              }}
            >
              <UserX className="size-4" /> Delete account
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

export default function UsersPage() {
  return (
    <RequireRole role="admin">
      <UsersAdmin />
    </RequireRole>
  );
}
