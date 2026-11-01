"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Eye, EyeOff, KeyRound, Loader2, Save, Server } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import { useCreateRouter, useUpdateRouter } from "@/lib/queries";
import { isIPAddress } from "@/lib/validation";
import type { Driver, Router, RouterProtocol, RouterUpdate } from "@/lib/types";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { InlineAlert } from "@/components/states";

function isHostname(value: string): boolean {
  return (
    /^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/.test(
      value,
    ) || isIPAddress(value)
  );
}

function buildSchema(isEdit: boolean, hasConfiguredKey: boolean) {
  return z
    .object({
      name: z
        .string()
        .trim()
        .min(1, "Name is required")
        .max(64, "Name must be 64 characters or fewer"),
      host: z
        .string()
        .trim()
        .min(1, "Host is required")
        .refine(isHostname, "Enter a valid IP address or hostname"),
      port: z
        .string()
        .trim()
        .min(1, "Port is required")
        .refine(
          (value) => {
            const n = Number(value);
            return /^\d+$/.test(value) && n >= 1 && n <= 65535;
          },
          "Port must be an integer between 1 and 65535",
        ),
      protocol: z.enum(["https", "http"]),
      driver: z.enum(["pyvyos", "mock"]),
      api_key: z.string().optional().default(""),
      verify_tls: z.boolean().default(true),
      description: z
        .string()
        .max(500, "Description must be 500 characters or fewer")
        .optional()
        .default(""),
      clear_api_key: z.boolean().default(false),
    })
    .superRefine((values, ctx) => {
      if (values.driver !== "pyvyos") return;
      const key = values.api_key?.trim() ?? "";
      if (!isEdit && !key) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["api_key"],
          message: "An API key is required for the pyvyos driver",
        });
      }
      if (isEdit && !hasConfiguredKey && !key) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["api_key"],
          message:
            "No API key is stored yet — provide one, or switch to the mock driver",
        });
      }
    });
}

type RouterFormValues = z.infer<ReturnType<typeof buildSchema>>;

function defaultsFor(router: Router | null): RouterFormValues {
  return {
    name: router?.name ?? "",
    host: router?.host ?? "",
    port: String(router?.port ?? 443),
    protocol: (router?.protocol ?? "https") as RouterProtocol,
    driver: (router?.driver ?? "pyvyos") as Driver,
    api_key: "",
    verify_tls: router?.verify_tls ?? true,
    description: router?.description ?? "",
    clear_api_key: false,
  };
}

