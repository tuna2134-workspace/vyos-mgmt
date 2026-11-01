"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Loader2,
  LockKeyhole,
  RefreshCw,
  Save,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useAuth } from "@/lib/auth";
import {
  queryKeys,
  useBgpConfig,
  useDeleteBgpConfig,
  useUpdateBgpGlobal,
} from "@/lib/queries";
import { canWrite, isAdmin } from "@/lib/roles";
import { errorMessage } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import { isValidAsn, isIPv4 } from "@/lib/validation";
import type { Router } from "@/lib/types";
import {
  BgpPageHeading,
  BgpRouterBoundary,
} from "@/components/bgp/shared";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import {
  ErrorPanel,
  InlineAlert,
  Spinner,
  TableSkeleton,
} from "@/components/states";

const globalSchema = z.object({
  system_as: z
    .string()
    .trim()
    .min(1, "System AS is required")
    .refine(isValidAsn, "Enter an AS number between 1 and 4294967295"),
  router_id: z
    .string()
    .optional()
    .refine(
      (value) => !value || isIPv4(trimOrEmpty(value)),
      "Router ID must be a valid IPv4 address",
    ),
  log_neighbor_changes: z.boolean(),
});

function trimOrEmpty(value: string | undefined): string {
  return value?.trim() ?? "";
}

type GlobalFormValues = z.infer<typeof globalSchema>;

