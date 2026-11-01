"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  RadioTower,
  Save,
  ShieldAlert,
} from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import {
  useCreateNeighbor,
  useRouteMaps,
  useUpdateNeighbor,
} from "@/lib/queries";
import {
  isNeighborAddress,
  isValidAsn,
} from "@/lib/validation";
import type {
  AddressFamilies,
  BgpNeighbor,
  BgpNeighborCreate,
  BgpNeighborUpdate,
} from "@/lib/types";
import {
  AddressFamilyBadges,
  AfSettingsEditor,
  makeAfSettings,
  withAfDefaults,
} from "@/components/bgp/shared";
import { Badge } from "@/components/ui/badge";
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
import { InlineAlert } from "@/components/states";

const optionalPort = (min: number, max: number) =>
  z
    .string()
    .optional()
    .refine(
      (value) =>
        !value ||
        (/^\d+$/.test(value) &&
          Number(value) >= min &&
          Number(value) <= max),
      `Must be an integer between ${min} and ${max}, or empty`,
    );

const optionalAsn = z
  .string()
  .optional()
  .refine((value) => !value || isValidAsn(value), "Must be a valid AS number");

function buildNeighborSchema(isEdit: boolean) {
  return z
  .object({
    address: z
      .string()
      .trim()
      .min(1, "Neighbor address is required")
      .refine(isNeighborAddress, "Enter an IP address or interface name"),
    remote_as: z
      .string()
      .trim()
      .refine(
        (value) => value === "" || isValidAsn(value),
        "Remote AS must be an integer from 1 to 4294967295",
      ),
    description: z
      .string()
      .max(255, "Description must be 255 characters or fewer")
      .optional(),
    peer_group: z.string().optional(),
    update_source: z
      .string()
      .max(64, "Update source is too long")
      .optional(),
    ebgp_multihop: optionalPort(1, 255),
    password: z.string().max(128, "Password is too long").optional(),
    remove_password: z.boolean(),
    passive: z.boolean(),
    shutdown: z.boolean(),
    keepalive: optionalPort(1, 65535),
    holdtime: optionalPort(3, 65535),
    local_as: optionalAsn,
    address_families: z.custom<AddressFamilies>(
      (value) => !!value && typeof value === "object",
      "Invalid address families",
    ),
  })
  .superRefine((values, ctx) => {
    if (
      !values.remote_as?.trim() &&
      !(isEdit && values.peer_group?.trim())
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["remote_as"],
        message: values.peer_group?.trim()
          ? "Remote AS is required when creating a neighbor"
          : "Remote AS is required",
      });
    }
    const hasKeepalive = !!values.keepalive?.trim();
    const hasHoldtime = !!values.holdtime?.trim();
    if (hasKeepalive !== hasHoldtime) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: [hasKeepalive ? "holdtime" : "keepalive"],
        message: "Set both keepalive and holdtime, or leave both empty",
      });
    }
    if (hasKeepalive && hasHoldtime) {
      if (Number(values.keepalive) >= Number(values.holdtime)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["holdtime"],
          message: "Holdtime must be greater than keepalive",
        });
      }
    }
    if (Object.keys(values.address_families ?? {}).length === 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["address_families"],
        message: "Activate at least one address family",
      });
    }
    if (values.local_as && Number(values.local_as) === 23456) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["local_as"],
        message: "23456 (AS_TRANS) cannot be used as a local AS",
      });
    }
  });
}

type NeighborFormValues = z.infer<ReturnType<typeof buildNeighborSchema>>;

function defaultsFor(neighbor: BgpNeighbor | null): NeighborFormValues {
  return {
    address: neighbor?.address ?? "",
    remote_as:
      neighbor?.remote_as != null ? String(neighbor.remote_as) : "",
    description: neighbor?.description ?? "",
    peer_group: neighbor?.peer_group ?? "",
    update_source: neighbor?.update_source ?? "",
    ebgp_multihop:
      neighbor?.ebgp_multihop != null ? String(neighbor.ebgp_multihop) : "",
    password: "",
    remove_password: false,
    passive: neighbor?.passive ?? false,
    shutdown: neighbor?.shutdown ?? false,
    keepalive:
      neighbor?.timers != null ? String(neighbor.timers.keepalive) : "",
    holdtime:
      neighbor?.timers != null ? String(neighbor.timers.holdtime) : "",
    local_as: neighbor?.local_as != null ? String(neighbor.local_as) : "",
    address_families: neighbor
      ? withAfDefaults(neighbor.address_families)
      : { "ipv4-unicast": makeAfSettings() },
  };
}

function SwitchRow({
  label,
  description,
  checked,
  onCheckedChange,
  disabled,
}: {
  label: string;
  description: string;
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-card/40 px-3 py-2.5">
      <div className="min-w-0">
        <p className="text-[13px] font-medium">{label}</p>
        <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
          {description}
        </p>
      </div>
      <Switch
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        aria-label={label}
      />
    </div>
  );
}

