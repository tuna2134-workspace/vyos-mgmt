"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Loader2,
  Plus,
  Route,
  Save,
  Trash2,
} from "lucide-react";
import {
  type Path,
  type UseFormSetError,
  useFieldArray,
  useForm,
} from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError, errorMessage } from "@/lib/api";
import {
  useCreateStaticRoute,
  useDeleteStaticRoute,
  useUpdateStaticRoute,
} from "@/lib/queries";
import type {
  StaticRoute,
  StaticRouteFamily,
  StaticRouteUpdate,
} from "@/lib/types";
import { isPrefix } from "@/lib/validation";
import {
  INTERFACE_NAME_PATTERN,
  ROUTE_TYPE_DESCRIPTION,
  ROUTE_TYPE_LABEL,
  STATIC_FAMILY_LABEL,
  STATIC_FAMILY_PLACEHOLDER,
  STATIC_FAMILY_VYOS_PATH,
  StaticFamilyBadge,
  RouteTypeBadge,
  nextHopMatchesFamily,
  nextHopPairKey,
  staticRouteType,
  type StaticRouteType,
} from "@/components/static-routes/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Textarea } from "@/components/ui/textarea";
import { InlineAlert, Spinner } from "@/components/states";

/* -------------------------------------------------------------------------- */
/* Validation                                                                 */
/* -------------------------------------------------------------------------- */

const NUMERIC = /^\d{1,10}$/;

/**
 * Blank means "device default" (`null`); `undefined` means the value is present
 * but not a valid integer in range.
 */
function parseOptionalInteger(
  value: string,
  min: number,
  max: number,
): number | null | undefined {
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (!NUMERIC.test(trimmed)) return undefined;
  const parsed = Number(trimmed);
  if (!Number.isSafeInteger(parsed) || parsed < min || parsed > max) {
    return undefined;
  }
  return parsed;
}

function isValidOptionalInteger(
  value: string,
  min: number,
  max: number,
): boolean {
  return parseOptionalInteger(value, min, max) !== undefined;
}

const nextHopSchema = z.object({
  address: z.string(),
  interface: z.string(),
  distance: z.string(),
  enabled: z.boolean(),
});

function makeSchema(isCreate: boolean) {
  return z
    .object({
      family: z.enum(["ipv4", "ipv6"]),
      prefix: z.string(),
      description: z.string(),
      route_type: z.enum(["gateway", "blackhole", "reject"]),
      distance: z.string(),
      tag: z.string(),
      next_hops: z.array(nextHopSchema),
    })
    .superRefine((values, ctx) => {
      if (isCreate) {
        const prefix = values.prefix.trim();
        if (!prefix) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["prefix"],
            message: "Prefix is required",
          });
        } else if (!isPrefix(prefix)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["prefix"],
            message: `Use CIDR notation with host bits zero, for example ${STATIC_FAMILY_PLACEHOLDER[values.family].prefix}`,
          });
        } else {
          const address = prefix.slice(0, prefix.lastIndexOf("/"));
          if (!nextHopMatchesFamily(address, values.family)) {
            ctx.addIssue({
              code: z.ZodIssueCode.custom,
              path: ["prefix"],
              message: `Prefix must be an ${STATIC_FAMILY_LABEL[values.family]} network`,
            });
          }
        }
      }

      if (values.description.trim().length > 255) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["description"],
          message: "Description must be 255 characters or fewer",
        });
      }

      if (values.route_type === "gateway") {
        if (values.next_hops.length === 0) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["next_hops"],
            message: "A gateway route needs at least one next hop",
          });
        }

        const seen = new Map<string, number>();
        values.next_hops.forEach((hop, index) => {
          const address = hop.address.trim();
          const iface = hop.interface.trim();

          if (!address && !iface) {
            ctx.addIssue({
              code: z.ZodIssueCode.custom,
              path: ["next_hops", index, "address"],
              message: "Enter a next-hop address, an interface, or both",
            });
          }
          if (address && !nextHopMatchesFamily(address, values.family)) {
            ctx.addIssue({
              code: z.ZodIssueCode.custom,
              path: ["next_hops", index, "address"],
              message: `${STATIC_FAMILY_LABEL[values.family]} host address without a prefix, for example ${STATIC_FAMILY_PLACEHOLDER[values.family].next_hop}`,
            });
          }
          if (iface && !INTERFACE_NAME_PATTERN.test(iface)) {
            ctx.addIssue({
              code: z.ZodIssueCode.custom,
              path: ["next_hops", index, "interface"],
              message: "Use a VyOS interface name such as eth0",
            });
          }
          if (!isValidOptionalInteger(hop.distance, 1, 255)) {
            ctx.addIssue({
              code: z.ZodIssueCode.custom,
              path: ["next_hops", index, "distance"],
              message: "Distance must be between 1 and 255",
            });
          }

          if (address || iface) {
            const key = nextHopPairKey({ address, interface: iface });
            const first = seen.get(key);
            if (first !== undefined) {
              ctx.addIssue({
                code: z.ZodIssueCode.custom,
                path: ["next_hops", index, address ? "address" : "interface"],
                message: `Duplicate next hop: row ${first + 1} already uses this address/interface pair`,
              });
            } else {
              seen.set(key, index);
            }
          }
        });
      } else {
        if (!isValidOptionalInteger(values.distance, 1, 255)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["distance"],
            message: "Distance must be between 1 and 255",
          });
        }
        if (!isValidOptionalInteger(values.tag, 1, 4294967295)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["tag"],
            message: "Tag must be between 1 and 4294967295",
          });
        }
      }
    });
}

