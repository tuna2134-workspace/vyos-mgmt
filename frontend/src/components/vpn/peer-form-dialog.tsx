"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { KeyRound, Loader2, Save, UsersRound } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError, errorMessage } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import {
  useCreateWireGuardPeer,
  useGenerateWireGuardPresharedKey,
  useUpdateWireGuardPeer,
} from "@/lib/queries";
import type {
  WireGuardPeer,
  WireGuardPeerCreate,
  WireGuardPeerUpdate,
} from "@/lib/types";
import { isEndpointHost, isPrefix, isWireGuardKey } from "@/lib/validation";
import {
  CopyButton,
  SecretKeyInput,
  applyListFieldErrors,
  splitLines,
} from "@/components/vpn/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { InlineAlert } from "@/components/states";

const KEY_ERROR =
  "Enter a Base64 32-byte key (44 characters ending with =)";
const ALIAS_ERROR =
  "Alias must be 1–100 characters with no spaces";

const FORM_FIELDS = [
  "name",
  "description",
  "public_key",
  "allowed_ips",
  "endpoint",
  "endpoint_port",
  "persistent_keepalive",
  "preshared_key",
  "enabled",
] as const;

interface PeerFormValues {
  name: string;
  description: string;
  public_key: string;
  allowed_ips: string;
  endpoint: string;
  endpoint_port: string;
  persistent_keepalive: string;
  preshared_key: string;
  remove_preshared_key: boolean;
  enabled: boolean;
}

function makeSchema(isEdit: boolean) {
  return z
    .object({
      name: z.string(),
      description: z.string(),
      public_key: z.string(),
      allowed_ips: z.string(),
      endpoint: z.string(),
      endpoint_port: z.string(),
      persistent_keepalive: z.string(),
      preshared_key: z.string(),
      remove_preshared_key: z.boolean(),
      enabled: z.boolean(),
    })
    .superRefine((values, ctx) => {
      if (!isEdit && !/^[^\s]{1,100}$/.test(values.name.trim())) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["name"],
          message: ALIAS_ERROR,
        });
      }

      if (values.description.trim().length > 255) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["description"],
          message: "Description must be 255 characters or fewer",
        });
      }

      if (!values.public_key.trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["public_key"],
          message: "A peer public key is required",
        });
      } else if (!isWireGuardKey(values.public_key)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["public_key"],
          message: KEY_ERROR,
        });
      }

      const allowedIps = splitLines(values.allowed_ips);
      if (allowedIps.length === 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["allowed_ips"],
          message: "At least one allowed IP prefix is required",
        });
      } else {
        const invalid = allowedIps.find((line) => !isPrefix(line));
        if (invalid) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["allowed_ips"],
            message: `"${invalid}" is not a canonical IPv4/IPv6 network (for example 192.168.50.0/24)`,
          });
        }
      }

      const endpoint = values.endpoint.trim();
      if (endpoint && !isEndpointHost(endpoint)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["endpoint"],
          message:
            "Enter an IPv4/IPv6 address or FQDN without a port (for example 198.51.100.10 or vpn.example.com)",
        });
      }

      const endpointPort = values.endpoint_port.trim();
      if (endpointPort) {
        if (
          !/^\d+$/.test(endpointPort) ||
          Number(endpointPort) < 1 ||
          Number(endpointPort) > 65535
        ) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["endpoint_port"],
            message: "Endpoint port must be an integer from 1 to 65535",
          });
        } else if (!endpoint) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["endpoint_port"],
            message: "Set an endpoint host before an endpoint port",
          });
        }
      }

      const keepalive = values.persistent_keepalive.trim();
      if (
        keepalive &&
        (!/^\d+$/.test(keepalive) ||
          Number(keepalive) < 1 ||
          Number(keepalive) > 65535)
      ) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["persistent_keepalive"],
          message: "Persistent keepalive must be an integer from 1 to 65535",
        });
      }

      const presharedKey = values.preshared_key.trim();
      if (presharedKey && !isWireGuardKey(presharedKey)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["preshared_key"],
          message: KEY_ERROR,
        });
      }
    });
}

