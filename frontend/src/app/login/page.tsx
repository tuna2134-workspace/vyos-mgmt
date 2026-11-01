"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  ArrowRight,
  Eye,
  EyeOff,
  GitBranch,
  Loader2,
  LockKeyhole,
  RadioTower,
  ScrollText,
  ShieldCheck,
} from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Logo, LogoMark } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { BootScreen, InlineAlert, StatusDot } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const loginSchema = z.object({
  username: z
    .string()
    .trim()
    .min(1, "Username is required")
    .max(64, "Username is too long"),
  password: z.string().min(1, "Password is required"),
  remember_me: z.boolean(),
});

type LoginForm = z.infer<typeof loginSchema>;

const features = [
  {
    icon: RadioTower,
    title: "BGP session health",
    body: "Established peers, uptime, prefix counts and message flow.",
  },
  {
    icon: ShieldCheck,
    title: "Role-based guardrails",
    body: "Viewer, operator and administrator permissions enforced by the API.",
  },
  {
    icon: ScrollText,
    title: "Audited changes",
    body: "Every configuration change is attributed and recorded.",
  },
];

export default function LoginPage() {
  const router = useRouter();
  const { status, login, sessionExpired } = useAuth();
  const [serverError, setServerError] = React.useState<string | null>(null);
  const [showPassword, setShowPassword] = React.useState(false);
  const [nextPath, setNextPath] = React.useState<string | null>(null);

  const form = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
    defaultValues: { username: "", password: "", remember_me: true },
    mode: "onSubmit",
  });

  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const candidate = params.get("next");
    if (
      candidate &&
      candidate.startsWith("/") &&
      !candidate.startsWith("//") &&
      !candidate.startsWith("/login")
    ) {
      setNextPath(candidate);
    } else {
      setNextPath("/");
    }
  }, []);

  React.useEffect(() => {
    if (status === "authenticated" && nextPath) {
      router.replace(nextPath);
    }
  }, [status, nextPath, router]);

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    try {
      const user = await login(values);
      toast.success(`Signed in as ${user.username}`, {
        description: "Session established. Loading your console…",
      });
      router.replace(nextPath ?? "/");
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 429) {
          const retry = error.retryAfterSeconds
            ? ` Try again in ${error.retryAfterSeconds}s.`
            : " Try again shortly.";
          setServerError(`Too many sign-in attempts.${retry}`);
        } else if (error.code === "invalid_credentials") {
          setServerError("Invalid username or password.");
        } else {
          setServerError(error.message);
        }
      } else {
        setServerError(
          "Unable to reach the management API. Verify the backend is running.",
        );
      }
    }
  });

  if (status === "authenticated") {
    return <BootScreen label="Session established — opening console" />;
  }

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.08fr_1fr]">
      {/* Brand / story panel */}
      <section className="dark relative hidden overflow-hidden bg-[#070d14] text-foreground lg:flex lg:flex-col">
        <div aria-hidden="true" className="absolute inset-0 bg-grid opacity-40" />
        <div
          aria-hidden="true"
          className="absolute -top-32 -left-24 size-[520px] rounded-full bg-cyan-500/20 blur-[130px]"
        />
        <div
          aria-hidden="true"
          className="absolute right-0 bottom-0 size-[440px] translate-x-1/4 translate-y-1/4 rounded-full bg-emerald-500/15 blur-[120px]"
        />
        <div
          aria-hidden="true"
          className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-300/50 to-transparent"
        />

        <div className="relative z-10 flex flex-1 flex-col p-10 xl:p-14">
          <Logo />

          <div className="mt-auto max-w-lg pt-16 pb-10">
            <span className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-300/5 px-3 py-1 text-[10px] font-medium tracking-[0.18em] text-cyan-200/80 uppercase">
              <span className="relative flex size-1.5">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-cyan-300 opacity-60" />
                <span className="relative inline-flex size-1.5 rounded-full bg-cyan-300" />
              </span>
              Management plane
            </span>
            <h1 className="mt-6 text-4xl leading-[1.08] font-semibold tracking-tight text-balance xl:text-[2.9rem]">
              Every session.
              <br />
              Every prefix.
              <span className="bg-gradient-to-r from-cyan-300 to-emerald-300 bg-clip-text text-transparent">
                {" "}
                One console.
              </span>
            </h1>
            <p className="mt-4 max-w-md text-sm leading-relaxed text-slate-400">
              Operate your VyOS fleet with a purpose-built network operations
              console — BGP configuration, live peer health and an audit trail,
              without touching the CLI.
            </p>

            <ul className="mt-8 space-y-3.5">
              {features.map((feature) => (
                <li key={feature.title} className="flex gap-3">
                  <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-cyan-300">
                    <feature.icon className="size-4" />
                  </div>
                  <div>
                    <p className="text-[13px] font-medium text-slate-200">
                      {feature.title}
                    </p>
                    <p className="text-xs leading-relaxed text-slate-500">
                      {feature.body}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          {/* Illustrative session panel */}
          <div className="relative mt-auto max-w-md rounded-xl border border-white/10 bg-white/[0.03] p-4 backdrop-blur-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <GitBranch className="size-3.5 text-cyan-300" />
                <span className="font-mono text-[11px] tracking-wide text-slate-300">
                  edge-tokyo
                </span>
              </div>
              <span className="flex items-center gap-1.5 text-[10px] text-emerald-300/90">
                <StatusDot tone="success" pulse /> session summary
              </span>
            </div>
            <div className="mt-3 grid grid-cols-3 divide-x divide-white/10 rounded-lg border border-white/[0.07] bg-black/20">
              <div className="px-3 py-2.5">
                <p className="text-[9px] tracking-[0.14em] text-slate-500 uppercase">
                  Peers up
                </p>
                <p className="mt-0.5 font-mono text-sm text-slate-200">12 / 12</p>
              </div>
              <div className="px-3 py-2.5">
                <p className="text-[9px] tracking-[0.14em] text-slate-500 uppercase">
                  Prefixes
                </p>
                <p className="mt-0.5 font-mono text-sm text-slate-200">
                  1,284
                </p>
              </div>
              <div className="px-3 py-2.5">
                <p className="text-[9px] tracking-[0.14em] text-slate-500 uppercase">
                  Local AS
                </p>
                <p className="mt-0.5 font-mono text-sm text-slate-200">64512</p>
              </div>
            </div>
            <p className="mt-2 text-[9px] tracking-wide text-slate-600">
              Illustrative data · live values appear after sign-in
            </p>
          </div>
        </div>
      </section>

      {/* Auth panel */}
      <section className="relative flex min-h-dvh flex-col bg-background">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-grid bg-grid-fade opacity-25 dark:opacity-20"
        />
        <div className="relative z-10 flex items-center justify-between px-5 py-4 sm:px-8">
          <div className="lg:hidden">
            <Logo compact />
          </div>
          <div className="hidden text-[11px] text-muted-foreground lg:block">
            Need access? Contact your network administrator.
          </div>
          <ThemeToggle />
        </div>

        <div className="relative z-10 flex flex-1 items-center justify-center px-5 py-8 sm:px-8">
          <div className="w-full max-w-[360px]">
            <div className="mb-8">
              <div className="mb-6 hidden lg:block">
                <LogoMark size={38} />
              </div>
              <p className="text-[10px] font-semibold tracking-[0.2em] text-primary uppercase">
                Secure sign-in
              </p>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight">
                Welcome back
              </h1>
              <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                Sign in with your VyOS Control account to manage routers and BGP
                sessions.
              </p>
            </div>

            {sessionExpired && (
              <InlineAlert tone="warning" className="mb-4" title="Session expired">
                Your session ended. Sign in again to continue where you left
                off.
              </InlineAlert>
            )}
            {serverError && (
              <InlineAlert tone="error" className="mb-4" title="Sign-in failed">
                {serverError}
              </InlineAlert>
            )}

            <form onSubmit={onSubmit} className="space-y-4" noValidate>
              <div className="space-y-1.5">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  autoComplete="username"
                  autoFocus
                  placeholder="admin"
                  spellCheck={false}
                  autoCapitalize="none"
                  aria-invalid={!!form.formState.errors.username}
                  aria-describedby={
                    form.formState.errors.username
                      ? "username-error"
                      : undefined
                  }
                  {...form.register("username")}
                />
                {form.formState.errors.username && (
                  <p
                    id="username-error"
                    className="text-xs font-medium text-destructive"
                  >
                    {form.formState.errors.username.message}
                  </p>
                )}
              </div>

              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label htmlFor="password">Password</Label>
                  <span className="text-[11px] text-muted-foreground">
                    min 12 characters
                  </span>
                </div>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    placeholder="••••••••••••"
                    className="pr-10"
                    aria-invalid={!!form.formState.errors.password}
                    aria-describedby={
                      form.formState.errors.password
                        ? "password-error"
                        : undefined
                    }
                    {...form.register("password")}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((value) => !value)}
                    className="absolute top-1/2 right-1 -translate-y-1/2 rounded-md p-2 text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                    aria-label={
                      showPassword ? "Hide password" : "Show password"
                    }
                    aria-pressed={showPassword}
                  >
                    {showPassword ? (
                      <EyeOff className="size-4" />
                    ) : (
                      <Eye className="size-4" />
                    )}
                  </button>
                </div>
                {form.formState.errors.password && (
                  <p
                    id="password-error"
                    className="text-xs font-medium text-destructive"
                  >
                    {form.formState.errors.password.message}
                  </p>
                )}
              </div>

              <div className="flex items-center gap-2.5 pt-0.5">
                <Checkbox
                  id="remember_me"
                  checked={form.watch("remember_me")}
                  onCheckedChange={(checked) =>
                    form.setValue("remember_me", checked === true)
                  }
                />
                <div className="grid gap-0.5">
                  <Label
                    htmlFor="remember_me"
                    className="cursor-pointer text-[13px] font-normal"
                  >
                    Keep me signed in
                  </Label>
                  <p className="text-[11px] text-muted-foreground">
                    Uses a persistent refresh cookie instead of a session
                    cookie.
                  </p>
                </div>
              </div>

              <Button
                type="submit"
                className="mt-2 h-10 w-full gap-2"
                disabled={form.formState.isSubmitting}
              >
                {form.formState.isSubmitting ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    Signing in…
                  </>
                ) : (
                  <>
                    Sign in
                    <ArrowRight className="size-4" />
                  </>
                )}
              </Button>
            </form>

            <div className="mt-6 space-y-3">
              <div className="flex items-center gap-2 rounded-lg border border-border/70 bg-muted/30 px-3 py-2.5 text-[11px] leading-relaxed text-muted-foreground">
                <LockKeyhole className="size-3.5 shrink-0" />
                Access and configuration changes are recorded in the audit log.
              </div>
              <p className="text-center text-[10px] tracking-wide text-muted-foreground/60">
                VyOS Control · sessions protected with HttpOnly refresh cookies
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
