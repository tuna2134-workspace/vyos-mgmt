"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  AlertTriangle,
  Loader2,
  LockKeyhole,
  Save,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useAuth } from "@/lib/auth";
import { errorMessage } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import { useDeleteOspfProcess, useUpdateOspfGlobal } from "@/lib/queries";
import { canWrite, isAdmin } from "@/lib/roles";
import { isIPv4 } from "@/lib/validation";
import type { OspfConfig, OspfLogAdjacencyChanges, Router } from "@/lib/types";
import {
  LOG_ADJACENCY_LABEL,
  VERSION_LABEL,
  VERSION_VYOS_PATH,
  isOptionalIntegerInRange,
  optionalInteger,
} from "@/components/ospf/shared";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { InlineAlert, Spinner } from "@/components/states";

const LOG_LEVELS: OspfLogAdjacencyChanges[] = ["none", "normal", "detail"];
/** VyOS `auto-cost reference-bandwidth` is in Mbps. */
const MAX_REFERENCE_BANDWIDTH = 4_294_967;

const globalSchema = z
  .object({
    router_id: z.string(),
    log_adjacency_changes: z.enum(["none", "normal", "detail"]),
    auto_cost_reference_bandwidth: z.string(),
    default_information_originate: z.boolean(),
    default_information_always: z.boolean(),
    distance_global: z.string(),
  })
  .superRefine((values, ctx) => {
    const routerId = values.router_id.trim();
    if (routerId && !isIPv4(routerId)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["router_id"],
        message: "Router ID must be a valid IPv4 address",
      });
    }
    if (
      !isOptionalIntegerInRange(
        values.auto_cost_reference_bandwidth,
        1,
        MAX_REFERENCE_BANDWIDTH,
      )
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["auto_cost_reference_bandwidth"],
        message: `Reference bandwidth must be between 1 and ${MAX_REFERENCE_BANDWIDTH}`,
      });
    }
    if (!isOptionalIntegerInRange(values.distance_global, 1, 255)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["distance_global"],
        message: "Distance must be between 1 and 255",
      });
    }
    if (
      values.default_information_always &&
      !values.default_information_originate
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["default_information_always"],
        message: "Enable default-information originate first",
      });
    }
  });

type GlobalFormValues = z.infer<typeof globalSchema>;

