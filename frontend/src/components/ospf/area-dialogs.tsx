"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, Map, Plus, Save, Trash2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import {
  useCreateOspfArea,
  useDeleteOspfArea,
  useUpdateOspfArea,
} from "@/lib/queries";
import type { OspfArea, OspfAreaType, OspfVersion } from "@/lib/types";
import {
  AREA_TYPE_LABEL,
  VERSION_VYOS_PATH,
  normalizeAreaId,
} from "@/components/ospf/shared";
import { Badge } from "@/components/ui/badge";
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
import { Switch } from "@/components/ui/switch";
import { InlineAlert, Spinner } from "@/components/states";

const AREA_TYPES: OspfAreaType[] = ["normal", "stub", "nssa"];

const AREA_TYPE_DESCRIPTION: Record<OspfAreaType, string> = {
  normal: "Standard area with full LSDB and summaries.",
  stub: "Blocks external LSAs; a default route is injected instead.",
  nssa: "Stub area that can import external routes as type-7 LSAs.",
};

function makeAreaSchema(isCreate: boolean) {
  return z
    .object({
      area_id: z.string(),
      area_type: z.enum(["normal", "stub", "nssa"]),
      no_summary: z.boolean(),
    })
    .superRefine((values, ctx) => {
      if (!isCreate) return;
      if (!values.area_id.trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["area_id"],
          message: "Area ID is required",
        });
        return;
      }
      if (normalizeAreaId(values.area_id) === null) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["area_id"],
          message:
            "Enter a decimal area number (0–4294967295) or dotted notation (0.0.0.1)",
        });
      }
    });
}

type AreaFormValues = z.infer<ReturnType<typeof makeAreaSchema>>;

/* -------------------------------------------------------------------------- */
/* Create / edit                                                              */
/* -------------------------------------------------------------------------- */

