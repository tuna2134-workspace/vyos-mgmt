"use client";

import * as React from "react";
import Link from "next/link";
import { zodResolver } from "@hookform/resolvers/zod";
import { ListFilter, Loader2, Save } from "lucide-react";
import {
  type Control,
  type FieldErrors,
  type FieldPath,
  type UseFormSetError,
  useForm,
} from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import {
  useCreateRouteMapRule,
  useUpdateRouteMapRule,
} from "@/lib/queries";
import type {
  PrefixListFamily,
  RouteMap,
  RouteMapCommunityAction,
  RouteMapMatch,
  RouteMapMetricType,
  RouteMapOnMatch,
  RouteMapProtocol,
  RouteMapRule,
  RouteMapRuleCreate,
  RouteMapSet,
} from "@/lib/types";
import { isIPv4, isIPv6, isValidAsn } from "@/lib/validation";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { InlineAlert } from "@/components/states";

/* -------------------------------------------------------------------------- */
/* Schema                                                                     */
/* -------------------------------------------------------------------------- */

/** Policy object references (prefix-list, community-list, extcommunity…). */
const OBJECT_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
/** Route-map names are shorter (VyOS/VyOS-API limit). */
const ROUTE_MAP_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const UNSIGNED = /^\d+$/;
const SET_METRIC = /^(?:\d{1,10}|[+-]\d{1,10}|rtt|[+-]rtt)$/i;
const COMMUNITY_VALUE = /^(?:(\d{1,5}):(\d{1,5})|[A-Za-z][A-Za-z0-9-]*)$/;
const WELL_KNOWN_COMMUNITY = new Set([
  "accept-own",
  "accept-own-nexthop",
  "blackhole",
  "graceful-shutdown",
  "llgr-stale",
  "local-as",
  "no-advertise",
  "no-export",
  "no-llgr",
  "no-peer",
  "route-filter-translated-v4",
  "route-filter-translated-v6",
  "route-filter-v4",
  "route-filter-v6",
]);

function isValidCommunityValue(value: string): boolean {
  const match = COMMUNITY_VALUE.exec(value);
  if (!match) return false;
  if (match[1] === undefined) {
    return WELL_KNOWN_COMMUNITY.has(value.toLowerCase());
  }
  return Number(match[1]) <= 65535 && Number(match[2]) <= 65535;
}

const ruleSchema = z.object({
  number: z.string().trim().min(1, "Rule number is required"),
  action: z.enum(["permit", "deny"]),
  description: z
    .string()
    .max(255, "Description must be 255 characters or fewer"),
  on_match: z.enum(["none", "next", "goto"]),
  goto_rule: z.string(),
  call: z.string(),
  continue_rule: z.string(),

  // Match
  m_ipv4_prefix_list: z.string(),
  m_ipv6_prefix_list: z.string(),
  m_as_path: z.string(),
  m_community_list: z.string(),
  m_community_exact: z.boolean(),
  m_large_community_list: z.string(),
  m_extcommunity: z.string(),
  m_metric: z.string(),
  m_local_preference: z.string(),
  m_origin: z.enum(["any", "igp", "egp", "incomplete"]),
  m_tag: z.string(),
  m_protocol: z.enum([
    "any",
    "babel",
    "bgp",
    "connected",
    "isis",
    "kernel",
    "ospf",
    "ospfv3",
    "rip",
    "ripng",
    "static",
    "table",
    "vnc",
  ]),
  m_rpki: z.enum(["any", "invalid", "notfound", "valid"]),
  m_ip_nexthop: z.string(),
  m_ipv6_nexthop: z.string(),
  m_interface: z.string(),

  // Set
  s_local_preference: z.string(),
  s_metric: z.string(),
  s_origin: z.enum(["any", "igp", "egp", "incomplete"]),
  s_weight: z.string(),
  s_metric_type: z.enum(["unset", "type-1", "type-2"]),
  s_tag: z.string(),
  s_as_prepend: z.string(),
  s_community_action: z.enum(["unset", "add", "replace", "delete", "none"]),
  s_community_values: z.string(),
  s_community_delete: z.string(),
  s_ip_next_hop: z.string(),
  s_originator_id: z.string(),
});

type RuleFormValues = z.infer<typeof ruleSchema>;

interface NumberFieldRule {
  field: keyof RuleFormValues;
  label: string;
  min: number;
  max: number;
}

