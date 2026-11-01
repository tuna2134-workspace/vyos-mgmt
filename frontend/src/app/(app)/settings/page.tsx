"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  KeyRound,
  Loader2,
  LogOut,
  Monitor,
  Moon,
  ShieldCheck,
  Sun,
  UserRound,
} from "lucide-react";
import { useTheme } from "next-themes";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useChangePassword } from "@/lib/queries";
import { applyServerFormErrors } from "@/lib/form-errors";
import { formatDateTime, formatRelative, initials } from "@/lib/format";
import { ROLE_DESCRIPTION, ROLE_LABEL } from "@/lib/roles";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { RoleBadge, InlineAlert, PageHeader, Spinner } from "@/components/states";

const passwordSchema = z
  .object({
    current_password: z.string().min(1, "Current password is required"),
    new_password: z
      .string()
      .min(12, "New password must be at least 12 characters")
      .max(128, "New password must be 128 characters or fewer"),
    confirm_password: z.string().min(1, "Confirm the new password"),
  })
  .refine((values) => values.new_password === values.confirm_password, {
    path: ["confirm_password"],
    message: "Passwords do not match",
  })
  .refine((values) => values.new_password !== values.current_password, {
    path: ["new_password"],
    message: "Choose a password different from the current one",
  });

type PasswordForm = z.infer<typeof passwordSchema>;