const createSchema = makeSchema(true);
const editSchema = makeSchema(false);

type StaticRouteFormValues = z.infer<typeof createSchema>;

const FORM_FIELDS = [
  "prefix",
  "family",
  "description",
  "distance",
  "tag",
] as const;

const NEXT_HOP_FIELDS = ["address", "interface", "distance", "enabled"] as const;

function initialValues(
  route: StaticRoute | null,
  family: StaticRouteFamily,
): StaticRouteFormValues {
  if (!route) {
    return {
      family,
      prefix: "",
      description: "",
      route_type: "gateway",
      distance: "",
      tag: "",
      next_hops: [{ address: "", interface: "", distance: "", enabled: true }],
    };
  }

  const type = staticRouteType(route);
  const nextHops = route.next_hops.map((hop) => ({
    address: hop.address ?? "",
    interface: hop.interface ?? "",
    distance: hop.distance === null ? "" : String(hop.distance),
    enabled: hop.enabled,
  }));

  return {
    family: route.family,
    prefix: route.prefix,
    description: route.description ?? "",
    route_type: type,
    distance: route.distance === null ? "" : String(route.distance),
    tag: route.tag === null ? "" : String(route.tag),
    next_hops:
      nextHops.length > 0
        ? nextHops
        : [{ address: "", interface: "", distance: "", enabled: true }],
  };
}

/**
 * FastAPI 422 details are flat (`prefix`, `distance`, `tag`) or nested
 * (`next_hops.0.address`). Map both onto the form; anything else falls back to
 * the form-level banner.
 */
function applyServerErrors(
  error: unknown,
  setError: UseFormSetError<StaticRouteFormValues>,
  rowCount: number,
): boolean {
  if (!(error instanceof ApiError) || !Array.isArray(error.details)) {
    return false;
  }

  let applied = false;
  let allMapped = true;

  for (const detail of error.details) {
    if (!detail || !Array.isArray(detail.loc)) {
      allMapped = false;
      continue;
    }

    const loc = detail.loc.filter(
      (part): part is string | number =>
        (typeof part === "string" || typeof part === "number") &&
        part !== "body" &&
        part !== "query" &&
        part !== "path",
    );
    const message = detail.msg || "Invalid value";

    if (
      loc.length === 1 &&
      typeof loc[0] === "string" &&
      (FORM_FIELDS as readonly string[]).includes(loc[0])
    ) {
      setError(loc[0] as Path<StaticRouteFormValues>, {
        type: "server",
        message,
      });
      applied = true;
      continue;
    }

    if (
      loc[0] === "next_hops" &&
      typeof loc[1] === "number" &&
      typeof loc[2] === "string" &&
      (NEXT_HOP_FIELDS as readonly string[]).includes(loc[2]) &&
      loc[1] < rowCount
    ) {
      setError(
        `next_hops.${loc[1]}.${loc[2]}` as Path<StaticRouteFormValues>,
        { type: "server", message },
      );
      applied = true;
      continue;
    }

    // The backend may report a nested service error as one dotted token
    // ("next_hops.0.address") instead of a loc array; support both.
    if (typeof loc[0] === "string" && loc[0].startsWith("next_hops.")) {
      const [head, indexText, field] = loc[0].split(".");
      const index = Number(indexText);
      if (
        head === "next_hops" &&
        Number.isInteger(index) &&
        index >= 0 &&
        index < rowCount &&
        typeof field === "string" &&
        (NEXT_HOP_FIELDS as readonly string[]).includes(field)
      ) {
        setError(
          `next_hops.${index}.${field}` as Path<StaticRouteFormValues>,
          { type: "server", message },
        );
        applied = true;
        continue;
      }
    }

    allMapped = false;
  }

  return applied && allMapped;
}