const NUMBER_FIELDS: NumberFieldRule[] = [
  { field: "m_metric", label: "Match metric", min: 1, max: 65535 },
  {
    field: "m_local_preference",
    label: "Match local preference",
    min: 0,
    max: 4294967295,
  },
  { field: "m_tag", label: "Match tag", min: 1, max: 65535 },
  {
    field: "s_local_preference",
    label: "Local preference",
    min: 0,
    max: 4294967295,
  },
  { field: "s_weight", label: "Weight", min: 0, max: 4294967295 },
  { field: "s_tag", label: "Tag", min: 1, max: 65535 },
  { field: "continue_rule", label: "Continue rule", min: 1, max: 65535 },
];

const NAME_FIELDS: Array<{ field: keyof RuleFormValues; label: string }> = [
  { field: "m_ipv4_prefix_list", label: "IPv4 prefix-list" },
  { field: "m_ipv6_prefix_list", label: "IPv6 prefix-list" },
  { field: "m_as_path", label: "AS-path list" },
  { field: "m_community_list", label: "Community-list" },
  { field: "m_large_community_list", label: "Large community-list" },
  { field: "m_extcommunity", label: "Extcommunity" },
  { field: "m_interface", label: "Interface" },
  { field: "call", label: "Call route-map" },
  { field: "s_community_delete", label: "Community-list" },
];

const ruleFormSchema = ruleSchema.superRefine((values, ctx) => {
  const number = Number(values.number);
  if (
    !UNSIGNED.test(values.number.trim()) ||
    !Number.isInteger(number) ||
    number < 1 ||
    number > 65535
  ) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["number"],
      message: "Rule number must be an integer from 1 to 65535",
    });
  }

  if (values.on_match === "goto") {
    const goto = values.goto_rule.trim();
    if (!goto) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["goto_rule"],
        message: "A goto rule number is required when on-match is goto",
      });
    } else if (
      !UNSIGNED.test(goto) ||
      Number(goto) < 1 ||
      Number(goto) > 65535
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["goto_rule"],
        message: "Goto rule must be an integer from 1 to 65535",
      });
    } else if (Number(goto) === number) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["goto_rule"],
        message: "Goto rule must differ from this rule's number",
      });
    }
  }

  for (const rule of NUMBER_FIELDS) {
    const raw = String(values[rule.field] ?? "").trim();
    if (!raw) continue;
    if (
      !UNSIGNED.test(raw) ||
      Number(raw) < rule.min ||
      Number(raw) > rule.max
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: [rule.field],
        message: `${rule.label} must be an integer from ${rule.min} to ${rule.max}`,
      });
    }
  }

  for (const rule of NAME_FIELDS) {
    const raw = String(values[rule.field] ?? "").trim();
    if (!raw) continue;
    const pattern = rule.field === "call" ? ROUTE_MAP_NAME : OBJECT_NAME;
    if (!pattern.test(raw)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: [rule.field],
        message: `${rule.label} name must start with a letter or digit and use letters, digits, dots, underscores or hyphens`,
      });
    }
  }

  if (values.m_community_exact && !values.m_community_list.trim()) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["m_community_list"],
      message: "A community-list is required for exact matching",
    });
  }

  if (values.m_ip_nexthop.trim() && !isIPv4(values.m_ip_nexthop.trim())) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["m_ip_nexthop"],
      message: "Enter an IPv4 address",
    });
  }
  if (values.m_ipv6_nexthop.trim() && !isIPv6(values.m_ipv6_nexthop.trim())) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["m_ipv6_nexthop"],
      message: "Enter an IPv6 address",
    });
  }

  const metric = values.s_metric.trim();
  if (metric) {
    if (!SET_METRIC.test(metric)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["s_metric"],
        message: "Use 0–4294967295, +N, -N, rtt, +rtt or -rtt",
      });
    } else if (
      /^[+-]?\d+$/.test(metric) &&
      Number(metric.replace(/^[+-]/, "")) > 4294967295
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["s_metric"],
        message: "Metric must be at most 4294967295",
      });
    }
  }

  if (values.s_as_prepend.trim()) {
    const asns = splitTokens(values.s_as_prepend);
    if (asns.length > 20) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["s_as_prepend"],
        message: "At most 20 ASNs can be prepended",
      });
    } else if (asns.some((asn) => !isValidAsn(asn))) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["s_as_prepend"],
        message: "Each ASN must be an integer from 1 to 4294967295",
      });
    }
  }

  if (values.s_community_action === "add" || values.s_community_action === "replace") {
    const communityValues = splitTokens(values.s_community_values);
    if (communityValues.length === 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["s_community_values"],
        message: "Add at least one community value",
      });
    } else if (communityValues.some((value) => !isValidCommunityValue(value))) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["s_community_values"],
        message: "Use communities like 64512:100 or well-known names such as no-export",
      });
    }
  }

  if (values.s_community_action === "delete" && !values.s_community_delete.trim()) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["s_community_delete"],
      message: "A community-list name is required for the delete action",
    });
  }

  const nextHop = values.s_ip_next_hop.trim();
  if (
    nextHop &&
    nextHop !== "unchanged" &&
    nextHop !== "peer-address" &&
    !isIPv4(nextHop)
  ) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["s_ip_next_hop"],
      message: "Enter an IPv4 address, unchanged or peer-address",
    });
  }

  if (
    values.s_originator_id.trim() &&
    !isIPv4(values.s_originator_id.trim())
  ) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["s_originator_id"],
      message: "Enter an IPv4 address",
    });
  }
});

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