function defaultsFor(peer: WireGuardPeer | null): PeerFormValues {
  return {
    name: peer?.name ?? "",
    description: peer?.description ?? "",
    public_key: peer?.public_key ?? "",
    allowed_ips: peer?.allowed_ips.join("\n") ?? "",
    endpoint: peer?.endpoint ?? "",
    endpoint_port: peer?.endpoint_port != null ? String(peer.endpoint_port) : "",
    persistent_keepalive:
      peer?.persistent_keepalive != null ? String(peer.persistent_keepalive) : "",
    // Preshared keys are write-only; reads only expose has_preshared_key.
    preshared_key: "",
    remove_preshared_key: false,
    enabled: peer?.enabled ?? true,
  };
}

function intOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function uniquePrefixes(lines: string[]): string[] {
  return [...new Set(lines)];
}

/**
 * Create / edit a WireGuard peer.
 *
 * `preshared_key` is tri-state on update: omitted keeps the configured key, a
 * new Base64 value replaces it and the explicit "remove" checkbox sends `null`.
 * A blank replace field never clears an existing key.
 */
export function WireGuardPeerFormDialog({
  open,
  onOpenChange,
  routerId,
  ifaceName,
  peer,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  ifaceName: string;
  peer: WireGuardPeer | null;
}) {
  const isEdit = peer !== null;
  const createPeer = useCreateWireGuardPeer(routerId);
  const updatePeer = useUpdateWireGuardPeer(routerId);
  const generatePresharedKey = useGenerateWireGuardPresharedKey(routerId);
  const pending = createPeer.isPending || updatePeer.isPending;

  const [serverError, setServerError] = React.useState<string | null>(null);

  const schema = React.useMemo(() => makeSchema(isEdit), [isEdit]);
  const form = useForm<PeerFormValues>({
    resolver: zodResolver(schema),
    defaultValues: defaultsFor(peer),
    mode: "onSubmit",
  });

  const replacePresharedKey = form.watch("preshared_key");
  const removePresharedKey = form.watch("remove_preshared_key");
  const hasStoredPresharedKey = isEdit ? !!peer?.has_preshared_key : false;

  React.useEffect(() => {
    if (!open) return;
    form.reset(defaultsFor(peer));
    setServerError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, peer?.name, ifaceName, routerId]);

  const handleGeneratePresharedKey = async () => {
    try {
      const result = await generatePresharedKey.mutateAsync();
      form.setValue("preshared_key", result.preshared_key, {
        shouldValidate: true,
        shouldDirty: true,
      });
      form.setValue("remove_preshared_key", false);
      setServerError(null);
      toast.success("Preshared key generated", {
        description: "Reveal or copy it, then save the peer to apply it.",
      });
    } catch (error) {
      toast.error("Could not generate a preshared key", {
        description: errorMessage(error),
      });
    }
  };

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const base = {
      description: values.description.trim() || null,
      public_key: values.public_key.trim(),
      allowed_ips: uniquePrefixes(splitLines(values.allowed_ips)),
      endpoint: values.endpoint.trim() || null,
      endpoint_port: intOrNull(values.endpoint_port),
      persistent_keepalive: intOrNull(values.persistent_keepalive),
      enabled: values.enabled,
    };

    try {
      if (isEdit && peer) {
        const payload: WireGuardPeerUpdate = { ...base };
        if (values.remove_preshared_key) {
          payload.preshared_key = null;
        } else if (values.preshared_key.trim()) {
          payload.preshared_key = values.preshared_key.trim();
        }
        // Blank replace field + no removal: omit the field so the API keeps
        // the existing preshared key.
        await updatePeer.mutateAsync({
          iface: ifaceName,
          peer: peer.name,
          payload,
        });
        toast.success(`${peer.name} updated`, {
          description: `Peer saved on ${ifaceName}.`,
        });
      } else {
        const payload: WireGuardPeerCreate = {
          name: values.name.trim(),
          ...base,
          preshared_key: values.preshared_key.trim() || null,
        };
        await createPeer.mutateAsync({ iface: ifaceName, payload });
        toast.success(`${payload.name} added`, {
          description: `Peer configured on ${ifaceName}.`,
        });
      }
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === "wireguard_peer_exists") {
          form.setError("name", {
            type: "server",
            message: "A peer with this alias already exists on the interface",
          });
          return;
        }
        if (error.code === "wireguard_allowed_ips_conflict") {
          form.setError("allowed_ips", {
            type: "server",
            message:
              "One of these prefixes is already assigned to another peer. The same prefix can belong to only one peer.",
          });
          return;
        }
        if (error.code === "wireguard_public_key_conflict") {
          form.setError("public_key", {
            type: "server",
            message: "Another peer already uses this public key",
          });
          return;
        }
      }

      const applied = applyServerFormErrors(error, form.setError, FORM_FIELDS);
      if (
        !applied &&
        applyListFieldErrors(error, form.setError, {
          allowed_ips: "allowed_ips",
        })
      ) {
        return;
      }
      setServerError(errorMessage(error));
    }
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!pending) onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UsersRound className="size-4 text-primary" />
            {isEdit ? `Edit peer ${peer?.name}` : `Add peer to ${ifaceName}`}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update the peer. The alias is immutable; the public key can be replaced."
              : "Peers are identified by an alias and their WireGuard public key. Allowed IPs route traffic into the tunnel."}
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not save the peer">
            {serverError}
          </InlineAlert>
        )}

        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <div className="grid gap-3 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Alias</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        placeholder="branch-office"
                        className="font-mono"
                        autoCapitalize="none"
                        spellCheck={false}
                        disabled={isEdit || pending}
                      />
                    </FormControl>
                    <FormDescription>
                      {isEdit
                        ? "Peer aliases are immutable in VyOS."
                        : "1–100 characters, no spaces."}
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
                        {...field}
                        placeholder="Branch router"
                        disabled={pending}
                      />
                    </FormControl>
                    <FormDescription>
                      Optional operator note.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="public_key"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Public key</FormLabel>
                  <div className="flex items-center gap-1.5">
                    <FormControl>
                      <Input
                        {...field}
                        placeholder="Base64 32-byte public key"
                        className="font-mono text-[11px]"
                        autoCapitalize="none"
                        spellCheck={false}
                        disabled={pending}
                      />
                    </FormControl>
                    <CopyButton
                      value={field.value}
                      label="Copy peer public key"
                      disabled={pending}
                    />
                  </div>
                  <FormDescription>
                    The remote peer&apos;s public key, not the interface&apos;s.
                    Public keys are safe to share.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="allowed_ips"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Allowed IPs</FormLabel>
                  <FormControl>
                    <Textarea
                      {...field}
                      rows={3}
                      placeholder={"192.168.50.0/24\n10.50.0.0/16"}
                      className="font-mono text-[12px]"
                      spellCheck={false}
                      disabled={pending}
                    />
                  </FormControl>
                  <FormDescription>
                    One canonical IPv4/IPv6 network per line. Required; the same
                    prefix cannot belong to two peers.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid gap-3 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="endpoint"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Endpoint</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        placeholder="198.51.100.10 or vpn.example.com"
                        className="font-mono"
                        autoCapitalize="none"
                        spellCheck={false}
                        disabled={pending}
                      />
                    </FormControl>
                    <FormDescription>
                      Remote address or FQDN, without the port.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="endpoint_port"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Endpoint port</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        placeholder="51820"
                        inputMode="numeric"
                        className="font-mono"
                        disabled={pending}
                      />
                    </FormControl>
                    <FormDescription>
                      1–65535. Empty uses the remote default.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="persistent_keepalive"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Persistent keepalive</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        placeholder="25"
                        inputMode="numeric"
                        className="font-mono"
                        disabled={pending}
                      />
                    </FormControl>
                    <FormDescription>
                      Seconds (1–65535). Useful behind NAT; empty disables it.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="enabled"
                render={({ field }) => (
                  <FormItem className="sm:pt-6">
                    <div className="flex items-center justify-between gap-3 rounded-lg border border-border/70 bg-card/40 px-3 py-2">
                      <div className="min-w-0">
                        <FormLabel className="text-[12px]">Enabled</FormLabel>
                        <p className="mt-0.5 text-[10px] text-muted-foreground">
                          Disabled peers keep their configuration but do not
                          negotiate.
                        </p>
                      </div>
                      <FormControl>
                        <Switch
                          checked={field.value}
                          onCheckedChange={field.onChange}
                          disabled={pending}
                          aria-label="Peer enabled"
                        />
                      </FormControl>
                    </div>
                  </FormItem>
                )}
              />
            </div>

            <div className="space-y-3 rounded-lg border border-border/70 p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-[12px] font-medium">
                      {isEdit ? "Replace preshared key" : "Preshared key"}
                    </p>
                    {isEdit && (
                      <Badge
                        variant={
                          hasStoredPresharedKey ? "success" : "muted"
                        }
                        className="text-[9px]"
                      >
                        <KeyRound className="size-3" />
                        {hasStoredPresharedKey
                          ? "configured"
                          : "not configured"}
                      </Badge>
                    )}
                  </div>
                  <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
                    {isEdit
                      ? "Write-only. Leave empty to keep the configured key, or enter a new Base64 key to replace it."
                      : "Optional. Adds an extra symmetric layer on top of the public key."}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void handleGeneratePresharedKey()}
                  disabled={pending || generatePresharedKey.isPending}
                >
                  {generatePresharedKey.isPending ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : (
                    <KeyRound className="size-3.5" />
                  )}
                  Generate preshared key
                </Button>
              </div>

              <FormField
                control={form.control}
                name="preshared_key"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel
                      className="sr-only"
                      htmlFor="wg-peer-preshared-key"
                    >
                      Preshared key
                    </FormLabel>
                    <SecretKeyInput
                      id="wg-peer-preshared-key"
                      value={field.value}
                      onChange={field.onChange}
                      onBlur={field.onBlur}
                      name={field.name}
                      inputRef={field.ref}
                      label="Preshared key"
                      placeholder={
                        isEdit && hasStoredPresharedKey
                          ? "Leave empty to keep the configured key"
                          : "Base64 32-byte preshared key"
                      }
                      disabled={pending || removePresharedKey}
                    />
                    <FormMessage />
                  </FormItem>
                )}
              />

              {isEdit && hasStoredPresharedKey && (
                <FormField
                  control={form.control}
                  name="remove_preshared_key"
                  render={({ field }) => (
                    <FormItem>
                      <div className="flex items-start gap-2.5">
                        <FormControl>
                          <Checkbox
                            checked={field.value}
                            onCheckedChange={(checked) => {
                              field.onChange(checked === true);
                              if (checked === true) {
                                form.setValue("preshared_key", "");
                              }
                            }}
                            disabled={pending || !!replacePresharedKey.trim()}
                            aria-label="Remove the configured preshared key"
                          />
                        </FormControl>
                        <div className="min-w-0">
                          <FormLabel className="text-[12px] font-normal">
                            Remove the configured preshared key
                          </FormLabel>
                          <p className="mt-0.5 text-[10px] text-muted-foreground">
                            Sends an explicit removal. Disabled while a
                            replacement key is entered.
                          </p>
                        </div>
                      </div>
                    </FormItem>
                  )}
                />
              )}
            </div>

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
                    {isEdit ? "Save peer" : "Add peer"}
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