export function OspfSettingsPanel({
  router,
  config,
}: {
  router: Router;
  config: OspfConfig;
}) {
  const { user } = useAuth();
  const writer = canWrite(user?.role);
  const admin = isAdmin(user?.role);
  const version = config.version;
  const updateGlobal = useUpdateOspfGlobal(router.id, version);
  const deleteProcess = useDeleteOspfProcess(router.id, version);

  const [serverError, setServerError] = React.useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const [confirmText, setConfirmText] = React.useState("");
  const [deleteError, setDeleteError] = React.useState<string | null>(null);

  const form = useForm<GlobalFormValues>({
    resolver: zodResolver(globalSchema),
    defaultValues: {
      router_id: "",
      log_adjacency_changes: "none",
      auto_cost_reference_bandwidth: "",
      default_information_originate: false,
      default_information_always: false,
      distance_global: "",
    },
    mode: "onSubmit",
  });

  const global = config.global;

  React.useEffect(() => {
    form.reset({
      router_id: global.router_id ?? "",
      log_adjacency_changes: global.log_adjacency_changes ?? "none",
      auto_cost_reference_bandwidth:
        global.auto_cost_reference_bandwidth === null
          ? ""
          : String(global.auto_cost_reference_bandwidth),
      default_information_originate: global.default_information_originate,
      default_information_always: global.default_information_always,
      distance_global:
        global.distance_global === null ? "" : String(global.distance_global),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    config.router.id,
    config.version,
    global.router_id,
    global.log_adjacency_changes,
    global.auto_cost_reference_bandwidth,
    global.default_information_originate,
    global.default_information_always,
    global.distance_global,
  ]);

  const originate = form.watch("default_information_originate");

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    try {
      await updateGlobal.mutateAsync({
        router_id: values.router_id.trim() || null,
        log_adjacency_changes: values.log_adjacency_changes,
        auto_cost_reference_bandwidth: optionalInteger(
          values.auto_cost_reference_bandwidth,
        ),
        default_information_originate: values.default_information_originate,
        default_information_always:
          values.default_information_originate &&
          values.default_information_always,
        distance_global: optionalInteger(values.distance_global),
      });
      toast.success("OSPF global settings saved", {
        description: config.configured
          ? `${VERSION_VYOS_PATH[version]} global fields updated on ${router.name}.`
          : `${VERSION_LABEL[version]} was configured on ${router.name}.`,
      });
    } catch (error) {
      const applied = applyServerFormErrors(error, form.setError, [
        "router_id",
        "log_adjacency_changes",
        "auto_cost_reference_bandwidth",
        "default_information_originate",
        "default_information_always",
        "distance_global",
      ]);
      if (!applied) {
        setServerError(errorMessage(error));
      }
    }
  });

  const handleDelete = async () => {
    setDeleteError(null);
    try {
      await deleteProcess.mutateAsync();
      toast.success(`${VERSION_LABEL[version]} process removed`, {
        description: `${VERSION_VYOS_PATH[version]} was deleted from ${router.name}.`,
      });
      setDeleteOpen(false);
      setConfirmText("");
    } catch (error) {
      const message = errorMessage(error);
      setDeleteError(message);
      toast.error("Could not delete the OSPF process", {
        description: message,
      });
    }
  };

  return (
    <div className="space-y-5">
      {!config.configured && (
        <InlineAlert tone="info" title="OSPF is not configured yet">
          Saving global settings creates{" "}
          <code className="font-mono text-[11px]">
            {VERSION_VYOS_PATH[version]}
          </code>{" "}
          on {router.name}. A process without interfaces is valid; add areas and
          interfaces to form adjacencies.
        </InlineAlert>
      )}

      <div className="grid items-start gap-5 lg:grid-cols-[1.45fr_1fr]">
        <Card className="gap-4 border-t border-border/70 pt-4">
          <CardHeader className="gap-1 border-b border-border/60 pb-3">
            <CardTitle className="text-sm">Global OSPF configuration</CardTitle>
            <CardDescription className="text-xs">
              Managed global scope of{" "}
              <span className="font-mono">{VERSION_VYOS_PATH[version]}</span> on{" "}
              <span className="font-mono">{router.name}</span>.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {serverError && (
              <InlineAlert
                tone="error"
                title="Could not save settings"
                className="mb-4"
              >
                {serverError}
              </InlineAlert>
            )}
            <Form {...form}>
              <form onSubmit={onSubmit} className="space-y-5" noValidate>
                <div className="grid gap-4 sm:grid-cols-2">
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
                            autoCapitalize="none"
                            autoCorrect="off"
                            spellCheck={false}
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
                  <FormField
                    control={form.control}
                    name="log_adjacency_changes"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Log adjacency changes</FormLabel>
                        <Select
                          value={field.value}
                          onValueChange={field.onChange}
                          disabled={!writer || updateGlobal.isPending}
                        >
                          <FormControl>
                            <SelectTrigger className="w-full">
                              <SelectValue />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            {LOG_LEVELS.map((level) => (
                              <SelectItem key={level} value={level}>
                                {LOG_ADJACENCY_LABEL[level]}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <FormDescription>
                          Syslog detail for neighbor state changes.
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <FormField
                    control={form.control}
                    name="auto_cost_reference_bandwidth"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Auto-cost reference bandwidth</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            inputMode="numeric"
                            min={1}
                            max={MAX_REFERENCE_BANDWIDTH}
                            placeholder="100"
                            className="font-mono"
                            disabled={!writer || updateGlobal.isPending}
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          1–4294967 Mbps; empty = device default.
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="distance_global"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Administrative distance</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            inputMode="numeric"
                            min={1}
                            max={255}
                            placeholder="110"
                            className="font-mono"
                            disabled={!writer || updateGlobal.isPending}
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          1–255; empty = device default.
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>

                <div className="space-y-2 rounded-xl border border-border/70 bg-muted/20 p-3">
                  <FormField
                    control={form.control}
                    name="default_information_originate"
                    render={({ field }) => (
                      <FormItem className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <div className="space-y-0.5">
                          <FormLabel className="text-[13px]">
                            Default-information originate
                          </FormLabel>
                          <p className="text-[10px] leading-relaxed text-muted-foreground">
                            Originate a default route into the OSPF domain.
                          </p>
                        </div>
                        <FormControl>
                          <Switch
                            checked={field.value}
                            onCheckedChange={(checked) => {
                              field.onChange(checked);
                              // `always` is meaningless without originate.
                              if (!checked) {
                                form.setValue(
                                  "default_information_always",
                                  false,
                                );
                              }
                            }}
                            disabled={!writer || updateGlobal.isPending}
                            aria-label="Default-information originate"
                          />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="default_information_always"
                    render={({ field }) => (
                      <FormItem className="flex flex-col gap-2 border-t border-border/60 pt-2 sm:flex-row sm:items-center sm:justify-between">
                        <div className="space-y-0.5">
                          <FormLabel className="text-[13px]">
                            Always advertise the default
                          </FormLabel>
                          <p className="text-[10px] leading-relaxed text-muted-foreground">
                            Advertise even when no default route is present.
                            Requires originate.
                          </p>
                        </div>
                        <FormControl>
                          <Switch
                            checked={originate && field.value}
                            onCheckedChange={field.onChange}
                            disabled={
                              !writer || updateGlobal.isPending || !originate
                            }
                            aria-label="Always advertise the default route"
                          />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-4">
                  <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    <LockKeyhole className="size-3.5" />
                    {writer
                      ? "Changes are committed to the device and audited."
                      : "Your role cannot modify OSPF settings."}
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
                        {config.configured
                          ? "Save global settings"
                          : "Configure OSPF"}
                      </>
                    )}
                  </Button>
                </div>
              </form>
            </Form>
          </CardContent>
        </Card>

        <Card variant="surface" className="gap-4 border-destructive/30">
          <CardHeader className="gap-1">
            <CardTitle className="flex items-center gap-2 text-sm text-destructive">
              <ShieldAlert className="size-4" />
              Danger zone
            </CardTitle>
            <CardDescription className="text-xs leading-relaxed">
              Remove the entire{" "}
              <span className="font-mono">{VERSION_VYOS_PATH[version]}</span>{" "}
              subtree from <span className="font-mono">{router.name}</span>. All
              global settings, areas, interfaces and redistribution entries are
              deleted on the device. Other VyOS configuration is untouched.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {admin ? (
              <>
                <div className="flex items-start gap-2.5 rounded-lg border border-destructive/20 bg-destructive/[0.04] px-3 py-2.5 text-[11px] leading-relaxed text-muted-foreground">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-destructive" />
                  Adjacencies drop immediately. This cannot be undone from the
                  console.
                </div>
                <Button
                  variant="destructive"
                  className="w-full"
                  disabled={!config.configured || deleteProcess.isPending}
                  onClick={() => {
                    setConfirmText("");
                    setDeleteError(null);
                    setDeleteOpen(true);
                  }}
                >
                  <Trash2 className="size-4" /> Delete {VERSION_LABEL[version]}
                </Button>
                {!config.configured && (
                  <p className="text-center text-[10px] text-muted-foreground">
                    Nothing to delete — {VERSION_LABEL[version]} is not
                    configured.
                  </p>
                )}
              </>
            ) : (
              <div className="flex items-start gap-2 text-[11px] leading-relaxed text-muted-foreground">
                <LockKeyhole className="mt-0.5 size-3.5 shrink-0" />
                Deleting an entire OSPF process requires the administrator role.
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog
        open={deleteOpen}
        onOpenChange={(next) => {
          if (!deleteProcess.isPending) {
            setDeleteOpen(next);
            if (!next) {
              setConfirmText("");
              setDeleteError(null);
            }
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <ShieldAlert className="size-4" />
              Delete {VERSION_LABEL[version]}
            </DialogTitle>
            <DialogDescription>
              This removes <span className="font-mono">
                {VERSION_VYOS_PATH[version]}
              </span>{" "}
              from {router.name}. Type the router name to confirm.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <div className="rounded-lg border border-destructive/25 bg-destructive/5 px-3 py-2.5 text-[11px] leading-relaxed text-muted-foreground">
              {config.areas.length} area
              {config.areas.length === 1 ? "" : "s"}, {config.interfaces.length}{" "}
              interface{config.interfaces.length === 1 ? "" : "s"} and{" "}
              {config.redistributions.length} redistribution entr
              {config.redistributions.length === 1 ? "y" : "ies"} will be
              removed. Sessions drop immediately.
            </div>
            <Input
              value={confirmText}
              onChange={(event) => setConfirmText(event.target.value)}
              placeholder={router.name}
              aria-label={`Type ${router.name} to confirm`}
              className="font-mono"
              autoComplete="off"
              disabled={deleteProcess.isPending}
            />
            <p className="text-[10px] text-muted-foreground">
              Expected: <span className="font-mono">{router.name}</span>
            </p>
          </div>
          {deleteError && (
            <InlineAlert tone="error" title="Delete failed">
              {deleteError}
            </InlineAlert>
          )}
          {deleteProcess.isPending && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Spinner /> Deleting the OSPF process…
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteProcess.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={confirmText !== router.name || deleteProcess.isPending}
              onClick={() => void handleDelete()}
            >
              <Trash2 className="size-4" /> Delete permanently
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