export function RouterFormDialog({
  open,
  onOpenChange,
  router,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  router: Router | null;
  onSaved?: (router: Router, created: boolean) => void;
}) {
  const isEdit = !!router;
  const hasConfiguredKey = router?.api_key_configured ?? false;
  const [serverError, setServerError] = React.useState<string | null>(null);
  const [showKey, setShowKey] = React.useState(false);
  const createRouter = useCreateRouter();
  const updateRouter = useUpdateRouter();
  const pending = createRouter.isPending || updateRouter.isPending;

  const schema = React.useMemo(
    () => buildSchema(isEdit, hasConfiguredKey),
    [isEdit, hasConfiguredKey],
  );

  const form = useForm<RouterFormValues>({
    resolver: zodResolver(schema),
    defaultValues: defaultsFor(router),
    mode: "onSubmit",
  });

  React.useEffect(() => {
    if (!open) return;
    form.reset(defaultsFor(router));
    setServerError(null);
    setShowKey(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, router?.id]);

  const driver = form.watch("driver");
  const clearKey = form.watch("clear_api_key");

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const base = {
      name: values.name.trim(),
      host: values.host.trim(),
      port: Number(values.port),
      protocol: values.protocol,
      verify_tls: values.verify_tls,
      driver: values.driver,
      description: values.description?.trim() ? values.description.trim() : null,
    };

    try {
      if (isEdit && router) {
        const payload: RouterUpdate = { ...base };
        if (values.clear_api_key) {
          payload.api_key = "";
        } else if (values.api_key?.trim()) {
          payload.api_key = values.api_key.trim();
        }
        const updated = await updateRouter.mutateAsync({
          routerId: router.id,
          payload,
        });
        toast.success("Router updated", {
          description: `${updated.name} configuration saved.`,
        });
        onSaved?.(updated, false);
      } else {
        const created = await createRouter.mutateAsync({
          ...base,
          api_key: values.api_key?.trim() || undefined,
        });
        toast.success("Router added", {
          description: `${created.name} is now available in the fleet.`,
        });
        onSaved?.(created, true);
      }
      onOpenChange(false);
    } catch (error) {
      const applied = applyServerFormErrors(error, form.setError, [
        "name",
        "host",
        "port",
        "protocol",
        "driver",
        "api_key",
        "verify_tls",
        "description",
      ]);
      if (!applied) {
        setServerError(
          error instanceof ApiError
            ? error.message
            : "Could not save the router. Check the details and try again.",
        );
      }
    }
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Server className="size-4 text-primary" />
            {isEdit ? `Edit ${router?.name}` : "Add router"}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update connection details. Changes apply to the control plane only."
              : "Register a VyOS device. Credentials are encrypted at rest and never returned by the API."}
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not save router">
            {serverError}
          </InlineAlert>
        )}

        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input placeholder="edge-tokyo" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="driver"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Driver</FormLabel>
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
                        <SelectItem value="pyvyos">
                          pyvyos · real device
                        </SelectItem>
                        <SelectItem value="mock">mock · demo device</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      Mock devices need no API key and answer with canned data.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-[1fr_92px]">
              <FormField
                control={form.control}
                name="host"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Host</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="192.0.2.10"
                        autoCapitalize="none"
                        spellCheck={false}
                        className="font-mono"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="port"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Port</FormLabel>
                    <FormControl>
                      <Input
                        inputMode="numeric"
                        placeholder="443"
                        className="font-mono"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="protocol"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Protocol</FormLabel>
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
                        <SelectItem value="https">HTTPS</SelectItem>
                        <SelectItem value="http">HTTP</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="verify_tls"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center justify-between rounded-lg border border-border/80 px-3 py-2.5">
                    <div className="space-y-0.5">
                      <FormLabel className="text-[13px]">Verify TLS</FormLabel>
                      <p className="text-[11px] text-muted-foreground">
                        Recommended for production
                      </p>
                    </div>
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                        disabled={pending || form.watch("protocol") === "http"}
                        aria-label="Verify TLS certificate"
                      />
                    </FormControl>
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="api_key"
              render={({ field }) => (
                <FormItem>
                  <div className="flex items-center justify-between">
                    <FormLabel className="gap-2">
                      API key
                      {isEdit && hasConfiguredKey && (
                        <Badge variant="success" className="gap-1 text-[9px]">
                          <KeyRound className="size-2.5" /> configured
                        </Badge>
                      )}
                    </FormLabel>
                    {isEdit && (
                      <span className="text-[10px] text-muted-foreground">
                        Leave blank to keep the current key
                      </span>
                    )}
                  </div>
                  <FormControl>
                    <div className="relative">
                      <Input
                        type={showKey ? "text" : "password"}
                        placeholder={
                          driver === "mock"
                            ? "Not required for mock"
                            : isEdit && hasConfiguredKey
                              ? "••••••••••••"
                              : "vyos-api-key"
                        }
                        autoComplete="new-password"
                        disabled={pending || driver === "mock" || clearKey}
                        className="pr-10 font-mono"
                        {...field}
                      />
                      <button
                        type="button"
                        onClick={() => setShowKey((value) => !value)}
                        aria-label={showKey ? "Hide API key" : "Show API key"}
                        aria-pressed={showKey}
                        className="absolute top-1/2 right-1 -translate-y-1/2 rounded-md p-2 text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                      >
                        {showKey ? (
                          <EyeOff className="size-4" />
                        ) : (
                          <Eye className="size-4" />
                        )}
                      </button>
                    </div>
                  </FormControl>
                  <FormDescription>
                    {driver === "mock"
                      ? "The mock driver ignores credentials."
                      : "Stored encrypted at rest; the API only reports whether a key is configured."}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {isEdit && hasConfiguredKey && (
              <FormField
                control={form.control}
                name="clear_api_key"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center gap-2.5 rounded-lg border border-destructive/20 bg-destructive/[0.03] px-3 py-2.5">
                    <FormControl>
                      <Checkbox
                        checked={field.value}
                        onCheckedChange={(checked) =>
                          field.onChange(checked === true)
                        }
                        disabled={pending}
                        id="clear-api-key"
                      />
                    </FormControl>
                    <div>
                      <FormLabel
                        htmlFor="clear-api-key"
                        className="cursor-pointer text-[13px]"
                      >
                        Clear the stored API key
                      </FormLabel>
                      <p className="text-[11px] text-muted-foreground">
                        The router will fail authentication until a new key is
                        saved.
                      </p>
                    </div>
                  </FormItem>
                )}
              />
            )}

            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    <Textarea
                      rows={2}
                      placeholder="Tokyo edge · transit + peering"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter className="gap-2 pt-1">
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
                    {isEdit ? "Save changes" : "Add router"}
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
