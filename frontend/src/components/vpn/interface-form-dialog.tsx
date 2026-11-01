"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { KeyRound, Loader2, LockKeyhole, Save } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError, errorMessage } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import {
  useCreateWireGuardInterface,
  useGenerateWireGuardKeypair,
  useUpdateWireGuardInterface,
} from "@/lib/queries";
import type {
  WireGuardInterfaceCreate,
  WireGuardInterfaceDetail,
  WireGuardInterfaceUpdate,
  WireGuardKeypair,
} from "@/lib/types";
import { isCidr, isWireGuardKey } from "@/lib/validation";
import {
  KeyValueBlock,
  SecretKeyInput,
  applyListFieldErrors,
  splitLines,
} from "@/components/vpn/shared";
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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { InlineAlert } from "@/components/states";

const KEY_ERROR =
  "Enter a Base64 32-byte key (44 characters ending with =)";

const FORM_FIELDS = [
  "name",
  "description",
  "addresses",
  "port",
  "mtu",
  "enabled",
  "private_key",
] as const;

interface InterfaceFormValues {
  name: string;
  description: string;
  addresses: string;
  port: string;
  mtu: string;
  enabled: boolean;
  private_key: string;
}

function makeSchema(isEdit: boolean) {
  return z
    .object({
      name: z.string(),
      description: z.string(),
      addresses: z.string(),
      port: z.string(),
      mtu: z.string(),
      enabled: z.boolean(),
      private_key: z.string(),
    })
    .superRefine((values, ctx) => {
      if (!isEdit) {
        if (!/^wg[0-9]+$/.test(values.name.trim())) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["name"],
            message: "Use wg followed by a number, for example wg0",
          });
        }
        const privateKey = values.private_key.trim();
        if (!privateKey) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["private_key"],
            message: "A private key is required to create the interface",
          });
        } else if (!isWireGuardKey(privateKey)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["private_key"],
            message: KEY_ERROR,
          });
        }
      }

      if (values.description.trim().length > 255) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["description"],
          message: "Description must be 255 characters or fewer",
        });
      }

      const invalidAddress = splitLines(values.addresses).find(
        (line) => !isCidr(line),
      );
      if (invalidAddress) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["addresses"],
          message: `"${invalidAddress}" is not an IPv4/IPv6 CIDR (for example 10.100.0.1/24)`,
        });
      }

      const port = values.port.trim();
      if (
        port &&
        (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535)
      ) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["port"],
          message: "Listen port must be an integer from 1 to 65535",
        });
      }

      const mtu = values.mtu.trim();
      if (mtu && (!/^\d+$/.test(mtu) || Number(mtu) < 68 || Number(mtu) > 16000)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["mtu"],
          message: "MTU must be an integer from 68 to 16000",
        });
      }
    });
}

function suggestInterfaceName(existingNames: string[]): string {
  const used = new Set(existingNames);
  let index = 0;
  while (used.has(`wg${index}`)) index += 1;
  return `wg${index}`;
}

function defaultsFor(
  iface: WireGuardInterfaceDetail | null,
  existingNames: string[],
): InterfaceFormValues {
  return {
    name: iface?.name ?? suggestInterfaceName(existingNames),
    description: iface?.description ?? "",
    addresses: iface?.addresses.join("\n") ?? "",
    port: iface?.port != null ? String(iface.port) : "",
    mtu: iface?.mtu != null ? String(iface.mtu) : "",
    enabled: iface?.enabled ?? true,
    private_key: "",
  };
}

function intOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Create / edit a WireGuard interface.
 *
 * Create is the only place a private key is accepted: it is write-only, so the
 * edit form manages metadata only and offers key rotation separately. A keypair
 * generated here stays in form state until the interface is saved.
 */