/* -------------------------------------------------------------------------- */
/* Create / edit                                                              */
/* -------------------------------------------------------------------------- */

const ROUTE_TYPES: StaticRouteType[] = ["gateway", "blackhole", "reject"];

export function StaticRouteFormDialog({
  open,
  onOpenChange,
  routerId,
  family,
  route,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  /** Preselected from the active IPv4/IPv6 tab; changeable on create only. */
  family: StaticRouteFamily;
  /** `null` creates a route; a route edits it (family + prefix immutable). */
  route: StaticRoute | null;
  onSaved?: (route: StaticRoute) => void;
}) {
  const isEdit = !!route;
  const [serverError, setServerError] = React.useState<string | null>(null);
  const createRoute = useCreateStaticRoute(routerId);
  const updateRoute = useUpdateStaticRoute(routerId);
  const pending = createRoute.isPending || updateRoute.isPending;

  const form = useForm<StaticRouteFormValues>({
    resolver: zodResolver(isEdit ? editSchema : createSchema),
    defaultValues: initialValues(route, family),
    mode: "onSubmit",
  });

  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "next_hops",
  });

  const routeType = form.watch("route_type");
  const formFamily = form.watch("family");
  const nextHopError = form.formState.errors.next_hops;
  const nextHopArrayMessage =
    nextHopError?.root?.message ??
    (nextHopError as unknown as { message?: string } | undefined)?.message;

  React.useEffect(() => {
    if (!open) return;
    form.reset(initialValues(route, family));
    setServerError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, route?.family, route?.prefix, routerId, family]);

  // Switching a blank blackhole/reject route to gateway needs a first row.
  React.useEffect(() => {
    if (routeType !== "gateway") return;
    if (form.getValues("next_hops").length === 0) {
      append({ address: "", interface: "", distance: "", enabled: true });
    }
  }, [routeType, append, form]);

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const type = values.route_type;

    const shared: StaticRouteUpdate = {
      description: values.description.trim() || null,
      blackhole: type === "blackhole",
      reject: type === "reject",
      distance:
        type === "gateway"
          ? null
          : (parseOptionalInteger(values.distance, 1, 255) ?? null),
      tag:
        type === "gateway"
          ? null
          : (parseOptionalInteger(values.tag, 1, 4294967295) ?? null),
      next_hops:
        type === "gateway"
          ? values.next_hops.map((hop) => ({
              address: hop.address.trim() || null,
              interface: hop.interface.trim() || null,
              distance: parseOptionalInteger(hop.distance, 1, 255) ?? null,
              enabled: hop.enabled,
            }))
          : [],
    };

    try {
      const saved = route
        ? await updateRoute.mutateAsync({
            family: route.family,
            prefix: route.prefix,
            payload: shared,
          })
        : await createRoute.mutateAsync({
            family: values.family,
            prefix: values.prefix.trim(),
            ...shared,
          });

      onSaved?.(saved);
      toast.success(route ? "Static route updated" : "Static route created", {
        description: `${saved.prefix} (${STATIC_FAMILY_LABEL[saved.family]}) saved under ${STATIC_FAMILY_VYOS_PATH[saved.family]}.`,
      });
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError && error.code === "static_route_exists") {
        form.setError("prefix", {
          type: "server",
          message: `A ${STATIC_FAMILY_LABEL[values.family]} static route for this prefix already exists`,
        });
        return;
      }
      if (
        error instanceof ApiError &&
        error.code === "static_route_not_found"
      ) {
        setServerError(
          "This route no longer exists on the router. Close the dialog and refresh the list.",
        );
        return;
      }
      const applied = applyServerErrors(
        error,
        form.setError,
        form.getValues("next_hops").length,
      );
      if (!applied) setServerError(errorMessage(error));
    }
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Route className="size-4 text-primary" />
            {isEdit ? "Edit static route" : "New static route"}
          </DialogTitle>
          <DialogDescription>
            {isEdit ? (
              <>
                Full replacement of the managed fields for{" "}
                <span className="font-mono text-foreground">{route?.prefix}</span>.
                Family and prefix are immutable on the device, so delete and
                recreate the route to change either.
              </>
            ) : (
              <>
                A unicast route needs at least one next hop; blackhole and reject
                routes discard traffic instead. IPv4 routes live under{" "}
                <code className="font-mono text-[11px]">
                  protocols static route
                </code>
                , IPv6 under{" "}
                <code className="font-mono text-[11px]">
                  protocols static route6
                </code>
                .
              </>
            )}
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert
            tone="error"
            title={isEdit ? "Could not update route" : "Could not create route"}
          >
            {serverError}
          </InlineAlert>
        )}

        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <div className="grid gap-3 sm:grid-cols-[160px_minmax(0,1fr)]">
              <FormField
                control={form.control}
                name="family"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Address family</FormLabel>
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                      disabled={pending || isEdit}
                    >
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="ipv4">IPv4</SelectItem>
                        <SelectItem value="ipv6">IPv6</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="prefix"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Prefix</FormLabel>
                    <FormControl>
                      <Input
                        placeholder={
                          STATIC_FAMILY_PLACEHOLDER[formFamily].prefix
                        }
                        className="font-mono"
                        autoCapitalize="none"
                        spellCheck={false}
                        autoFocus={!isEdit}
                        disabled={pending || isEdit}
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      {isEdit
                        ? "Prefix and family identify the route and cannot be changed."
                        : "Canonical CIDR with host bits zero."}
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Default via transit"
                      rows={2}
                      className="resize-none text-sm"
                      disabled={pending}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Optional, up to 255 characters.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="route_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Route type</FormLabel>
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
                      {ROUTE_TYPES.map((type) => (
                        <SelectItem key={type} value={type}>
                          {ROUTE_TYPE_LABEL[type]} ·{" "}
                          {ROUTE_TYPE_DESCRIPTION[type]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            {routeType === "gateway" ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-[12px] font-medium">Next hops</p>
                    <p className="text-[10px] text-muted-foreground">
                      At least one row. Set an address, an interface, or both.
                    </p>
                  </div>
                  <Badge variant="muted" className="font-mono text-[9px]">
                    {fields.length} {fields.length === 1 ? "hop" : "hops"}
                  </Badge>
                </div>

                <div className="space-y-2">
                  {fields.map((item, index) => (
                    <div
                      key={item.id}
                      className="space-y-2 rounded-lg border border-border/70 p-2.5"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
                          Next hop {index + 1}
                        </span>
                        <div className="flex items-center gap-2">
                          <FormField
                            control={form.control}
                            name={`next_hops.${index}.enabled`}
                            render={({ field }) => (
                              <FormItem className="flex flex-row items-center gap-1.5 space-y-0">
                                <FormControl>
                                  <Checkbox
                                    checked={field.value}
                                    onCheckedChange={(checked) =>
                                      field.onChange(checked === true)
                                    }
                                    disabled={pending}
                                    aria-label={`Next hop ${index + 1} enabled`}
                                  />
                                </FormControl>
                                <FormLabel className="text-[11px] font-normal">
                                  Enabled
                                </FormLabel>
                              </FormItem>
                            )}
                          />
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => remove(index)}
                            disabled={pending || fields.length <= 1}
                            aria-label={`Remove next hop ${index + 1}`}
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        </div>
                      </div>

                      <div className="grid gap-2 sm:grid-cols-2">
                        <FormField
                          control={form.control}
                          name={`next_hops.${index}.address`}
                          render={({ field }) => (
                            <FormItem className="gap-1.5">
                              <FormLabel className="text-[11px]">
                                Address
                              </FormLabel>
                              <FormControl>
                                <Input
                                  placeholder={
                                    STATIC_FAMILY_PLACEHOLDER[formFamily]
                                      .next_hop
                                  }
                                  className="h-8 font-mono text-xs"
                                  autoCapitalize="none"
                                  spellCheck={false}
                                  disabled={pending}
                                  {...field}
                                />
                              </FormControl>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                        <FormField
                          control={form.control}
                          name={`next_hops.${index}.interface`}
                          render={({ field }) => (
                            <FormItem className="gap-1.5">
                              <FormLabel className="text-[11px]">
                                Interface
                              </FormLabel>
                              <FormControl>
                                <Input
                                  placeholder="eth0"
                                  className="h-8 font-mono text-xs"
                                  autoCapitalize="none"
                                  spellCheck={false}
                                  disabled={pending}
                                  {...field}
                                />
                              </FormControl>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      </div>

                      <FormField
                        control={form.control}
                        name={`next_hops.${index}.distance`}
                        render={({ field }) => (
                          <FormItem className="gap-1.5">
                            <FormLabel className="text-[11px]">
                              Distance
                            </FormLabel>
                            <FormControl>
                              <Input
                                inputMode="numeric"
                                placeholder="Device default"
                                className="h-8 max-w-40 font-mono text-xs"
                                disabled={pending}
                                {...field}
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </div>
                  ))}
                </div>

                {nextHopArrayMessage && (
                  <p className="text-[12px] text-destructive" role="alert">
                    {nextHopArrayMessage}
                  </p>
                )}

                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    append({
                      address: "",
                      interface: "",
                      distance: "",
                      enabled: true,
                    })
                  }
                  disabled={pending}
                >
                  <Plus className="size-4" /> Add next hop
                </Button>
              </div>
            ) : (
              <div className="space-y-2">
                <InlineAlert tone="warning" title="Traffic is discarded">
                  {routeType === "blackhole"
                    ? "Matching traffic is silently dropped. No next hops are configured."
                    : "Matching traffic is dropped and the sender receives an ICMP unreachable. No next hops are configured."}
                </InlineAlert>
                <div className="grid gap-3 sm:grid-cols-2">
                  <FormField
                    control={form.control}
                    name="distance"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Distance</FormLabel>
                        <FormControl>
                          <Input
                            inputMode="numeric"
                            placeholder="Device default"
                            className="font-mono"
                            disabled={pending}
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          1–255, optional.
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="tag"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Tag</FormLabel>
                        <FormControl>
                          <Input
                            inputMode="numeric"
                            placeholder="Unset"
                            className="font-mono"
                            disabled={pending}
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          1–4294967295, optional.
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              </div>
            )}

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
                    <Loader2 className="size-4 animate-spin" />{" "}
                    {isEdit ? "Saving…" : "Creating…"}
                  </>
                ) : (
                  <>
                    <Save className="size-4" />
                    {isEdit ? "Save route" : "Create route"}
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

/* -------------------------------------------------------------------------- */
/* Delete                                                                      */
/* -------------------------------------------------------------------------- */

export function StaticRouteDeleteDialog({
  open,
  onOpenChange,
  routerId,
  route,
  onDeleted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  route: StaticRoute | null;
  onDeleted?: (route: StaticRoute) => void;
}) {
  const [serverError, setServerError] = React.useState<string | null>(null);
  const deleteRoute = useDeleteStaticRoute(routerId);

  React.useEffect(() => {
    if (!open) return;
    setServerError(null);
  }, [open, route?.family, route?.prefix]);

  const handleDelete = async () => {
    if (!route) return;
    setServerError(null);
    try {
      await deleteRoute.mutateAsync({
        family: route.family,
        prefix: route.prefix,
      });
      toast.success("Static route deleted", {
        description: `${route.prefix} (${STATIC_FAMILY_LABEL[route.family]}) was removed from ${STATIC_FAMILY_VYOS_PATH[route.family]}.`,
      });
      onDeleted?.(route);
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError && error.code === "static_route_not_found") {
        toast.info("Route already removed", {
          description: `${route.prefix} no longer exists on the router.`,
        });
        onDeleted?.(route);
        onOpenChange(false);
        return;
      }
      const message = errorMessage(error);
      setServerError(message);
      toast.error("Could not delete route", { description: message });
    }
  };

  const type = route ? staticRouteType(route) : "gateway";

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !deleteRoute.isPending) onOpenChange(false);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <Trash2 className="size-4 text-destructive" />
            Delete static route {route?.prefix}?
          </AlertDialogTitle>
          <AlertDialogDescription>
            The route will be removed from{" "}
            <span className="font-mono">
              {route ? STATIC_FAMILY_VYOS_PATH[route.family] : "the router"}
            </span>
            . Matching traffic falls back to the remaining routing table. This
            cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Delete refused">
            {serverError}
          </InlineAlert>
        )}

        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          {route && (
            <>
              <StaticFamilyBadge family={route.family} />
              <RouteTypeBadge type={type} />
              <Badge variant="muted" className="font-mono text-[9px]">
                {type === "gateway"
                  ? `${route.next_hops.length} ${
                      route.next_hops.length === 1
                        ? "next hop"
                        : "next hops"
                    }`
                  : "No next hops"}
              </Badge>
            </>
          )}
        </div>

        {deleteRoute.isPending && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Spinner /> Deleting route…
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={deleteRoute.isPending}>
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            disabled={deleteRoute.isPending}
            onClick={(event) => {
              event.preventDefault();
              void handleDelete();
            }}
          >
            <Trash2 className="size-4" /> Delete route
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
