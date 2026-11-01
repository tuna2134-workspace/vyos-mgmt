"use client";

import * as React from "react";
import { Check, Clipboard, Eye, EyeOff } from "lucide-react";
import type { FieldValues, Path, UseFormSetError } from "react-hook-form";
import { toast } from "sonner";

import { ApiError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/** VyOS configuration path of one WireGuard interface. */
export function wireGuardPath(name: string): string {
  return `interfaces wireguard ${name}`;
}

/** "10.100.0.1/24" or "10.100.0.1/24 +1" for the interface list. */
export function addressSummary(addresses: string[]): string {
  if (addresses.length === 0) return "No address";
  if (addresses.length === 1) return addresses[0];
  return `${addresses[0]} +${addresses.length - 1}`;
}

/** `endpoint` already carries `address:port`; config uses separate fields. */
export function formatEndpoint(
  endpoint: string | null,
  port: number | null,
): string {
  if (!endpoint) return "—";
  return port ? `${endpoint}:${port}` : endpoint;
}

export function formatKeepalive(value: number | null): string {
  return value ? `${value}s` : "—";
}

/** Short, copyable form of a Base64 key (never rendered in full in tables). */
export function shortKey(key: string | null | undefined, head = 12): string {
  if (!key) return "—";
  return `${key.slice(0, head)}…`;
}

/** One entry per non-empty line, trimmed. */
export function splitLines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

/**
 * Map 422 validation details for list-valued fields (`addresses`,
 * `allowed_ips`) onto their textarea. FastAPI reports entries as
 * `loc: ["body", "addresses", 0]`, which `applyServerFormErrors` ignores
 * because it only handles flat body fields.
 */
export function applyListFieldErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  fields: Record<string, Path<T>>,
): boolean {
  if (!(error instanceof ApiError) || !Array.isArray(error.details)) {
    return false;
  }
  let applied = false;
  for (const detail of error.details) {
    if (!detail || !Array.isArray(detail.loc)) continue;
    const strings = detail.loc.filter(
      (part): part is string =>
        typeof part === "string" &&
        part !== "body" &&
        part !== "query" &&
        part !== "path",
    );
    const field = strings.length > 0 ? fields[strings[0]] : undefined;
    if (!field) continue;
    setError(field, {
      type: "server",
      message: detail.msg || "Invalid value",
    });
    applied = true;
  }
  return applied;
}

/**
 * Copy arbitrary text to the clipboard. Secrets are only ever held in memory;
 * nothing is logged, persisted or put into the URL.
 */
export function CopyButton({
  value,
  label,
  className,
  disabled,
}: {
  value: string;
  label: string;
  className?: string;
  disabled?: boolean;
}) {
  const [copied, setCopied] = React.useState(false);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const copy = async () => {
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard API unavailable");
      }
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1600);
    } catch {
      toast.error("Could not copy to the clipboard", {
        description: "Select the value and copy it manually.",
      });
    }
  };

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label={label}
      title={label}
      disabled={disabled || !value}
      className={className}
      onClick={() => void copy()}
    >
      {copied ? (
        <Check className="size-3.5 text-emerald-500" />
      ) : (
        <Clipboard className="size-3.5" />
      )}
    </Button>
  );
}

export function EnabledBadge({
  enabled,
  className,
}: {
  enabled: boolean;
  className?: string;
}) {
  return (
    <Badge
      variant={enabled ? "success" : "muted"}
      className={cn("gap-1.5", className)}
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          enabled ? "bg-emerald-500" : "bg-muted-foreground/60",
        )}
      />
      {enabled ? "enabled" : "disabled"}
    </Badge>
  );
}

/**
 * Masked secret input (private / preshared key) with reveal and copy.
 *
 * `value` is controlled by react-hook-form; the reveal state is local so it
 * resets whenever the owning dialog unmounts. The value never leaves the form
 * except in the write request body.
 */
export function SecretKeyInput({
  value,
  onChange,
  onBlur,
  name,
  inputRef,
  id,
  disabled,
  placeholder,
  label,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  name?: string;
  inputRef?: React.Ref<HTMLInputElement>;
  id?: string;
  disabled?: boolean;
  placeholder?: string;
  label: string;
  className?: string;
}) {
  const [revealed, setRevealed] = React.useState(false);

  return (
    <div className={cn("relative", className)}>
      <Input
        ref={inputRef}
        id={id}
        name={name}
        type={revealed ? "text" : "password"}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        disabled={disabled}
        placeholder={placeholder}
        aria-label={label}
        autoComplete="off"
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        className="pr-20 font-mono text-[11px]"
      />
      <div className="absolute inset-y-0 right-0.5 flex items-center">
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={revealed ? "Hide key" : "Reveal key"}
          title={revealed ? "Hide key" : "Reveal key"}
          disabled={disabled || !value}
          onClick={() => setRevealed((current) => !current)}
        >
          {revealed ? (
            <EyeOff className="size-3.5" />
          ) : (
            <Eye className="size-3.5" />
          )}
        </Button>
        <CopyButton
          value={value}
          label={`Copy ${label.toLowerCase()}`}
          disabled={disabled || !value}
        />
      </div>
    </div>
  );
}

/** Read-only key display used for derived public keys. */
export function KeyValueBlock({
  label,
  value,
  copyLabel,
  hint,
}: {
  label: string;
  value: string;
  copyLabel: string;
  hint?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border/70 bg-muted/25 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
          {label}
        </p>
        <CopyButton value={value} label={copyLabel} className="-my-1" />
      </div>
      <p className="mt-1 font-mono text-[11px] break-all">{value}</p>
      {hint && (
        <p className="mt-1.5 text-[10px] leading-relaxed text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  );
}
