"use client";

import * as React from "react";

import type {
  RouteMapAction,
  RouteMapMatch,
  RouteMapRule,
  RouteMapSet,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

export interface SummaryToken {
  /** Full human-readable label, used as the hover title. */
  label: string;
  value: string;
}

const ACTION_VARIANT: Record<RouteMapAction, "success" | "destructive"> = {
  permit: "success",
  deny: "destructive",
};

export function RuleActionBadge({ action }: { action: RouteMapAction }) {
  return (
    <Badge
      variant={ACTION_VARIANT[action]}
      className="gap-1.5 font-mono text-[10px] uppercase"
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          action === "permit" ? "bg-emerald-500" : "bg-destructive",
        )}
      />
      {action}
    </Badge>
  );
}

/** Short, scannable match summary tokens (empty array = match any). */
export function matchTokens(match: RouteMapMatch): SummaryToken[] {
  const tokens: SummaryToken[] = [];
  const push = (label: string, value: string | null | undefined) => {
    if (value) tokens.push({ label, value });
  };

  push("IPv4 prefix-list", match.ipv4_prefix_list);
  push("IPv6 prefix-list", match.ipv6_prefix_list);
  push("AS-path list", match.as_path);
  if (match.community_list) {
    tokens.push({
      label: match.community_exact_match
        ? "Community-list (exact match)"
        : "Community-list",
      value: match.community_exact_match
        ? `${match.community_list} (exact)`
        : match.community_list,
    });
  }
  push("Large community-list", match.large_community_list);
  push("Extcommunity", match.extcommunity);
  push("Metric", match.metric != null ? String(match.metric) : null);
  push(
    "Local preference",
    match.local_preference != null ? String(match.local_preference) : null,
  );
  push("Origin", match.origin);
  push("Tag", match.tag != null ? String(match.tag) : null);
  push("Protocol", match.protocol);
  push("RPKI", match.rpki);
  push("IPv4 next-hop", match.ip_nexthop);
  push("IPv6 next-hop", match.ipv6_nexthop);
  push("Interface", match.interface);
  return tokens;
}

/** Short, scannable set-action summary tokens. */
export function setTokens(set: RouteMapSet): SummaryToken[] {
  const tokens: SummaryToken[] = [];
  const push = (label: string, value: string | null | undefined) => {
    if (value) tokens.push({ label, value });
  };

  push(
    "Local preference",
    set.local_preference != null ? String(set.local_preference) : null,
  );
  push("Metric", set.metric);
  push("Origin", set.origin);
  push("Weight", set.weight != null ? String(set.weight) : null);
  push("Metric type", set.metric_type);
  push("Tag", set.tag != null ? String(set.tag) : null);
  if (set.as_path_prepend?.length) {
    tokens.push({
      label: "AS-path prepend",
      value:
        set.as_path_prepend.length === 1
          ? `prepend ${set.as_path_prepend[0]}`
          : `prepend ${set.as_path_prepend.join(",")}`,
    });
  }
  if (set.community_action === "none") {
    tokens.push({ label: "Community action", value: "community none" });
  } else if (set.community_action === "delete" && set.community_delete) {
    tokens.push({
      label: "Community delete",
      value: `community ${set.community_delete}`,
    });
  } else if (set.community_action && set.community_values?.length) {
    tokens.push({
      label: `Community ${set.community_action}`,
      value: `${set.community_action} ${set.community_values.join(",")}`,
    });
  } else if (set.community_action) {
    tokens.push({
      label: "Community action",
      value: `community ${set.community_action}`,
    });
  }
  push("IPv4 next-hop", set.ip_next_hop);
  push("Originator ID", set.originator_id);
  return tokens;
}

function TokenList({
  tokens,
  empty,
  className,
}: {
  tokens: SummaryToken[];
  empty: string;
  className?: string;
}) {
  if (tokens.length === 0) {
    return (
      <span className="text-[11px] text-muted-foreground">{empty}</span>
    );
  }
  return (
    <div className={cn("flex max-w-[320px] flex-wrap gap-1", className)}>
      {tokens.map((token) => (
        <span
          key={`${token.label}:${token.value}`}
          title={token.label}
          className="inline-flex max-w-full items-center truncate rounded border border-border/70 bg-muted/40 px-1.5 py-0.5 font-mono text-[10px] text-foreground/85"
        >
          {token.value}
        </span>
      ))}
    </div>
  );
}

export function MatchSummaryCell({ match }: { match: RouteMapMatch }) {
  return <TokenList tokens={matchTokens(match)} empty="Match any" />;
}

export function SetSummaryCell({ set }: { set: RouteMapSet }) {
  return <TokenList tokens={setTokens(set)} empty="No set actions" />;
}

export interface RouteMapRuleCounts {
  total: number;
  permit: number;
  deny: number;
}

export function ruleCounts(rules: RouteMapRule[]): RouteMapRuleCounts {
  return {
    total: rules.length,
    permit: rules.filter((rule) => rule.action === "permit").length,
    deny: rules.filter((rule) => rule.action === "deny").length,
  };
}

/**
 * Behaviour indicators shown in the rules table: on-match / goto, call and
 * continue references.
 */
export function RuleBehavior({ rule }: { rule: RouteMapRule }) {
  const items: string[] = [];
  if (rule.on_match === "goto" && rule.goto_rule != null) {
    items.push(`goto ${rule.goto_rule}`);
  } else if (rule.on_match === "next") {
    items.push("on-match next");
  }
  if (rule.call) items.push(`call ${rule.call}`);
  if (rule.continue_rule != null) items.push(`continue ${rule.continue_rule}`);

  if (items.length === 0) {
    return <span className="text-[11px] text-muted-foreground">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((item) => (
        <Badge
          key={item}
          variant="outline"
          className="border-border/70 font-mono text-[9px] font-normal"
        >
          {item}
        </Badge>
      ))}
    </div>
  );
}
