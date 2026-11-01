"use client";

import * as React from "react";
import Link from "next/link";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeftRight, Loader2, Plus, Save, Trash2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import {
  useCreateOspfRedistribute,
  useDeleteOspfRedistribute,
  useUpdateOspfRedistribute,
} from "@/lib/queries";
import type {
  OspfMetricType,
  OspfRedistribute,
  OspfVersion,
} from "@/lib/types";
import {
  ROUTE_MAP_NAME_PATTERN,
  VERSION_VYOS_PATH,
  isOptionalIntegerInRange,
  optionalInteger,
  sourceLabel,
} from "@/components/ospf/shared";
import { Button } from "@/components/ui/button";
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
import { InlineAlert, Spinner } from "@/components/states";

const DEVICE_DEFAULT = "__default__";
const MAX_METRIC = 16_777_214;

function makeRedistributeSchema(isCreate: boolean) {
  return z
    .object({
      source: z.string(),
      metric: z.string(),
      metric_type: z.string(),
      route_map: z.string(),
    })
    .superRefine((values, ctx) => {
      if (isCreate && !values.source) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["source"],
          message: "Select a route source",
        });
      }
      if (!isOptionalIntegerInRange(values.metric, 1, MAX_METRIC)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["metric"],
          message: `Metric must be between 1 and ${MAX_METRIC}`,
        });
      }
      if (!["", "1", "2"].includes(values.metric_type)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["metric_type"],
          message: "Metric type must be 1 or 2",
        });
      }
      const routeMap = values.route_map.trim();
      if (routeMap && !ROUTE_MAP_NAME_PATTERN.test(routeMap)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["route_map"],
          message:
            "Start with a letter or digit; then letters, digits, dots, underscores or hyphens",
        });
      }
    });
}

type RedistributeFormValues = z.infer<
  ReturnType<typeof makeRedistributeSchema>
>;