export function OspfAreaFormDialog({
  open,
  onOpenChange,
  routerId,
  version,
  area,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  version: OspfVersion;
  /** `null` creates a new area; otherwise edits type/`no_summary` only. */
  area: OspfArea | null;
}) {
  const isCreate = area === null;
  const [serverError, setServerError] = React.useState<string | null>(null);
  const createArea = useCreateOspfArea(routerId, version);
  const updateArea = useUpdateOspfArea(routerId, version);
  const pending = createArea.isPending || updateArea.isPending;

  const schema = React.useMemo(() => makeAreaSchema(isCreate), [isCreate]);
  const form = useForm<AreaFormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      area_id: "",
      area_type: "normal",
      no_summary: false,
    },
    mode: "onSubmit",
  });

  React.useEffect(() => {
    if (!open) return;
    form.reset({
      area_id: area?.area_id ?? "",
      area_type: area?.area_type ?? "normal",
      no_summary: area?.no_summary ?? false,
    });
    setServerError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, area?.area_id, routerId, version]);

  const areaType = form.watch("area_type");
  const supportsNoSummary = areaType === "stub" || areaType === "nssa";

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const payload = {
      area_type: values.area_type,
      no_summary: supportsNoSummary && values.no_summary,
    };

    try {
      if (isCreate) {
        const areaId = normalizeAreaId(values.area_id);
        if (!areaId) return;
        await createArea.mutateAsync({ area_id: areaId, ...payload });
        toast.success("OSPF area created", {
          description: `Area ${areaId} (${AREA_TYPE_LABEL[values.area_type]}) saved on the router.`,
        });
      } else {
        await updateArea.mutateAsync({ areaId: area.area_id, payload });
        toast.success("OSPF area updated", {
          description: `${area.area_id} is now ${AREA_TYPE_LABEL[values.area_type]}.`,
        });
      }
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError && error.code === "ospf_area_exists") {
        form.setError("area_id", {
          type: "server",
          message: "This area already exists",
        });
        return;
      }
      const applied = applyServerFormErrors(error, form.setError, [
        "area_id",
        "area_type",
        "no_summary",
      ]);
      if (!applied) {
        setServerError(
          error instanceof Error
            ? error.message
            : "Could not save the OSPF area.",
        );
      }
    }
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Map className="size-4 text-primary" />
            {isCreate ? "New OSPF area" : `Edit area ${area?.area_id}`}
          </DialogTitle>
          <DialogDescription>
            Areas are stored under{" "}
            <code className="font-mono text-[11px]">
              {VERSION_VYOS_PATH[version]}
            </code>
            . Interfaces activate OSPF and must reference an existing area.
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not save area">
            {serverError}
          </InlineAlert>
        )}

        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <FormField
              control={form.control}
              name="area_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Area ID</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="0.0.0.1"
                      className="font-mono"
                      autoCapitalize="none"
                      autoCorrect="off"
                      spellCheck={false}
                      autoFocus={isCreate}
                      disabled={pending || !isCreate}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    {isCreate
                      ? "Decimal (1) or dotted (0.0.0.1) notation. The API returns canonical dotted decimal; the ID cannot be changed later."
                      : "Area IDs are immutable; delete the area and recreate it to change the ID."}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="area_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Area type</FormLabel>
                  <Select
                    value={field.value}
                    onValueChange={(next) => {
                      field.onChange(next);
                      if (next === "normal") {
                        form.setValue("no_summary", false);
                      }
                    }}
                    disabled={pending}
                  >
                    <FormControl>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {AREA_TYPES.map((value) => (
                        <SelectItem key={value} value={value}>
                          {AREA_TYPE_LABEL[value]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    {AREA_TYPE_DESCRIPTION[areaType]}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="no_summary"
              render={({ field }) => (
                <FormItem className="flex flex-row items-center justify-between rounded-lg border border-border/70 px-3.5 py-3">
                  <div className="space-y-0.5">
                    <FormLabel className="text-[13px]">
                      Suppress summary LSAs
                    </FormLabel>
                    <p className="text-[10px] leading-relaxed text-muted-foreground">
                      Totally-stub / totally-NSSA. Only available for stub and
                      NSSA areas.
                    </p>
                  </div>
                  <FormControl>
                    <Switch
                      checked={supportsNoSummary && field.value}
                      onCheckedChange={field.onChange}
                      disabled={pending || !supportsNoSummary}
                      aria-label="Suppress summary LSAs (no-summary)"
                    />
                  </FormControl>
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
                ) : isCreate ? (
                  <>
                    <Plus className="size-4" /> Create area
                  </>
                ) : (
                  <>
                    <Save className="size-4" /> Save area
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
/* Delete                                                                     */
/* -------------------------------------------------------------------------- */

function usedByFromError(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [];
  const details = error.details;
  if (!details || Array.isArray(details)) return [];
  const raw = (details as Record<string, unknown>).used_by;
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is string => typeof item === "string");
}

export function OspfAreaDeleteDialog({
  open,
  onOpenChange,
  routerId,
  version,
  area,
  usedByInterfaces,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  version: OspfVersion;
  area: OspfArea | null;
  /** Interfaces currently referencing this area, from the config payload. */
  usedByInterfaces: string[];
}) {
  const [usedBy, setUsedBy] = React.useState<string[]>([]);
  const [serverError, setServerError] = React.useState<string | null>(null);
  const deleteArea = useDeleteOspfArea(routerId, version);

  React.useEffect(() => {
    if (!open) return;
    setUsedBy([]);
    setServerError(null);
  }, [open, area?.area_id]);

  const blocked = (area?.interface_count ?? 0) > 0;
  const references = usedBy.length > 0 ? usedBy : usedByInterfaces;

  const handleDelete = async () => {
    if (!area) return;
    setUsedBy([]);
    setServerError(null);
    try {
      await deleteArea.mutateAsync(area.area_id);
      toast.success("OSPF area deleted", {
        description: `Area ${area.area_id} was removed from ${VERSION_VYOS_PATH[version]}.`,
      });
      onOpenChange(false);
    } catch (error) {
      const inUse = usedByFromError(error);
      if (inUse.length > 0) {
        setUsedBy(inUse);
        toast.error("Area is in use", {
          description: `${area.area_id} is referenced by ${inUse.length} interface${inUse.length === 1 ? "" : "s"}. Remove those interfaces first.`,
        });
        return;
      }
      const message =
        error instanceof Error
          ? error.message
          : "Could not delete the OSPF area.";
      setServerError(message);
      toast.error("Could not delete area", { description: message });
    }
  };

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !deleteArea.isPending) onOpenChange(false);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <Trash2 className="size-4 text-destructive" />
            Delete area {area?.area_id}?
          </AlertDialogTitle>
          <AlertDialogDescription>
            The area is removed from{" "}
            <code className="font-mono text-[11px]">
              {VERSION_VYOS_PATH[version]}
            </code>
            . Interfaces in the area lose their OSPF activation, so the API
            refuses deletion while any interface still references it.
          </AlertDialogDescription>
        </AlertDialogHeader>

        {area && (
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <Badge variant="outline" className="font-mono text-[9px]">
              {AREA_TYPE_LABEL[area.area_type]}
            </Badge>
            {area.no_summary && (
              <Badge variant="secondary" className="font-mono text-[9px]">
                no-summary
              </Badge>
            )}
            <span>
              {area.interface_count} interface
              {area.interface_count === 1 ? "" : "s"}
            </span>
          </div>
        )}

        {blocked && (
          <InlineAlert tone="warning" title="Area is in use">
            Remove or move these interfaces before deleting the area:
            {references.length > 0 && (
              <ul className="mt-2 space-y-1 font-mono text-[11px]">
                {references.map((name) => (
                  <li key={name} className="break-all">
                    {name}
                  </li>
                ))}
              </ul>
            )}
          </InlineAlert>
        )}

        {(usedBy.length > 0 || serverError) && (
          <InlineAlert tone="error" title="Delete refused">
            {usedBy.length > 0 ? (
              <>
                <p>
                  The API reports this area is still referenced by:
                </p>
                <ul className="mt-2 space-y-1 font-mono text-[11px]">
                  {usedBy.map((name) => (
                    <li key={name} className="break-all">
                      {name}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              serverError
            )}
          </InlineAlert>
        )}

        {deleteArea.isPending && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Spinner /> Deleting area…
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={deleteArea.isPending}>
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            disabled={deleteArea.isPending || blocked}
            onClick={(event) => {
              event.preventDefault();
              void handleDelete();
            }}
          >
            <Trash2 className="size-4" /> Delete area
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
