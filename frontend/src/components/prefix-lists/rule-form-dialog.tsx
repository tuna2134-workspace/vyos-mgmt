"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, ListFilter, Save } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import {
  useCreatePrefixListRule,
  useUpdatePrefixListRule,
} from "@/lib/queries";
import type {
  PrefixList,
  PrefixListRule,
  PrefixListRuleCreate,
} from "@/lib/types";
import { isPrefix, prefixMatchesAf } from "@/lib/validation";
import {
  FAMILY_LABEL,
  FAMILY_MAX_LENGTH,
  FAMILY_PLACEHOLDER,
  PrefixListFamilyBadge,
  prefixLength,
  suggestedRuleNumber,
} from "@/components/prefix-lists/shared";
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
import { InlineAlert } from "@/components/states";

const UNSIGNED = /^\d+$/;

const ruleSchema = z.object({
  number: z.string(),
  action: z.enum(["permit", "deny"]),
  prefix: z.string(),
  ge: z.string(),
  le: z.string(),
  description: z
    .string()
    .max(255, "Description must be 255 characters or fewer"),
});

type RuleFormValues = z.infer<typeof ruleSchema>;

function familyAf(family: PrefixList["family"]) {
  return family === "ipv4" ? "ipv4-unicast" : "ipv6-unicast";
}

function prefixError(value: string, family: PrefixList["family"]): string | null {
  const trimmed = value.trim();
  if (!trimmed) return "Prefix is required";
  if (!isPrefix(trimmed)) {
    return family === "ipv4"
      ? "Enter an IPv4 network in CIDR notation with host bits zero (e.g. 203.0.113.0/24)"
      : "Enter an IPv6 network in CIDR notation with host bits zero (e.g. 2001:db8::/32)";
  }
  if (!prefixMatchesAf(trimmed, familyAf(family))) {
    return `This prefix is not ${FAMILY_LABEL[family]}. ${family === "ipv4" ? "IPv6" : "IPv4"} prefixes belong in a ${family === "ipv4" ? "prefix-list6" : "prefix-list"}.`;
  }
  return null;
}

function makeRuleFormSchema(family: PrefixList["family"]) {
  const maxLength = FAMILY_MAX_LENGTH[family];
  return ruleSchema.superRefine((values, ctx) => {
    const number = Number(values.number.trim());
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

    const prefixIssue = prefixError(values.prefix, family);
    if (prefixIssue) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["prefix"],
        message: prefixIssue,
      });
    }

    const length = prefixIssue ? null : prefixLength(values.prefix.trim());

    const readBound = (field: "ge" | "le"): number | null | undefined => {
      const raw = values[field].trim();
      if (!raw) return null;
      // undefined = invalid, so a bad value does not also produce a
      // "must be >= prefix length" message.
      if (!UNSIGNED.test(raw) || Number(raw) < 0 || Number(raw) > maxLength) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: [field],
          message: `The ${field} value must be an integer from 0 to ${maxLength}`,
        });
        return undefined;
      }
      return Number(raw);
    };

    const ge = readBound("ge");
    const le = readBound("le");

    if (length !== null && ge !== null && ge !== undefined && ge < length) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["ge"],
        message: `ge must be at least the prefix length (${length})`,
      });
    }
    if (length !== null && le !== null && le !== undefined && le < length) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["le"],
        message: `le must be at least the prefix length (${length})`,
      });
    }
    if (
      ge !== null &&
      ge !== undefined &&
      le !== null &&
      le !== undefined &&
      ge > le
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["le"],
        message: "le must be greater than or equal to ge",
      });
    }
  });
}

function intOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function defaultsFor(
  prefixList: PrefixList,
  rule: PrefixListRule | null,
): RuleFormValues {
  return {
    number: rule
      ? String(rule.number)
      : String(suggestedRuleNumber(prefixList.rules)),
    action: rule?.action ?? "permit",
    prefix: rule?.prefix ?? "",
    ge: rule?.ge != null ? String(rule.ge) : "",
    le: rule?.le != null ? String(rule.le) : "",
    description: rule?.description ?? "",
  };
}

function buildRule(values: RuleFormValues): PrefixListRuleCreate {
  return {
    number: Number(values.number.trim()),
    action: values.action,
    prefix: values.prefix.trim(),
    ge: intOrNull(values.ge),
    le: intOrNull(values.le),
    description: values.description.trim() || null,
  };
}