export function WireGuardInterfaceFormDialog({
  open,
  onOpenChange,
  routerId,
  iface,
  existingNames,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  iface: WireGuardInterfaceDetail | null;
  existingNames: string[];
  onCreated?: (name: string) => void;
}) {
  const isEdit = iface !== null;
  const createInterface = useCreateWireGuardInterface(routerId);
  const updateInterface = useUpdateWireGuardInterface(routerId);
  const generateKeypair = useGenerateWireGuardKeypair(routerId);
  const pending = createInterface.isPending || updateInterface.isPending;

  const [serverError, setServerError] = React.useState<string | null>(null);
  const [generated, setGenerated] = React.useState<WireGuardKeypair | null>(
    null,
  );

  const schema = React.useMemo(() => makeSchema(isEdit), [isEdit]);
  const form = useForm<InterfaceFormValues>({
    resolver: zodResolver(schema),
    defaultValues: defaultsFor(iface, existingNames),
    mode: "onSubmit",
  });

  const privateKey = form.watch("private_key");
  // Re-derive visibility from the current value: editing or pasting over a
  // generated key must not keep showing an unrelated public key.
  const derivedPublicKey =
    generated && generated.private_key === privateKey
      ? generated.public_key
      : null;

  React.useEffect(() => {
    if (!open) return;
    form.reset(defaultsFor(iface, existingNames));
    setServerError(null);
    setGenerated(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, iface?.name, iface?.public_key, routerId]);

  const handleGenerate = async () => {
    try {
      const pair = await generateKeypair.mutateAsync();
      setGenerated(pair);
      form.setValue("private_key", pair.private_key, {
        shouldValidate: true,
        shouldDirty: true,
      });
      setServerError(null);
      toast.success("Keypair generated", {
        description: "The private key was filled in. Save to apply it.",
      });
    } catch (error) {
      toast.error("Could not generate a keypair", {
        description: errorMessage(error),
      });
    }
  };

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const payload: WireGuardInterfaceUpdate = {
      description: values.description.trim() || null,
      addresses: splitLines(values.addresses),
      port: intOrNull(values.port),
      mtu: intOrNull(values.mtu),
      enabled: values.enabled,
    };

    try {
      if (isEdit && iface) {
        await updateInterface.mutateAsync({ name: iface.name, payload });
        toast.success(`${iface.name} updated`, {
          description: "Interface metadata saved on the router.",
        });
        onOpenChange(false);
        return;
      }

      const body: WireGuardInterfaceCreate = {
        name: values.name.trim(),
        ...payload,
        private_key: values.private_key.trim(),
      };
      const detail = await createInterface.mutateAsync(body);
      toast.success(`${detail.name} created`, {
        description: `WireGuard interface configured on the router with ${detail.peer_count} peer${detail.peer_count === 1 ? "" : "s"}.`,
      });
      onCreated?.(detail.name);
      onOpenChange(false);
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.code === "wireguard_interface_exists"
      ) {
        form.setError("name", {
          type: "server",
          message: "An interface with this name already exists",
        });
        return;
      }
      const applied = applyServerFormErrors(error, form.setError, FORM_FIELDS);
      if (
        !applied &&
        applyListFieldErrors(error, form.setError, { addresses: "addresses" })
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
            <LockKeyhole className="size-4 text-primary" />
            {isEdit ? `Edit ${iface?.name}` : "New WireGuard interface"}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update the interface metadata. The private key and peers are untouched; use Rotate key to replace the key."
              : "Creates interfaces wireguard wgN on the router. The private key is write-only: it is sent once and never returned."}
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not save the interface">
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
                    <FormLabel>Interface name</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        className="font-mono"
                        placeholder="wg0"
                        autoCapitalize="none"
                        spellCheck={false}
                        disabled={isEdit || pending}
                      />
                    </FormControl>
                    <FormDescription>
                      {isEdit
                        ? "Interface names are immutable in VyOS."
                        : "VyOS names it wg followed by a number."}
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
                        placeholder="Tokyo branch tunnel"
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
              name="addresses"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Addresses</FormLabel>
                  <FormControl>
                    <Textarea
                      {...field}
                      rows={3}
                      placeholder={"10.100.0.1/24\n2001:db8:100::1/64"}
                      className="font-mono text-[12px]"
                      spellCheck={false}
                      disabled={pending}
                    />
                  </FormControl>
                  <FormDescription>
                    One IPv4/IPv6 CIDR per line. Host bits are allowed
                    (10.100.0.1/24). Leave empty for an unnumbered tunnel.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid gap-3 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="port"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Listen port</FormLabel>
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
                      1–65535. Empty uses the device default/random port.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="mtu"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>MTU</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        placeholder="1420"
                        inputMode="numeric"
                        className="font-mono"
                        disabled={pending}
                      />
                    </FormControl>
                    <FormDescription>
                      68–16000. Empty uses the device default (1420).
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="enabled"
              render={({ field }) => (
                <FormItem>
                  <div className="flex items-center justify-between gap-3 rounded-lg border border-border/70 bg-card/40 px-3 py-2">
                    <div className="min-w-0">
                      <FormLabel className="text-[12px]">Enabled</FormLabel>
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        Disabled keeps the configuration but removes the
                        interface from the live data plane.
                      </p>
                    </div>
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                        disabled={pending}
                        aria-label="Interface enabled"
                      />
                    </FormControl>
                  </div>
                </FormItem>
              )}
            />

            {isEdit ? (
              <InlineAlert tone="info" title="Private key is write-only">
                The API never returns the configured private key, so it cannot be
                edited here. Only the public key is shown after saving. Use{" "}
                <strong>Rotate key</strong> on the interface to replace it.
              </InlineAlert>
            ) : (
              <div className="space-y-3 rounded-lg border border-border/70 p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-[12px] font-medium">Private key</p>
                    <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
                      Write-only. Generate a keypair here or paste an existing
                      Base64 key. Only the derived public key is shown after
                      save.
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => void handleGenerate()}
                    disabled={pending || generateKeypair.isPending}
                  >
                    {generateKeypair.isPending ? (
                      <Loader2 className="size-3.5 animate-spin" />
                    ) : (
                      <KeyRound className="size-3.5" />
                    )}
                    Generate keypair
                  </Button>
                </div>

                <FormField
                  control={form.control}
                  name="private_key"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel
                        className="sr-only"
                        htmlFor="wg-interface-private-key"
                      >
                        Private key
                      </FormLabel>
                      <SecretKeyInput
                        id="wg-interface-private-key"
                        value={field.value}
                        onChange={field.onChange}
                        onBlur={field.onBlur}
                        name={field.name}
                        inputRef={field.ref}
                        label="Private key"
                        placeholder="Base64 32-byte private key"
                        disabled={pending}
                      />
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {derivedPublicKey ? (
                  <KeyValueBlock
                    label="Derived public key"
                    value={derivedPublicKey}
                    copyLabel="Copy derived public key"
                    hint="Share this with peers. The keypair is not saved until the interface is created."
                  />
                ) : (
                  <p className="text-[10px] text-muted-foreground">
                    A public key appears here after generating a keypair. A
                    pasted key&apos;s public key is derived by the router on save.
                  </p>
                )}
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
                    <Loader2 className="size-4 animate-spin" /> Saving…
                  </>
                ) : (
                  <>
                    <Save className="size-4" />
                    {isEdit ? "Save interface" : "Create interface"}
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