export function OspfRedistributeFormDialog({
  open,
  onOpenChange,
  routerId,
  version,
  redistribution,
  supportedSources,
  existingSources,
  routeMapNames,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  version: OspfVersion;
  /** `null` creates a new entry; otherwise edits metric/type/route map. */
  redistribution: OspfRedistribute | null;
  supportedSources: string[];
  existingSources: string[];
  routeMapNames: string[];
}) {
  const isCreate = redistribution === null;
  const [serverError, setServerError] = React.useState<string | null>(null);
  const datalistId = React.useId();
  const createRedistribute = useCreateOspfRedistribute(routerId, version);
  const updateRedistribute = useUpdateOspfRedistribute(routerId, version);
  const pending = createRedistribute.isPending || updateRedistribute.isPending;

  const schema = React.useMemo(
    () => makeRedistributeSchema(isCreate),
    [isCreate],
  );
  const form = useForm<RedistributeFormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      source: "",
      metric: "",
      metric_type: "",
      route_map: "",
    },
    mode: "onSubmit",
  });

  React.useEffect(() => {
    if (!open) return;
    form.reset({
      source: redistribution?.source ?? "",
      metric:
        redistribution?.metric === null || redistribution?.metric === undefined
          ? ""
          : String(redistribution.metric),
      metric_type:
        redistribution?.metric_type === null ||
        redistribution?.metric_type === undefined
          ? ""
          : String(redistribution.metric_type),
      route_map: redistribution?.route_map ?? "",
    });
    setServerError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, redistribution?.source, routerId, version]);

  // Creating: hide sources already redistributed. Editing: keep the current
  // source visible even if it is no longer advertised as supported.
  const sourceOptions = React.useMemo(() => {
    const available = supportedSources.filter(
      (source) => !existingSources.includes(source),
    );
    if (redistribution?.source && !available.includes(redistribution.source)) {
      available.unshift(redistribution.source);
    }
    return available;
  }, [supportedSources, existingSources, redistribution?.source]);

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const payload = {
      metric: optionalInteger(values.metric),
      metric_type:
        values.metric_type === ""
          ? null
          : (Number(values.metric_type) as OspfMetricType),
      route_map: values.route_map.trim() || null,
    };

    try {
      if (isCreate) {
        await createRedistribute.mutateAsync({
          source: values.source,
          ...payload,
        });
        toast.success("Redistribution added", {
          description: `${sourceLabel(values.source)} routes are now redistributed into ${version === "v2" ? "OSPFv2" : "OSPFv3"}.`,
        });
      } else {
        await updateRedistribute.mutateAsync({
          source: redistribution.source,
          payload,
        });
        toast.success("Redistribution updated", {
          description: `${sourceLabel(redistribution.source)} saved on the router.`,
        });
      }
      onOpenChange(false);
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.code === "ospf_redistribute_exists"
      ) {
        form.setError("source", {
          type: "server",
          message: "This source is already redistributed",
        });
        return;
      }
      if (error instanceof ApiError && error.code === "route_map_not_found") {
        form.setError("route_map", {
          type: "server",
          message: "That route map does not exist on the device",
        });
        return;
      }
      const applied = applyServerFormErrors(error, form.setError, [
        "source",
        "metric",
        "metric_type",
        "route_map",
      ]);
      if (!applied) {
        setServerError(
          error instanceof Error
            ? error.message
            : "Could not save the redistribution entry.",
        );
      }
    }
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ArrowLeftRight className="size-4 text-primary" />
            {isCreate
              ? "Redistribute routes into OSPF"
              : `Edit redistribution of ${sourceLabel(redistribution?.source ?? "")}`}
          </DialogTitle>
          <DialogDescription>
            Stored under{" "}
            <code className="font-mono text-[11px]">
              {VERSION_VYOS_PATH[version]}
            </code>{" "}
            · redistribute. The route-map reference must already exist.
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not save redistribution">
            {serverError}
          </InlineAlert>
        )}

        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <div className="grid gap-3 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="source"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Source</FormLabel>
                    {isCreate ? (
                      <Select
                        value={field.value}
                        onValueChange={field.onChange}
                        disabled={pending || sourceOptions.length === 0}
                      >
                        <FormControl>
                          <SelectTrigger className="w-full">
                            <SelectValue placeholder="Select a source" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {sourceOptions.map((source) => (
                            <SelectItem key={source} value={source}>
                              {sourceLabel(source)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <FormControl>
                        <Input
                          value={sourceLabel(field.value)}
                          className="font-mono"
                          readOnly
                          disabled
                          aria-label="Route source (immutable)"
                        />
                      </FormControl>
                    )}
                    <FormDescription>
                      {sourceOptions.length === 0 && isCreate
                        ? "Every source supported by this version is already redistributed."
                        : "Version-specific supported sources. The source is immutable after creation."}
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="metric"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Metric</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        inputMode="numeric"
                        min={1}
                        max={MAX_METRIC}
                        placeholder="Device default"
                        className="font-mono"
                        disabled={pending}
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      1–16777214; empty = device default.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="metric_type"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Metric type</FormLabel>
                    <Select
                      value={field.value || DEVICE_DEFAULT}
                      onValueChange={(next) =>
                        field.onChange(next === DEVICE_DEFAULT ? "" : next)
                      }
                      disabled={pending}
                    >
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value={DEVICE_DEFAULT}>
                          Device default
                        </SelectItem>
                        <SelectItem value="1">Type 1</SelectItem>
                        <SelectItem value="2">Type 2</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      OSPF external metric type (`type-1` / `type-2`).
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="route_map"
                render={({ field }) => (
                  <FormItem>
                    <div className="flex flex-wrap items-center justify-between gap-1.5">
                      <FormLabel>Route map</FormLabel>
                      <Link
                        href={`/route-maps/?router=${routerId}`}
                        className="text-[10px] font-medium text-primary underline-offset-2 hover:underline"
                      >
                        Manage route maps
                      </Link>
                    </div>
                    <FormControl>
                      <Input
                        list={datalistId}
                        placeholder="OSPF-OUT"
                        className="font-mono"
                        autoCapitalize="none"
                        autoCorrect="off"
                        spellCheck={false}
                        disabled={pending}
                        {...field}
                      />
                    </FormControl>
                    <datalist id={datalistId}>
                      {routeMapNames.map((name) => (
                        <option key={name} value={name} />
                      ))}
                    </datalist>
                    <FormDescription>
                      Optional. Must name an existing route map; referenced maps
                      cannot be deleted.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
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
              <Button
                type="submit"
                disabled={pending || (isCreate && sourceOptions.length === 0)}
              >
                {pending ? (
                  <>
                    <Loader2 className="size-4 animate-spin" /> Saving…
                  </>
                ) : isCreate ? (
                  <>
                    <Plus className="size-4" /> Add redistribution
                  </>
                ) : (
                  <>
                    <Save className="size-4" /> Save redistribution
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

export function OspfRedistributeDeleteDialog({
  open,
  onOpenChange,
  routerId,
  version,
  redistribution,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  version: OspfVersion;
  redistribution: OspfRedistribute | null;
}) {
  const [serverError, setServerError] = React.useState<string | null>(null);
  const deleteRedistribute = useDeleteOspfRedistribute(routerId, version);

  React.useEffect(() => {
    if (!open) return;
    setServerError(null);
  }, [open, redistribution?.source]);

  const handleDelete = async () => {
    if (!redistribution) return;
    setServerError(null);
    try {
      await deleteRedistribute.mutateAsync(redistribution.source);
      toast.success("Redistribution removed", {
        description: `${sourceLabel(redistribution.source)} is no longer redistributed.`,
      });
      onOpenChange(false);
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Could not remove the redistribution entry.";
      setServerError(message);
      toast.error("Could not remove redistribution", { description: message });
    }
  };

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !deleteRedistribute.isPending) onOpenChange(false);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <Trash2 className="size-4 text-destructive" />
            Stop redistributing {sourceLabel(redistribution?.source ?? "")}?
          </AlertDialogTitle>
          <AlertDialogDescription>
            The redistribution entry is removed from{" "}
            <code className="font-mono text-[11px]">
              {VERSION_VYOS_PATH[version]}
            </code>
            . Routes that were advertised into OSPF through it are withdrawn on
            commit.
          </AlertDialogDescription>
        </AlertDialogHeader>

        {redistribution?.route_map && (
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Route map{" "}
            <span className="font-mono">{redistribution.route_map}</span> stops
            being referenced by OSPF and may become deletable.
          </p>
        )}

        {serverError && (
          <InlineAlert tone="error" title="Delete refused">
            {serverError}
          </InlineAlert>
        )}

        {deleteRedistribute.isPending && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Spinner /> Removing redistribution…
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={deleteRedistribute.isPending}>
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            disabled={deleteRedistribute.isPending}
            onClick={(event) => {
              event.preventDefault();
              void handleDelete();
            }}
          >
            <Trash2 className="size-4" /> Remove redistribution
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