export function PrefixListRuleFormDialog({
  open,
  onOpenChange,
  routerId,
  prefixList,
  rule,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  prefixList: PrefixList;
  rule: PrefixListRule | null;
}) {
  const isEdit = !!rule;
  const [serverError, setServerError] = React.useState<string | null>(null);
  const createRule = useCreatePrefixListRule(routerId);
  const updateRule = useUpdatePrefixListRule(routerId);
  const pending = createRule.isPending || updateRule.isPending;

  const schema = React.useMemo(
    () => makeRuleFormSchema(prefixList.family),
    [prefixList.family],
  );

  const form = useForm<RuleFormValues>({
    resolver: zodResolver(schema),
    defaultValues: defaultsFor(prefixList, rule),
    mode: "onSubmit",
  });

  React.useEffect(() => {
    if (!open) return;
    form.reset(defaultsFor(prefixList, rule));
    setServerError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, rule?.number, prefixList.family, prefixList.name, routerId]);

  const prefixValue = form.watch("prefix").trim();
  const length = isPrefix(prefixValue) ? prefixLength(prefixValue) : null;
  const maxLength = FAMILY_MAX_LENGTH[prefixList.family];

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const payload = buildRule(values);
    try {
      if (isEdit && rule) {
        const { number: _number, ...body } = payload;
        await updateRule.mutateAsync({
          family: prefixList.family,
          name: prefixList.name,
          number: rule.number,
          payload: body,
        });
        toast.success(`Rule ${rule.number} updated`, {
          description: `${prefixList.name} saved on the router.`,
        });
      } else {
        await createRule.mutateAsync({
          family: prefixList.family,
          name: prefixList.name,
          payload,
        });
        toast.success(`Rule ${payload.number} added`, {
          description: `${prefixList.name} now has ${prefixList.rules.length + 1} rules.`,
        });
      }
      onOpenChange(false);
    } catch (error) {
      if (
        !isEdit &&
        error instanceof ApiError &&
        error.code === "prefix_list_rule_exists"
      ) {
        form.setError("number", {
          type: "server",
          message: "A rule with this number already exists in this list",
        });
        return;
      }
      if (
        error instanceof ApiError &&
        error.code === "prefix_list_rule_duplicate"
      ) {
        setServerError(
          "An identical rule (same action, prefix, ge and le) already exists in this list. Change the prefix or the ge/le bounds.",
        );
        return;
      }
      const applied = applyServerFormErrors(error, form.setError, [
        "number",
        "action",
        "prefix",
        "ge",
        "le",
        "description",
      ]);
      if (!applied) {
        setServerError(
          error instanceof ApiError
            ? error.message
            : "Could not save the rule. Review the fields and try again.",
        );
      }
    }
  });

  const placeholder = FAMILY_PLACEHOLDER[prefixList.family];

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ListFilter className="size-4 text-primary" />
            {isEdit
              ? `Edit rule ${rule?.number} · ${prefixList.name}`
              : `Add rule to ${prefixList.name}`}
          </DialogTitle>
          <DialogDescription className="flex flex-wrap items-center gap-1.5">
            <PrefixListFamilyBadge family={prefixList.family} />
            Rules are evaluated in ascending number order; the first match wins
            unless the device is configured otherwise.
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not save rule">
            {serverError}
          </InlineAlert>
        )}

        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <div className="grid gap-3 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="number"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Rule number</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="10"
                        inputMode="numeric"
                        className="font-mono"
                        disabled={isEdit || pending}
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      1–65535. Lower numbers are evaluated first.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="action"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Action</FormLabel>
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                      disabled={pending}
                    >
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="permit">
                          Permit · accept matching prefixes
                        </SelectItem>
                        <SelectItem value="deny">
                          Deny · drop matching prefixes
                        </SelectItem>
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      Applied when a route matches this rule.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="prefix"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Prefix</FormLabel>
                  <FormControl>
                    <Input
                      placeholder={placeholder.prefix}
                      className="font-mono"
                      autoCapitalize="none"
                      spellCheck={false}
                      disabled={pending}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    A {FAMILY_LABEL[prefixList.family]} network in CIDR
                    notation; host bits must be zero.
                    {length !== null && (
                      <>
                        {" "}
                        Prefix length{" "}
                        <span className="font-mono text-foreground">{length}</span>
                        .
                      </>
                    )}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid gap-3 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="ge"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      ge <span className="font-normal">(minimum length)</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder="Optional"
                        inputMode="numeric"
                        className="font-mono"
                        disabled={pending}
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      0–{maxLength}
                      {length !== null ? ` and ≥ ${length}` : ""}.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="le"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      le <span className="font-normal">(maximum length)</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder="Optional"
                        inputMode="numeric"
                        className="font-mono"
                        disabled={pending}
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      0–{maxLength}
                      {length !== null ? ` and ≥ ${length}` : ""}.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <p className="text-[11px] text-muted-foreground">
              Leave ge/le empty for an exact-length match. Setting{" "}
              <span className="font-mono">le</span> only widens the match to more
              specific prefixes; <span className="font-mono">ge</span> and{" "}
              <span className="font-mono">le</span> together bound the accepted
              prefix length.
            </p>

            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="Customer /24s"
                      disabled={pending}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Optional operator note shown in the rules table.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

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
