"use client";

import * as React from "react";

import type {
  PrefixList,
  PrefixListFamily,
  PrefixListRule,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

/** VyOS allows a safe subset of policy object names; IPv4/IPv6 are independent. */
export const PREFIX_LIST_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

export const FAMILY_LABEL: Record<PrefixListFamily, string> = {
  ipv4: "IPv4",
  ipv6: "IPv6",
};

/** Longest valid prefix length per family (also the ge/le upper bound). */
export const FAMILY_MAX_LENGTH: Record<PrefixListFamily, number> = {
  ipv4: 32,
  ipv6: 128,
};

/** `policy prefix-list` (4) or `policy prefix-list6` (6) VyOS tree. */
export const FAMILY_VYOS_PATH: Record<PrefixListFamily, string> = {
  ipv4: "policy prefix-list",
  ipv6: "policy prefix-list6",
};

export const FAMILY_PLACEHOLDER: Record<
  PrefixListFamily,
  { prefix: string; name: string }
> = {
  ipv4: { prefix: "203.0.113.0/24", name: "TRANSIT-IN" },
  ipv6: { prefix: "2001:db8::/32", name: "TRANSIT-IN6" },
};

export function familyBadgeClass(family: PrefixListFamily): string {
  return family === "ipv4"
    ? "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300"
    : "border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-300";
}

export function PrefixListFamilyBadge({
  family,
  className,
}: {
  family: PrefixListFamily;
  className?: string;
}) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "font-mono text-[9px] uppercase",
        familyBadgeClass(family),
        className,
      )}
    >
      {FAMILY_LABEL[family]}
    </Badge>
  );
}

export function sortPrefixListRules(rules: PrefixListRule[]): PrefixListRule[] {
  return [...rules].sort((a, b) => a.number - b.number);
}

export function sortPrefixLists(items: PrefixList[]): PrefixList[] {
  return [...items].sort((a, b) =>
    a.family === b.family
      ? a.name.localeCompare(b.name)
      : a.family.localeCompare(b.family),
  );
}

export interface PrefixListRuleCounts {
  total: number;
  permit: number;
  deny: number;
}

export function prefixListRuleCounts(
  rules: PrefixListRule[],
): PrefixListRuleCounts {
  return {
    total: rules.length,
    permit: rules.filter((rule) => rule.action === "permit").length,
    deny: rules.filter((rule) => rule.action === "deny").length,
  };
}

/**
 * Human label for the ge/le bounds.
 *
 * Both `null` means an exact-length match; otherwise `ge–le`, `≥ge` or `≤le`.
 */
export function boundsLabel(rule: {
  ge: number | null;
  le: number | null;
}): string {
  const { ge, le } = rule;
  if (ge === null && le === null) return "exact";
  if (ge !== null && le !== null) return `${ge}–${le}`;
  if (ge !== null) return `≥${ge}`;
  return `≤${le}`;
}

/** Next free rule number in tens, capped at 65535. */
export function suggestedRuleNumber(rules: PrefixListRule[]): number {
  if (rules.length === 0) return 10;
  const highest = Math.max(...rules.map((rule) => rule.number));
  return Math.min(65535, highest + 10);
}

/** Prefix length of a CIDR string, or null when it is not parseable. */
export function prefixLength(prefix: string): number | null {
  const slash = prefix.lastIndexOf("/");
  if (slash <= 0) return null;
  const raw = prefix.slice(slash + 1).trim();
  if (!/^\d{1,3}$/.test(raw)) return null;
  return Number(raw);
}