function splitTokens(value: string): string[] {
  return value
    .split(/[\s,]+/)
    .map((token) => token.trim())
    .filter(Boolean);
}

function blank(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

function intOrNull(value: string | undefined): number | null {
  const trimmed = value?.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function suggestedRuleNumber(rules: RouteMapRule[]): number {
  if (rules.length === 0) return 10;
  const highest = Math.max(...rules.map((rule) => rule.number));
  return Math.min(65535, highest + 10);
}

function defaultsFor(
  rule: RouteMapRule | null,
  rules: RouteMapRule[],
): RuleFormValues {
  const match = rule?.match;
  const set = rule?.set;
  return {
    number: rule ? String(rule.number) : String(suggestedRuleNumber(rules)),
    action: rule?.action ?? "permit",
    description: rule?.description ?? "",
    on_match: rule?.on_match ?? "none",
    goto_rule: rule?.goto_rule != null ? String(rule.goto_rule) : "",
    call: rule?.call ?? "",
    continue_rule:
      rule?.continue_rule != null ? String(rule.continue_rule) : "",

    m_ipv4_prefix_list: match?.ipv4_prefix_list ?? "",
    m_ipv6_prefix_list: match?.ipv6_prefix_list ?? "",
    m_as_path: match?.as_path ?? "",
    m_community_list: match?.community_list ?? "",
    m_community_exact: match?.community_exact_match ?? false,
    m_large_community_list: match?.large_community_list ?? "",
    m_extcommunity: match?.extcommunity ?? "",
    m_metric: match?.metric != null ? String(match.metric) : "",
    m_local_preference:
      match?.local_preference != null ? String(match.local_preference) : "",
    m_origin: match?.origin ?? "any",
    m_tag: match?.tag != null ? String(match.tag) : "",
    m_protocol: match?.protocol ?? "any",
    m_rpki: match?.rpki ?? "any",
    m_ip_nexthop: match?.ip_nexthop ?? "",
    m_ipv6_nexthop: match?.ipv6_nexthop ?? "",
    m_interface: match?.interface ?? "",

    s_local_preference:
      set?.local_preference != null ? String(set.local_preference) : "",
    s_metric: set?.metric ?? "",
    s_origin: set?.origin ?? "any",
    s_weight: set?.weight != null ? String(set.weight) : "",
    s_metric_type: set?.metric_type ?? "unset",
    s_tag: set?.tag != null ? String(set.tag) : "",
    s_as_prepend: set?.as_path_prepend?.length
      ? set.as_path_prepend.join(", ")
      : "",
    s_community_action: set?.community_action ?? "unset",
    s_community_values: set?.community_values?.length
      ? set.community_values.join(", ")
      : "",
    s_community_delete: set?.community_delete ?? "",
    s_ip_next_hop: set?.ip_next_hop ?? "",
    s_originator_id: set?.originator_id ?? "",
  };
}

function buildRule(values: RuleFormValues): RouteMapRuleCreate {
  const match: RouteMapMatch = {
    ipv4_prefix_list: blank(values.m_ipv4_prefix_list),
    ipv6_prefix_list: blank(values.m_ipv6_prefix_list),
    as_path: blank(values.m_as_path),
    community_list: blank(values.m_community_list),
    community_exact_match: values.m_community_exact,
    large_community_list: blank(values.m_large_community_list),
    extcommunity: blank(values.m_extcommunity),
    metric: intOrNull(values.m_metric),
    local_preference: intOrNull(values.m_local_preference),
    origin: values.m_origin === "any" ? null : values.m_origin,
    tag: intOrNull(values.m_tag),
    protocol: values.m_protocol === "any" ? null : values.m_protocol,
    rpki: values.m_rpki === "any" ? null : values.m_rpki,
    ip_nexthop: blank(values.m_ip_nexthop),
    ipv6_nexthop: blank(values.m_ipv6_nexthop),
    interface: blank(values.m_interface),
  };

  const asPathPrepend = splitTokens(values.s_as_prepend);
  const communityValues = splitTokens(values.s_community_values);

  const set: RouteMapSet = {
    local_preference: intOrNull(values.s_local_preference),
    metric: blank(values.s_metric),
    origin: values.s_origin === "any" ? null : values.s_origin,
    weight: intOrNull(values.s_weight),
    metric_type:
      values.s_metric_type === "unset"
        ? null
        : (values.s_metric_type as RouteMapMetricType),
    tag: intOrNull(values.s_tag),
    as_path_prepend: asPathPrepend.length ? asPathPrepend.map(Number) : [],
    community_action:
      values.s_community_action === "unset"
        ? null
        : (values.s_community_action as RouteMapCommunityAction),
    community_values:
      (values.s_community_action === "add" ||
        values.s_community_action === "replace") &&
      communityValues.length
        ? communityValues
        : [],
    community_delete:
      values.s_community_action === "delete"
        ? blank(values.s_community_delete)
        : null,
    ip_next_hop: blank(values.s_ip_next_hop),
    originator_id: blank(values.s_originator_id),
  };

  return {
    number: Number(values.number),
    action: values.action,
    description: blank(values.description),
    match,
    set,
    on_match:
      values.on_match === "none"
        ? null
        : (values.on_match as RouteMapOnMatch),
    goto_rule:
      values.on_match === "goto" ? intOrNull(values.goto_rule) : null,
    call: blank(values.call),
    continue_rule: intOrNull(values.continue_rule),
  };
}

const ORIGIN_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "any", label: "Any (unset)" },
  { value: "igp", label: "IGP" },
  { value: "egp", label: "EGP" },
  { value: "incomplete", label: "Incomplete" },
];