export function NeighborFormDialog({
  open,
  onOpenChange,
  routerId,
  neighbor,
  peerGroups,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  neighbor: BgpNeighbor | null;
  peerGroups: string[];
}) {
  const isEdit = !!neighbor;
  const [serverError, setServerError] = React.useState<string | null>(null);
  const [showPassword, setShowPassword] = React.useState(false);
  const createNeighbor = useCreateNeighbor(routerId);
  const updateNeighbor = useUpdateNeighbor(routerId);
  const routeMapsQuery = useRouteMaps(routerId);
  const routeMapNames = React.useMemo(
    () => (routeMapsQuery.data?.items ?? []).map((routeMap) => routeMap.name),
    [routeMapsQuery.data],
  );
  const pending = createNeighbor.isPending || updateNeighbor.isPending;

  const schema = React.useMemo(
    () => buildNeighborSchema(isEdit),
    [isEdit],
  );

  const form = useForm<NeighborFormValues>({
    resolver: zodResolver(schema),
    defaultValues: defaultsFor(neighbor),
    mode: "onSubmit",
  });

  React.useEffect(() => {
    if (!open) return;
    form.reset(defaultsFor(neighbor));
    setServerError(null);
    setShowPassword(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, neighbor?.address, routerId]);

  const removePassword = form.watch("remove_password");
  const families = form.watch("address_families");

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const remoteAs = values.remote_as?.trim()
      ? Number(values.remote_as)
      : null;
    const base = {
      description: values.description?.trim() ? values.description.trim() : null,
      peer_group: values.peer_group?.trim() ? values.peer_group.trim() : null,
      update_source: values.update_source?.trim()
        ? values.update_source.trim()
        : null,
      ebgp_multihop: values.ebgp_multihop?.trim()
        ? Number(values.ebgp_multihop)
        : null,
      passive: values.passive,
      shutdown: values.shutdown,
      timers:
        values.keepalive?.trim() && values.holdtime?.trim()
          ? {
              keepalive: Number(values.keepalive),
              holdtime: Number(values.holdtime),
            }
          : null,
      local_as: values.local_as?.trim() ? Number(values.local_as) : null,
      address_families: values.address_families,
    };

    try {
      if (isEdit && neighbor) {
        const payload: BgpNeighborUpdate = { ...base };
        // An empty AS with a peer group means "keep the inherited value";
        // omitting the field preserves it on the device.
        if (remoteAs !== null) payload.remote_as = remoteAs;
        if (values.remove_password) {
          payload.password = "";
        } else if (values.password?.trim()) {
          payload.password = values.password;
        }
        await updateNeighbor.mutateAsync({
          address: neighbor.address,
          payload,
        });
        toast.success("Neighbor updated", {
          description: `${neighbor.address} configuration saved.`,
        });
      } else {
        const payload: BgpNeighborCreate = {
          address: values.address.trim(),
          remote_as: Number(values.remote_as),
          ...base,
          password: values.password?.trim() ? values.password : undefined,
        };
        await createNeighbor.mutateAsync(payload);
        toast.success("Neighbor added", {
          description: `${payload.address} is configured on the router.`,
        });
      }
      onOpenChange(false);
    } catch (error) {
      const applied = applyServerFormErrors(error, form.setError, [
        "address",
        "remote_as",
        "description",
        "peer_group",
        "update_source",
        "ebgp_multihop",
        "password",
        "passive",
        "shutdown",
        "keepalive",
        "holdtime",
        "local_as",
        "address_families",
      ]);
      if (!applied) {
        setServerError(
          error instanceof ApiError
            ? error.message
            : "Could not save the neighbor. Review the fields and try again.",
        );
      }
    }
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <RadioTower className="size-4 text-primary" />
            {isEdit ? `Edit neighbor ${neighbor?.address}` : "Add BGP neighbor"}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update session parameters. The neighbor address is the key and cannot be changed."
              : "Create a peer session. Address families activate on the device when saved."}
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not save neighbor">
            {serverError}
          </InlineAlert>
        )}

        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-5" noValidate>
            <section className="space-y-3">
              <p className="text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                Identity
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <FormField
                  control={form.control}
                  name="address"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Neighbor address</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="192.0.2.1 or eth0"
                          className="font-mono"
                          disabled={isEdit || pending}
                          autoCapitalize="none"
                          spellCheck={false}
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>
                        IPv4, IPv6 or an interface for unnumbered peering.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="remote_as"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Remote AS</FormLabel>
                      <FormControl>
                        <Input
                          inputMode="numeric"
                          placeholder="65001"
                          className="font-mono"
                          disabled={pending}
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>
                        {isEdit && neighbor?.remote_as == null
                          ? "Inherited from the peer group. Leave empty to keep it."
                          : "eBGP/iBGP peer autonomous system."}
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <FormField
                  control={form.control}
                  name="peer_group"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Peer group</FormLabel>
                      <Select
                        value={field.value || "none"}
                        onValueChange={(value) =>
                          field.onChange(value === "none" ? "" : value)
                        }
                        disabled={pending}
                      >
                        <FormControl>
                          <SelectTrigger className="w-full">
                            <SelectValue placeholder="None" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="none">No peer group</SelectItem>
                          {peerGroups.map((group) => (
                            <SelectItem key={group} value={group}>
                              {group}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormDescription>
                        Inherits timers and policies from the group.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="description"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Description</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="Transit A"
                          disabled={pending}
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
            </section>

            <section className="space-y-3">
              <p className="text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                Session parameters
              </p>
              <div className="grid gap-3 sm:grid-cols-3">
                <FormField
                  control={form.control}
                  name="update_source"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Update source</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="eth0"
                          className="font-mono"
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
                  name="ebgp_multihop"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>eBGP multihop</FormLabel>
                      <FormControl>
                        <Input
                          inputMode="numeric"
                          placeholder="TTL"
                          className="font-mono"
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
                  name="local_as"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Local AS override</FormLabel>
                      <FormControl>
                        <Input
                          inputMode="numeric"
                          placeholder="Optional"
                          className="font-mono"
                          disabled={pending}
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <FormField
                  control={form.control}
                  name="keepalive"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Keepalive (s)</FormLabel>
                      <FormControl>
                        <Input
                          inputMode="numeric"
                          placeholder="30"
                          className="font-mono"
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
                  name="holdtime"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Holdtime (s)</FormLabel>
                      <FormControl>
                        <Input
                          inputMode="numeric"
                          placeholder="90"
                          className="font-mono"
                          disabled={pending}
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>
                        Leave both empty for device defaults.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <div className="flex items-center justify-between gap-2">
                      <FormLabel className="gap-2">
                        TCP MD5 password
                        {isEdit && neighbor?.password_configured && (
                          <Badge variant="success" className="gap-1 text-[9px]">
                            <KeyRound className="size-2.5" /> configured
                          </Badge>
                        )}
                      </FormLabel>
                      <span className="text-[10px] text-muted-foreground">
                        Write-only — never returned
                      </span>
                    </div>
                    <FormControl>
                      <div className="relative">
                        <Input
                          type={showPassword ? "text" : "password"}
                          placeholder={
                            isEdit && neighbor?.password_configured
                              ? "Leave blank to keep current password"
                              : "Optional"
                          }
                          autoComplete="new-password"
                          disabled={pending || removePassword}
                          className="pr-10 font-mono"
                          {...field}
                        />
                        <button
                          type="button"
                          onClick={() => setShowPassword((value) => !value)}
                          aria-label={
                            showPassword ? "Hide password" : "Show password"
                          }
                          aria-pressed={showPassword}
                          className="absolute top-1/2 right-1 -translate-y-1/2 rounded-md p-2 text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                        >
                          {showPassword ? (
                            <EyeOff className="size-4" />
                          ) : (
                            <Eye className="size-4" />
                          )}
                        </button>
                      </div>
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {isEdit && neighbor?.password_configured && (
                <SwitchRow
                  label="Remove configured password"
                  description="Clears the stored MD5 password on save; the session will flap."
                  checked={removePassword}
                  onCheckedChange={(checked) =>
                    form.setValue("remove_password", checked)
                  }
                  disabled={pending}
                />
              )}
            </section>

            <section className="space-y-3">
              <p className="text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                Behavior
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <FormField
                  control={form.control}
                  name="passive"
                  render={({ field }) => (
                    <FormItem>
                      <FormControl>
                        <SwitchRow
                          label="Passive"
                          description="Do not initiate the TCP connection."
                          checked={field.value}
                          onCheckedChange={field.onChange}
                          disabled={pending}
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="shutdown"
                  render={({ field }) => (
                    <FormItem>
                      <FormControl>
                        <SwitchRow
                          label="Administratively shut down"
                          description="Keep the peer configured but disabled."
                          checked={field.value}
                          onCheckedChange={field.onChange}
                          disabled={pending}
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />
              </div>
            </section>

            <section className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-[10px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                  Address families
                </p>
                <AddressFamilyBadges families={families} />
              </div>
              <FormField
                control={form.control}
                name="address_families"
                render={({ field }) => (
                  <FormItem>
                    <FormControl>
                      <AfSettingsEditor
                        value={field.value}
                        onChange={field.onChange}
                        disabled={pending}
                        routeMaps={routeMapNames}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </section>

            <InlineAlert tone="info" className="text-[11px]">
              <span className="flex items-start gap-2">
                <ShieldAlert className="mt-0.5 size-3.5 shrink-0" />
                Changes are committed to the router and recorded in the audit
                log. Session resets can briefly interrupt route exchange.
              </span>
            </InlineAlert>

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
                    {isEdit ? "Save neighbor" : "Add neighbor"}
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