function ThemePicker() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  const options = [
    {
      value: "dark",
      label: "Dark",
      description: "Deep slate ops theme (default)",
      icon: Moon,
    },
    {
      value: "light",
      label: "Light",
      description: "High-contrast daytime theme",
      icon: Sun,
    },
  ] as const;

  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {options.map((option) => {
        const active = mounted ? theme === option.value : option.value === "dark";
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => setTheme(option.value)}
            aria-pressed={active}
            className={cn(
              "flex items-start gap-3 rounded-xl border p-3.5 text-left transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              active
                ? "border-primary/50 bg-primary/[0.06]"
                : "border-border/70 bg-card hover:border-border",
            )}
          >
            <span
              className={cn(
                "flex size-8 shrink-0 items-center justify-center rounded-lg",
                active
                  ? "bg-primary/15 text-primary"
                  : "bg-muted text-muted-foreground",
              )}
            >
              <option.icon className="size-4" />
            </span>
            <span className="min-w-0">
              <span className="flex items-center gap-2 text-[13px] font-medium">
                {option.label}
                {active && (
                  <span className="size-1.5 rounded-full bg-primary" />
                )}
              </span>
              <span className="mt-0.5 block text-[10px] leading-relaxed text-muted-foreground">
                {option.description}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

export default function SettingsPage() {
  const { user, logout, forceSignOut, refresh, sessionExpired } = useAuth();
  const router = useRouter();
  const changePassword = useChangePassword();
  const [serverError, setServerError] = React.useState<string | null>(null);
  const [refreshingProfile, setRefreshingProfile] = React.useState(false);

  const form = useForm<PasswordForm>({
    resolver: zodResolver(passwordSchema),
    defaultValues: {
      current_password: "",
      new_password: "",
      confirm_password: "",
    },
    mode: "onSubmit",
  });

  if (!user) return null;

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    try {
      await changePassword.mutateAsync({
        current_password: values.current_password,
        new_password: values.new_password,
      });
      toast.success("Password changed", {
        description:
          "All refresh tokens were revoked. Sign in again with your new password.",
      });
      forceSignOut();
      router.replace("/login/");
    } catch (error) {
      const applied = applyServerFormErrors(error, form.setError, [
        "current_password",
        "new_password",
      ]);
      if (!applied) {
        setServerError(
          error instanceof ApiError
            ? error.message
            : "Could not change the password.",
        );
      }
    }
  });

  const handleSignOut = async () => {
    await logout();
    router.replace("/login/");
  };

  const handleRefreshProfile = async () => {
    setRefreshingProfile(true);
    try {
      await refresh();
      toast.success("Profile refreshed");
    } finally {
      setRefreshingProfile(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Account settings"
        description="Your profile, sign-in security and console appearance."
        badge={<RoleBadge role={user.role} />}
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => void handleRefreshProfile()}
            disabled={refreshingProfile}
          >
            {refreshingProfile ? (
              <Spinner className="size-3.5" />
            ) : (
              <UserRound className="size-3.5" />
            )}
            Refresh profile
          </Button>
        }
      />

      {sessionExpired && (
        <InlineAlert tone="warning" title="Session re-established">
          Your previous session expired. You are seeing fresh profile data.
        </InlineAlert>
      )}

      <div className="grid gap-5 lg:grid-cols-[1.2fr_1fr]">
        <div className="space-y-5">
          <Card className="gap-0 overflow-hidden py-0">
            <div className="relative border-b border-border/70 bg-gradient-to-br from-primary/[0.07] via-transparent to-emerald-500/[0.04] px-5 py-5">
              <div className="flex items-center gap-4">
                <Avatar className="size-14 border border-border shadow-sm">
                  <AvatarFallback className="bg-primary/15 text-base font-semibold text-primary">
                    {initials(user.username)}
                  </AvatarFallback>
                </Avatar>
                <div className="min-w-0">
                  <h2 className="truncate text-lg font-semibold tracking-tight">
                    {user.username}
                  </h2>
                  <p className="truncate text-xs text-muted-foreground">
                    {user.email ?? "No email address on file"}
                  </p>
                  <div className="mt-1.5 flex items-center gap-2">
                    <RoleBadge role={user.role} />
                    <Badge
                      variant={user.is_active ? "success" : "destructive"}
                      className="text-[9px]"
                    >
                      {user.is_active ? "active" : "disabled"}
                    </Badge>
                  </div>
                </div>
              </div>
              <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
                {ROLE_DESCRIPTION[user.role]}
              </p>
            </div>
            <CardContent className="px-5 py-2">
              <dl className="divide-y divide-border/60">
                {[
                  ["Role", ROLE_LABEL[user.role]],
                  ["Last sign-in", formatDateTime(user.last_login_at)],
                  ["Last sign-in (relative)", formatRelative(user.last_login_at)],
                  ["Member since", formatDateTime(user.created_at)],
                  ["Account ID", user.id],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="flex items-center justify-between gap-4 py-2.5 text-xs"
                  >
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="max-w-[65%] truncate text-right font-mono text-[11px]">
                      {value}
                    </dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>

          <Card className="gap-4">
            <CardHeader className="gap-1 border-b border-border/60 pb-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <KeyRound className="size-4 text-primary" />
                Change password
              </CardTitle>
              <CardDescription className="text-xs leading-relaxed">
                Choose at least 12 characters. Changing your password revokes
                every refresh token, including other browsers.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {serverError && (
                <InlineAlert tone="error" title="Could not change password" className="mb-4">
                  {serverError}
                </InlineAlert>
              )}
              <Form {...form}>
                <form onSubmit={onSubmit} className="space-y-4" noValidate>
                  <FormField
                    control={form.control}
                    name="current_password"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Current password</FormLabel>
                        <FormControl>
                          <Input
                            type="password"
                            autoComplete="current-password"
                            disabled={changePassword.isPending}
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <div className="grid gap-4 sm:grid-cols-2">
                    <FormField
                      control={form.control}
                      name="new_password"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>New password</FormLabel>
                          <FormControl>
                            <Input
                              type="password"
                              autoComplete="new-password"
                              disabled={changePassword.isPending}
                              {...field}
                            />
                          </FormControl>
                          <FormDescription>Minimum 12 characters.</FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="confirm_password"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Confirm new password</FormLabel>
                          <FormControl>
                            <Input
                              type="password"
                              autoComplete="new-password"
                              disabled={changePassword.isPending}
                              {...field}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                  <div className="flex justify-end border-t border-border/60 pt-4">
                    <Button type="submit" disabled={changePassword.isPending}>
                      {changePassword.isPending ? (
                        <>
                          <Loader2 className="size-4 animate-spin" /> Updating…
                        </>
                      ) : (
                        <>
                          <KeyRound className="size-4" /> Update password
                        </>
                      )}
                    </Button>
                  </div>
                </form>
              </Form>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-5">
          <Card className="gap-4">
            <CardHeader className="gap-1 border-b border-border/60 pb-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Monitor className="size-4 text-primary" />
                Appearance
              </CardTitle>
              <CardDescription className="text-xs">
                The console defaults to dark mode; your choice is stored in this
                browser.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ThemePicker />
            </CardContent>
          </Card>

          <Card className="gap-4">
            <CardHeader className="gap-1 border-b border-border/60 pb-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <ShieldCheck className="size-4 text-primary" />
                Session security
              </CardTitle>
              <CardDescription className="text-xs leading-relaxed">
                How this console keeps your session safe.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-[11px] leading-relaxed text-muted-foreground">
              <div className="flex gap-2.5">
                <span className="mt-1 size-1.5 shrink-0 rounded-full bg-emerald-500" />
                <p>
                  <span className="font-medium text-foreground">
                    Access token in memory only.
                  </span>{" "}
                  It is never written to localStorage or cookies and expires
                  after 15 minutes.
                </p>
              </div>
              <div className="flex gap-2.5">
                <span className="mt-1 size-1.5 shrink-0 rounded-full bg-emerald-500" />
                <p>
                  <span className="font-medium text-foreground">
                    Refresh token in an HttpOnly cookie.
                  </span>{" "}
                  JavaScript cannot read it; refresh requests include a CSRF
                  header.
                </p>
              </div>
              <div className="flex gap-2.5">
                <span className="mt-1 size-1.5 shrink-0 rounded-full bg-emerald-500" />
                <p>
                  <span className="font-medium text-foreground">
                    Server-enforced roles.
                  </span>{" "}
                  UI gating is a convenience; the API rejects unauthorized
                  actions.
                </p>
              </div>
              <Button
                variant="outline"
                className="mt-1 w-full"
                onClick={() => void handleSignOut()}
              >
                <LogOut className="size-4" /> Sign out of this browser
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