const PROTOCOL_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "any", label: "Any (unset)" },
  ...(
    [
      "babel",
      "bgp",
      "connected",
      "isis",
      "kernel",
      "ospf",
      "ospfv3",
      "rip",
      "ripng",
      "static",
      "table",
      "vnc",
    ] as RouteMapProtocol[]
  ).map((protocol) => ({
    value: protocol,
    label: protocol === "bgp" ? "BGP" : protocol,
  })),
];

const RPKI_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "any", label: "Any (unset)" },
  { value: "valid", label: "Valid" },
  { value: "invalid", label: "Invalid" },
  { value: "notfound", label: "Not found" },
];

/* -------------------------------------------------------------------------- */
/* Field primitives                                                           */
/* -------------------------------------------------------------------------- */

function TextField({
  control,
  name,
  label,
  hint,
  placeholder,
  disabled,
  mono = true,
  inputMode,
  datalistId,
  datalistOptions,
}: {
  control: Control<RuleFormValues>;
  name: FieldPath<RuleFormValues>;
  label: string;
  hint?: React.ReactNode;
  placeholder?: string;
  disabled?: boolean;
  mono?: boolean;
  inputMode?: React.HTMLAttributes<HTMLInputElement>["inputMode"];
  /** Native `<datalist>` suggestions; free text is still accepted. */
  datalistId?: string;
  datalistOptions?: string[];
}) {
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            <Input
              placeholder={placeholder}
              className={mono ? "font-mono" : undefined}
              inputMode={inputMode}
              list={datalistId}
              autoCapitalize="none"
              spellCheck={false}
              disabled={disabled}
              value={(field.value as string) ?? ""}
              onChange={field.onChange}
              onBlur={field.onBlur}
              name={field.name}
              ref={field.ref}
            />
          </FormControl>
          {datalistId && (
            <datalist id={datalistId}>
              {(datalistOptions ?? []).map((option) => (
                <option key={option} value={option} />
              ))}
            </datalist>
          )}
          {hint && <FormDescription>{hint}</FormDescription>}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

function SelectField({
  control,
  name,
  label,
  hint,
  options,
  disabled,
}: {
  control: Control<RuleFormValues>;
  name: FieldPath<RuleFormValues>;
  label: string;
  hint?: React.ReactNode;
  options: Array<{ value: string; label: string }>;
  disabled?: boolean;
}) {
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <Select
            value={(field.value as string) ?? options[0]?.value}
            onValueChange={field.onChange}
            disabled={disabled}
          >
            <FormControl>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
            </FormControl>
            <SelectContent>
              {options.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {hint && <FormDescription>{hint}</FormDescription>}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
      {children}
    </p>
  );
}

/* -------------------------------------------------------------------------- */
/* Server-error help                                                          */
/* -------------------------------------------------------------------------- */

/**
 * Prefix-list names live under `match`, so FastAPI reports
 * `loc: ["body", "match", "ipv4_prefix_list"]`. `applyServerFormErrors` only
 * maps flat body fields; map these onto the form fields explicitly so an
 * unknown/missing prefix list is not a silent 422.
 */
const PREFIX_LIST_MATCH_FIELDS: Record<
  string,
  "m_ipv4_prefix_list" | "m_ipv6_prefix_list"
> = {
  ipv4_prefix_list: "m_ipv4_prefix_list",
  ipv6_prefix_list: "m_ipv6_prefix_list",
};

function applyPrefixListMatchErrors(
  error: unknown,
  setError: UseFormSetError<RuleFormValues>,
): boolean {
  if (!(error instanceof ApiError) || !Array.isArray(error.details)) {
    return false;
  }
  let applied = false;
  for (const detail of error.details) {
    if (!detail || !Array.isArray(detail.loc)) continue;
    const leaf = [...detail.loc]
      .reverse()
      .find((part): part is string => typeof part === "string");
    if (!leaf) continue;
    const field = PREFIX_LIST_MATCH_FIELDS[leaf];
    if (!field) continue;
    setError(field, {
      type: "server",
      message:
        detail.msg ||
        `This prefix list does not exist on the device; create it under Prefix lists first.`,
    });
    applied = true;
  }
  return applied;
}

/* -------------------------------------------------------------------------- */
/* Dialog                                                                     */
/* -------------------------------------------------------------------------- */

export function RuleFormDialog({
  open,
  onOpenChange,
  routerId,
  routeMap,
  rule,
  prefixListNames,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  routeMap: RouteMap;
  rule: RouteMapRule | null;
  /** Existing policy objects offered as `<datalist>` suggestions. */
  prefixListNames?: Record<PrefixListFamily, string[]>;
}) {
  const isEdit = !!rule;
  const ipv4PrefixLists = prefixListNames?.ipv4 ?? [];
  const ipv6PrefixLists = prefixListNames?.ipv6 ?? [];
  const [serverError, setServerError] = React.useState<string | null>(null);
  const [tab, setTab] = React.useState("general");
  const createRule = useCreateRouteMapRule(routerId);
  const updateRule = useUpdateRouteMapRule(routerId);
  const pending = createRule.isPending || updateRule.isPending;

  const form = useForm<RuleFormValues>({
    resolver: zodResolver(ruleFormSchema),
    defaultValues: defaultsFor(rule, routeMap.rules),
    mode: "onSubmit",
  });

  React.useEffect(() => {
    if (!open) return;
    form.reset(defaultsFor(rule, routeMap.rules));
    setServerError(null);
    setTab("general");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, rule?.number, routeMap.name, routerId]);

  const onMatch = form.watch("on_match");
  const communityList = form.watch("m_community_list");
  const communityAction = form.watch("s_community_action");

  // Validation errors on an inactive tab would otherwise be invisible.
  const onInvalid = (errors: FieldErrors<RuleFormValues>) => {
    const paths = Object.keys(errors);
    if (paths.some((path) => path.startsWith("m_"))) {
      setTab("match");
    } else if (paths.some((path) => path.startsWith("s_"))) {
      setTab("set");
    } else {
      setTab("general");
    }
  };

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const payload = buildRule(values);
    try {
      if (isEdit && rule) {
        const { number: _number, ...body } = payload;
        await updateRule.mutateAsync({
          name: routeMap.name,
          number: rule.number,
          payload: body,
        });
        toast.success(`Rule ${rule.number} updated`, {
          description: `${routeMap.name} policy saved on the router.`,
        });
      } else {
        await createRule.mutateAsync({
          name: routeMap.name,
          payload,
        });
        toast.success(`Rule ${payload.number} added`, {
          description: `${routeMap.name} now has ${routeMap.rules.length + 1} rules.`,
        });
      }
      onOpenChange(false);
    } catch (error) {
      if (
        !isEdit &&
        error instanceof ApiError &&
        error.code === "rule_exists"
      ) {
        form.setError("number", {
          type: "server",
          message: "A rule with this number already exists",
        });
        return;
      }
      const applied = applyServerFormErrors(error, form.setError, [
        "number",
        "action",
        "description",
        "on_match",
        "goto_rule",
        "call",
        "continue_rule",
      ]);
      if (!applied) {
        // 422 for a nested prefix-list name: jump to the Match tab so the
        // field error is visible instead of only a banner.
        if (applyPrefixListMatchErrors(error, form.setError)) {
          setTab("match");
          return;
        }
        setServerError(
          error instanceof ApiError
            ? error.message
            : "Could not save the rule. Review the fields and try again.",
        );
      }
    }
  }, onInvalid);

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ListFilter className="size-4 text-primary" />
            {isEdit
              ? `Edit rule ${rule?.number} · ${routeMap.name}`
              : `Add rule to ${routeMap.name}`}
          </DialogTitle>
          <DialogDescription>
            Rules are evaluated in ascending number order. A rule can match
            route attributes, then permit or deny and optionally rewrite
            attributes. Unsupported VyOS fields on an existing rule are
            preserved.
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not save rule">
            {serverError}
          </InlineAlert>
        )}

        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <Tabs value={tab} onValueChange={setTab} className="gap-3">
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="general">General</TabsTrigger>
                <TabsTrigger value="match">Match</TabsTrigger>
                <TabsTrigger value="set">Set actions</TabsTrigger>
              </TabsList>

              <TabsContent value="general" className="mt-1 space-y-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <TextField
                    control={form.control}
                    name="number"
                    label="Rule number"
                    hint="1–65535. Lower numbers are evaluated first."
                    placeholder="10"
                    inputMode="numeric"
                    disabled={isEdit || pending}
                  />
                  <SelectField
                    control={form.control}
                    name="action"
                    label="Action"
                    options={[
                      { value: "permit", label: "Permit" },
                      { value: "deny", label: "Deny" },
                    ]}
                    disabled={pending}
                  />
                </div>
                <TextField
                  control={form.control}
                  name="description"
                  label="Description"
                  hint="Optional operator note shown in the rules table."
                  placeholder="Allow transit prefixes"
                  mono={false}
                  disabled={pending}
                />
                <div className="grid gap-3 sm:grid-cols-3">
                  <SelectField
                    control={form.control}
                    name="on_match"
                    label="On match"
                    options={[
                      { value: "none", label: "None (finish)" },
                      { value: "next", label: "Next rule" },
                      { value: "goto", label: "Goto rule" },
                    ]}
                    disabled={pending}
                  />
                  <TextField
                    control={form.control}
                    name="goto_rule"
                    label="Goto rule"
                    hint="Required for goto; must differ from this number."
                    placeholder="20"
                    inputMode="numeric"
                    disabled={pending || onMatch !== "goto"}
                  />
                  <TextField
                    control={form.control}
                    name="continue_rule"
                    label="Continue rule"
                    hint="Evaluate this rule number after a match."
                    placeholder="Optional"
                    inputMode="numeric"
                    disabled={pending}
                  />
                </div>
                <TextField
                  control={form.control}
                  name="call"
                  label="Call route-map"
                  hint="Jump into another route map for evaluation. Must exist on the device."
                  placeholder="BGP-COMMON"
                  disabled={pending}
                />
                <InlineAlert tone="info" className="text-[11px]">
                  <span className="flex items-start gap-2">
                    <ListFilter className="mt-0.5 size-3.5 shrink-0" />
                    A rule with no match conditions matches every route. Use
                    deny rules deliberately — policy affects what is accepted
                    from or sent to BGP peers.
                  </span>
                </InlineAlert>
              </TabsContent>

              <TabsContent value="match" className="mt-1 space-y-4">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <SectionLabel>Prefix and path lists</SectionLabel>
                    <Link
                      href="/prefix-lists/"
                      className="inline-flex items-center gap-1 text-[10px] font-medium text-primary hover:underline"
                    >
                      <ListFilter className="size-3" /> Manage prefix lists
                    </Link>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <TextField
                      control={form.control}
                      name="m_ipv4_prefix_list"
                      label="IPv4 prefix-list"
                      hint={
                        ipv4PrefixLists.length > 0
                          ? `Must exist on the device. ${ipv4PrefixLists.length} IPv4 list${ipv4PrefixLists.length === 1 ? "" : "s"} offered as suggestions; free text is still allowed.`
                          : "Must exist on the device. Type a name, or create one under Prefix lists."
                      }
                      placeholder="TRANSIT-IN"
                      disabled={pending}
                      datalistId="route-map-ipv4-prefix-list-names"
                      datalistOptions={ipv4PrefixLists}
                    />
                    <TextField
                      control={form.control}
                      name="m_ipv6_prefix_list"
                      label="IPv6 prefix-list"
                      hint={
                        ipv6PrefixLists.length > 0
                          ? `Must exist on the device. ${ipv6PrefixLists.length} IPv6 list${ipv6PrefixLists.length === 1 ? "" : "s"} offered as suggestions; free text is still allowed.`
                          : "Must exist on the device. Type a name, or create one under Prefix lists."
                      }
                      placeholder="TRANSIT-IN6"
                      disabled={pending}
                      datalistId="route-map-ipv6-prefix-list-names"
                      datalistOptions={ipv6PrefixLists}
                    />
                    <TextField
                      control={form.control}
                      name="m_as_path"
                      label="AS-path list"
                      hint="AS-path access-list name on the device."
                      placeholder="AS-PATH-TRANSIT"
                      disabled={pending}
                    />
                    <div className="space-y-2">
                      <TextField
                        control={form.control}
                        name="m_community_list"
                        label="Community-list"
                        hint="Community-list name on the device."
                        placeholder="CUSTOMER-COMM"
                        disabled={pending}
                      />
                      <FormField
                        control={form.control}
                        name="m_community_exact"
                        render={({ field }) => (
                          <FormItem>
                            <div className="flex items-center justify-between gap-3 rounded-lg border border-border/70 bg-card/40 px-3 py-2">
                              <div className="min-w-0">
                                <FormLabel className="text-[12px]">
                                  Exact match
                                </FormLabel>
                                <p className="mt-0.5 text-[10px] text-muted-foreground">
                                  Require the community set to match exactly.
                                </p>
                              </div>
                              <FormControl>
                                <Switch
                                  checked={field.value}
                                  onCheckedChange={field.onChange}
                                  disabled={pending || !communityList.trim()}
                                  aria-label="Community exact match"
                                />
                              </FormControl>
                            </div>
                          </FormItem>
                        )}
                      />
                    </div>
                    <TextField
                      control={form.control}
                      name="m_large_community_list"
                      label="Large community-list"
                      hint="Large community-list name on the device."
                      placeholder="LARGE-COMM"
                      disabled={pending}
                    />
                    <TextField
                      control={form.control}
                      name="m_extcommunity"
                      label="Extcommunity"
                      hint="Extcommunity-list name on the device."
                      placeholder="EXTCOMM"
                      disabled={pending}
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <SectionLabel>Attributes</SectionLabel>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <TextField
                      control={form.control}
                      name="m_metric"
                      label="Metric"
                      hint="1–65535."
                      placeholder="100"
                      inputMode="numeric"
                      disabled={pending}
                    />
                    <TextField
                      control={form.control}
                      name="m_local_preference"
                      label="Local preference"
                      hint="0–4294967295."
                      placeholder="200"
                      inputMode="numeric"
                      disabled={pending}
                    />
                    <SelectField
                      control={form.control}
                      name="m_origin"
                      label="Origin"
                      options={ORIGIN_OPTIONS}
                      disabled={pending}
                    />
                    <TextField
                      control={form.control}
                      name="m_tag"
                      label="Tag"
                      hint="1–65535. Route tag, often used with routing protocols."
                      placeholder="Optional"
                      inputMode="numeric"
                      disabled={pending}
                    />
                    <SelectField
                      control={form.control}
                      name="m_protocol"
                      label="Protocol"
                      options={PROTOCOL_OPTIONS}
                      disabled={pending}
                    />
                    <SelectField
                      control={form.control}
                      name="m_rpki"
                      label="RPKI validation state"
                      hint="Only meaningful when RPKI is enabled on the device."
                      options={RPKI_OPTIONS}
                      disabled={pending}
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <SectionLabel>Next hop and interface</SectionLabel>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <TextField
                      control={form.control}
                      name="m_ip_nexthop"
                      label="IPv4 next-hop"
                      hint="Exact IPv4 next-hop address."
                      placeholder="192.0.2.1"
                      disabled={pending}
                    />
                    <TextField
                      control={form.control}
                      name="m_ipv6_nexthop"
                      label="IPv6 next-hop"
                      hint="Exact IPv6 next-hop address."
                      placeholder="2001:db8::1"
                      disabled={pending}
                    />
                    <TextField
                      control={form.control}
                      name="m_interface"
                      label="Interface"
                      hint="Incoming interface name on the device."
                      placeholder="eth0"
                      disabled={pending}
                    />
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="set" className="mt-1 space-y-4">
                <div className="space-y-2">
                  <SectionLabel>Path attributes</SectionLabel>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <TextField
                      control={form.control}
                      name="s_local_preference"
                      label="Local preference"
                      hint="0–4294967295. Leave empty to keep the current value."
                      placeholder="200"
                      inputMode="numeric"
                      disabled={pending}
                    />
                    <TextField
                      control={form.control}
                      name="s_metric"
                      label="Metric"
                      hint="0–4294967295, +N, -N, rtt, +rtt or -rtt."
                      placeholder="+50"
                      disabled={pending}
                    />
                    <SelectField
                      control={form.control}
                      name="s_origin"
                      label="Origin"
                      options={ORIGIN_OPTIONS}
                      disabled={pending}
                    />
                    <TextField
                      control={form.control}
                      name="s_weight"
                      label="Weight"
                      hint="0–4294967295. Local to this router, not advertised."
                      placeholder="Optional"
                      inputMode="numeric"
                      disabled={pending}
                    />
                    <SelectField
                      control={form.control}
                      name="s_metric_type"
                      label="Metric type"
                      hint="OSPF metric type, for OSPF-learned routes."
                      options={[
                        { value: "unset", label: "Unset" },
                        { value: "type-1", label: "Type 1" },
                        { value: "type-2", label: "Type 2" },
                      ]}
                      disabled={pending}
                    />
                    <TextField
                      control={form.control}
                      name="s_tag"
                      label="Tag"
                      hint="1–65535. Route tag."
                      placeholder="Optional"
                      inputMode="numeric"
                      disabled={pending}
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <SectionLabel>AS path and communities</SectionLabel>
                  <TextField
                    control={form.control}
                    name="s_as_prepend"
                    label="AS-path prepend"
                    hint="Comma or space separated ASNs, at most 20. Each AS is prepended once."
                    placeholder="64512, 64512"
                    disabled={pending}
                  />
                  <div className="grid gap-3 sm:grid-cols-2">
                    <SelectField
                      control={form.control}
                      name="s_community_action"
                      label="Community action"
                      hint="Unset leaves communities untouched."
                      options={[
                        { value: "unset", label: "Unset" },
                        { value: "add", label: "Add" },
                        { value: "replace", label: "Replace" },
                        { value: "delete", label: "Delete (list)" },
                        { value: "none", label: "None (remove all)" },
                      ]}
                      disabled={pending}
                    />
                    {(communityAction === "add" ||
                      communityAction === "replace") && (
                      <TextField
                        control={form.control}
                        name="s_community_values"
                        label="Community values"
                        hint="Comma separated, e.g. 64512:100, no-export."
                        placeholder="64512:100"
                        disabled={pending}
                      />
                    )}
                    {communityAction === "delete" && (
                      <TextField
                        control={form.control}
                        name="s_community_delete"
                        label="Delete community-list"
                        hint="Community-list name on the device."
                        placeholder="CUSTOMER-COMM"
                        disabled={pending}
                      />
                    )}
                  </div>
                </div>

                <div className="space-y-2">
                  <SectionLabel>Next hop and originator</SectionLabel>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <TextField
                      control={form.control}
                      name="s_ip_next_hop"
                      label="IPv4 next-hop"
                      hint="IPv4 address, unchanged or peer-address."
                      placeholder="192.0.2.1"
                      disabled={pending}
                    />
                    <TextField
                      control={form.control}
                      name="s_originator_id"
                      label="Originator ID"
                      hint="IPv4 address used for route-reflector loop detection."
                      placeholder="10.255.0.1"
                      disabled={pending}
                    />
                  </div>
                </div>
              </TabsContent>
            </Tabs>

            <DialogFooter className="gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={pending}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={pending}>
                {pending ? (
                  <>
                    <Loader2 className="size-4 animate-spin" /> Saving…
                  </>
                ) : (
                  <>
                    <Save className="size-4" />
                    {isEdit ? "Save rule" : "Add rule"}
                  </>
                )}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