function SettingsContent({ router }: { router: Router }) {
  const { user } = useAuth();
  const writer = canWrite(user?.role);
  const admin = isAdmin(user?.role);
  const queryClient = useQueryClient();
  const configQuery = useBgpConfig(router.id);
  const updateGlobal = useUpdateBgpGlobal(router.id);
  const deleteConfig = useDeleteBgpConfig(router.id);

  const [serverError, setServerError] = React.useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const [confirmText, setConfirmText] = React.useState("");
  const [refreshing, setRefreshing] = React.useState(false);

  const form = useForm<GlobalFormValues>({
    resolver: zodResolver(globalSchema),
    defaultValues: {
      system_as: "",
      router_id: "",
      log_neighbor_changes: true,
    },
    mode: "onSubmit",
  });

  const config = configQuery.data;

  React.useEffect(() => {
    if (!config) return;
    form.reset({
      system_as: config.global.system_as != null ? String(config.global.system_as) : "",
      router_id: config.global.router_id ?? "",
      log_neighbor_changes: config.global.log_neighbor_changes ?? true,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config?.router.id, config?.configured, config?.global.system_as, config?.global.router_id, config?.global.log_neighbor_changes]);

  const refresh = async () => {
    setRefreshing(true);
    await queryClient.invalidateQueries({
      queryKey: queryKeys.bgpConfig(router.id),
    });
    setRefreshing(false);
  };

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    try {
      await updateGlobal.mutateAsync({
        system_as: Number(values.system_as),
        router_id: values.router_id?.trim() ? values.router_id.trim() : null,
        log_neighbor_changes: values.log_neighbor_changes,
      });
      toast.success("BGP global settings saved", {
        description: config?.configured
          ? "The managed global fields were updated on the router."
          : "BGP was configured on the router.",
      });
    } catch (error) {
      const applied = applyServerFormErrors(error, form.setError, [
        "system_as",
        "router_id",
        "log_neighbor_changes",
      ]);
      if (!applied) {
        setServerError(errorMessage(error));
      }
    }
  });

  const handleDelete = async () => {
    try {
      await deleteConfig.mutateAsync();
      toast.success("BGP configuration removed", {
        description: "protocols bgp was deleted from the router.",
      });
      setDeleteOpen(false);
      setConfirmText("");
    } catch (error) {
      toast.error("Could not remove BGP", {
        description: errorMessage(error),
      });
    }
  };

  const heading = (
    <BgpPageHeading
      title="BGP settings"
      routerName={router.name}
      description="Global autonomous system identity and high-risk configuration operations for this router."
      actions={
        <Button
          variant="outline"
          size="sm"
          onClick={() => void refresh()}
          disabled={refreshing}
        >
          <RefreshCw
            className={refreshing ? "size-3.5 animate-spin" : "size-3.5"}
          />
          Refresh
        </Button>
      }
    />
  );

  if (configQuery.isLoading) {
    return (
      <>
        {heading}
        <TableSkeleton rows={5} />
      </>
    );
  }

  if (configQuery.isError && !config) {
    return (
      <>
        {heading}
        <ErrorPanel
          title={`Could not read BGP from ${router.name}`}
          error={configQuery.error}
          onRetry={() => void configQuery.refetch()}
        />
      </>
    );
  }

  if (!config) return <>{heading}</>;

  return (
    <>
      {heading}

      {configQuery.isError && (
        <InlineAlert tone="warning" title="Showing cached settings">
          {errorMessage(configQuery.error)}
        </InlineAlert>
      )}
      {!config.configured && (
        <InlineAlert tone="info" title="BGP is not configured yet">
          Set a system AS below to create the BGP process on {router.name}. The
          rest of the console will populate once the configuration exists.
        </InlineAlert>
      )}
      {!writer && (
        <InlineAlert tone="info" title="Read-only view">
          Viewers can inspect global settings. Changes and deletion require
          elevated roles.
        </InlineAlert>
      )}

      <div className="grid gap-5 lg:grid-cols-[1.45fr_1fr]">
        <Card className="gap-4 border-t border-border/70 pt-4">
          <CardHeader className="gap-1 border-b border-border/60 pb-3">
            <CardTitle className="text-sm">Global BGP configuration</CardTitle>
            <CardDescription className="text-xs">
              These fields are the managed global scope of{" "}
              <span className="font-mono">{router.name}</span>.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {serverError && (
              <InlineAlert tone="error" title="Could not save settings" className="mb-4">
                {serverError}
              </InlineAlert>
            )}
            <Form {...form}>
              <form onSubmit={onSubmit} className="space-y-5" noValidate>
                <div className="grid gap-4 sm:grid-cols-2">
                  <FormField
                    control={form.control}
                    name="system_as"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>System AS</FormLabel>
                        <FormControl>
                          <Input
                            inputMode="numeric"
                            placeholder="64512"
                            className="font-mono"
                            disabled={!writer || updateGlobal.isPending}
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          Local autonomous system (1–4294967295).
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="router_id"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Router ID</FormLabel>
                        <FormControl>
                          <Input
                            placeholder="10.255.0.1"
                            className="font-mono"
                            disabled={!writer || updateGlobal.isPending}
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          IPv4 identifier. Leave empty to remove it.
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>

                <FormField
                  control={form.control}
                  name="log_neighbor_changes"
                  render={({ field }) => (
                    <FormItem className="flex flex-row items-center justify-between rounded-lg border border-border/70 px-4 py-3">
                      <div className="space-y-0.5">
                        <FormLabel className="text-[13px]">
                          Log neighbor changes
                        </FormLabel>
                        <p className="text-[11px] text-muted-foreground">
                          Emit a syslog message when a session changes state.
                        </p>
                      </div>
                      <FormControl>
                        <Switch
                          checked={field.value}
                          onCheckedChange={field.onChange}
                          disabled={!writer || updateGlobal.isPending}
                          aria-label="Log neighbor changes"
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />

                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-4">
                  <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    <LockKeyhole className="size-3.5" />
                    {writer
                      ? "Changes are committed to the device and audited."
                      : "Your role cannot modify BGP settings."}
                  </p>
                  <Button
                    type="submit"
                    disabled={!writer || updateGlobal.isPending}
                  >
                    {updateGlobal.isPending ? (
                      <>
                        <Loader2 className="size-4 animate-spin" /> Saving…
                      </>
                    ) : (
                      <>
                        <Save className="size-4" />
                        {config.configured ? "Save global settings" : "Configure BGP"}
                      </>
                    )}
                  </Button>
                </div>
              </form>
            </Form>
          </CardContent>
        </Card>

        <div className="space-y-5">
          <Card className="gap-0 border-t border-border/70 py-0">
            <CardHeader className="border-b border-border/60 px-5 py-3.5">
              <CardTitle className="text-sm">Configuration snapshot</CardTitle>
            </CardHeader>
            <CardContent className="divide-y divide-border/50 px-5 py-1">
              {[
                ["Configured", config.configured ? "Yes" : "No"],
                ["System AS", config.global.system_as ?? "—"],
                ["Router ID", config.global.router_id ?? "Not set"],
                [
                  "Log neighbor changes",
                  config.global.log_neighbor_changes ? "Enabled" : "Disabled",
                ],
                ["Neighbors", config.neighbors.length],
                ["Peer groups", config.peer_groups.length],
                ["Advertised networks", config.networks.length],
                [
                  "Managed families",
                  config.supported_address_families.join(", ") || "—",
                ],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="flex items-center justify-between gap-3 py-2.5 text-xs"
                >
                  <span className="text-muted-foreground">{label}</span>
                  <span className="max-w-[60%] truncate text-right font-mono text-[11px]">
                    {value}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card variant="surface" className="gap-4 border-destructive/30">
            <CardHeader className="gap-1">
              <CardTitle className="flex items-center gap-2 text-sm text-destructive">
                <ShieldAlert className="size-4" />
                Danger zone
              </CardTitle>
              <CardDescription className="text-xs leading-relaxed">
                Remove the entire managed BGP configuration from{" "}
                <span className="font-mono">{router.name}</span>. All neighbors,
                peer groups, networks and the global AS are deleted on the
                device. Other VyOS configuration is untouched.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {admin ? (
                <>
                  <div className="flex items-start gap-2.5 rounded-lg border border-destructive/20 bg-destructive/[0.04] px-3 py-2.5 text-[11px] leading-relaxed text-muted-foreground">
                    <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-destructive" />
                    Sessions will drop immediately. This cannot be undone from
                    the console.
                  </div>
                  <Button
                    variant="destructive"
                    className="w-full"
                    disabled={!config.configured}
                    onClick={() => {
                      setConfirmText("");
                      setDeleteOpen(true);
                    }}
                  >
                    <Trash2 className="size-4" /> Delete BGP configuration
                  </Button>
                  {!config.configured && (
                    <p className="text-center text-[10px] text-muted-foreground">
                      Nothing to delete — BGP is not configured.
                    </p>
                  )}
                </>
              ) : (
                <div className="flex items-start gap-2 text-[11px] leading-relaxed text-muted-foreground">
                  <LockKeyhole className="mt-0.5 size-3.5 shrink-0" />
                  Deleting the BGP configuration requires the administrator
                  role.
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <Dialog
        open={deleteOpen}
        onOpenChange={(next) => {
          if (!deleteConfig.isPending) {
            setDeleteOpen(next);
            if (!next) setConfirmText("");
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <ShieldAlert className="size-4" />
              Delete all BGP configuration
            </DialogTitle>
            <DialogDescription>
              This removes <span className="font-mono">protocols bgp</span> from{" "}
              {router.name}. Type the router name to confirm.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <div className="rounded-lg border border-destructive/25 bg-destructive/5 px-3 py-2.5 text-[11px] leading-relaxed text-muted-foreground">
              All {config.neighbors.length} neighbors,{" "}
              {config.peer_groups.length} peer groups and{" "}
              {config.networks.length} advertised networks will be removed.
              Sessions drop immediately.
            </div>
            <Input
              value={confirmText}
              onChange={(event) => setConfirmText(event.target.value)}
              placeholder={router.name}
              aria-label={`Type ${router.name} to confirm`}
              className="font-mono"
              autoComplete="off"
              disabled={deleteConfig.isPending}
            />
            <p className="text-[10px] text-muted-foreground">
              Expected: <span className="font-mono">{router.name}</span>
            </p>
          </div>
          {deleteConfig.isPending && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Spinner /> Deleting BGP configuration…
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteConfig.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={confirmText !== router.name || deleteConfig.isPending}
              onClick={() => void handleDelete()}
            >
              <Trash2 className="size-4" /> Delete permanently
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export default function BgpSettingsPage() {
  return (
    <BgpRouterBoundary>
      {(router) => <SettingsContent router={router} />}
    </BgpRouterBoundary>
  );
}
