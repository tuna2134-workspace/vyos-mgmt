"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, Plus, Route, Save, Trash2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import {
  useCreateRouteMap,
  useDeleteRouteMap,
  useUpdateRouteMap,
} from "@/lib/queries";
import type { RouteMap } from "@/lib/types";
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
import { Textarea } from "@/components/ui/textarea";
import { InlineAlert, Spinner } from "@/components/states";

export const ROUTE_MAP_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

const createSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Name is required")
    .max(64, "Name must be 64 characters or fewer")
    .refine(
      (value) => ROUTE_MAP_NAME_PATTERN.test(value),
      "Start with a letter or digit; then letters, digits, dots, underscores or hyphens",
    ),
  description: z
    .string()
    .max(255, "Description must be 255 characters or fewer")
    .optional(),
});

type CreateValues = z.infer<typeof createSchema>;

const editSchema = z.object({
  description: z
    .string()
    .max(255, "Description must be 255 characters or fewer")
    .optional(),
});

type EditValues = z.infer<typeof editSchema>;

export function RouteMapCreateDialog({
  open,
  onOpenChange,
  routerId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
}) {
  const [serverError, setServerError] = React.useState<string | null>(null);
  const createRouteMap = useCreateRouteMap(routerId);

  const form = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { name: "", description: "" },
    mode: "onSubmit",
  });

  React.useEffect(() => {
    if (!open) return;
    form.reset({ name: "", description: "" });
    setServerError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, routerId]);

  const pending = createRouteMap.isPending;

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    try {
      await createRouteMap.mutateAsync({
        name: values.name.trim(),
        description: values.description?.trim() || null,
      });
      toast.success("Route map created", {
        description: `${values.name.trim()} has no rules yet. Add a rule to start matching routes.`,
      });
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError && error.code === "route_map_exists") {
        form.setError("name", {
          type: "server",
          message: "A route map with this name already exists",
        });
        return;
      }
      const applied = applyServerFormErrors(error, form.setError, [
        "name",
        "description",
      ]);
      if (!applied) {
        setServerError(
          error instanceof Error
            ? error.message
            : "Could not create the route map.",
        );
      }
    }
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Route className="size-4 text-primary" />
            New route map
          </DialogTitle>
          <DialogDescription>
            Create a named policy. Rules are added afterwards and can be
            referenced by BGP import/export policy.
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not create route map">
            {serverError}
          </InlineAlert>
        )}

        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="BGP-IN"
                      className="font-mono"
                      autoCapitalize="none"
                      spellCheck={false}
                      autoFocus
                      disabled={pending}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Letters, digits, dots, underscores and hyphens; up to 64
                    characters. Names are case-sensitive on the device.
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
                    <Textarea
                      placeholder="Inbound filtering for transit"
                      rows={2}
                      className="resize-none text-sm"
                      disabled={pending}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Optional. Shown in the route-map list and BGP policy
                    selectors.
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
                    <Loader2 className="size-4 animate-spin" /> Creating…
                  </>
                ) : (
                  <>
                    <Plus className="size-4" /> Create route map
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

export function RouteMapEditDialog({
  open,
  onOpenChange,
  routerId,
  routeMap,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  routeMap: RouteMap | null;
}) {
  const [serverError, setServerError] = React.useState<string | null>(null);
  const updateRouteMap = useUpdateRouteMap(routerId);

  const form = useForm<EditValues>({
    resolver: zodResolver(editSchema),
    defaultValues: { description: "" },
    mode: "onSubmit",
  });

  React.useEffect(() => {
    if (!open) return;
    form.reset({ description: routeMap?.description ?? "" });
    setServerError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, routeMap?.name, routerId]);

  const pending = updateRouteMap.isPending;

  const onSubmit = form.handleSubmit(async (values) => {
    if (!routeMap) return;
    setServerError(null);
    try {
      await updateRouteMap.mutateAsync({
        name: routeMap.name,
        payload: { description: values.description?.trim() || null },
      });
      toast.success("Description updated", {
        description: `${routeMap.name} saved.`,
      });
      onOpenChange(false);
    } catch (error) {
      const applied = applyServerFormErrors(error, form.setError, [
        "description",
      ]);
      if (!applied) {
        setServerError(
          error instanceof Error
            ? error.message
            : "Could not update the route map.",
        );
      }
    }
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Route className="size-4 text-primary" />
            Edit route map
          </DialogTitle>
          <DialogDescription>
            Update the description for{" "}
            <span className="font-mono text-foreground">{routeMap?.name}</span>.
            Only the description is editable; rules are managed separately.
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not update route map">
            {serverError}
          </InlineAlert>
        )}

        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Inbound filtering for transit"
                      rows={3}
                      className="resize-none text-sm"
                      disabled={pending}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Leave empty to clear the description.
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
                    <Save className="size-4" /> Save description
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

function usedByFromError(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [];
  const details = error.details;
  if (!details || Array.isArray(details)) return [];
  const raw = (details as Record<string, unknown>).used_by;
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is string => typeof item === "string");
}

export function RouteMapDeleteDialog({
  open,
  onOpenChange,
  routerId,
  routeMap,
  onDeleted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  routeMap: RouteMap | null;
  onDeleted?: (name: string) => void;
}) {
  const [usedBy, setUsedBy] = React.useState<string[]>([]);
  const [serverError, setServerError] = React.useState<string | null>(null);
  const deleteRouteMap = useDeleteRouteMap(routerId);

  React.useEffect(() => {
    if (!open) return;
    setUsedBy([]);
    setServerError(null);
  }, [open, routeMap?.name]);

  const handleDelete = async () => {
    if (!routeMap) return;
    setUsedBy([]);
    setServerError(null);
    try {
      await deleteRouteMap.mutateAsync(routeMap.name);
      toast.success("Route map deleted", {
        description: `${routeMap.name} was removed from the router configuration.`,
      });
      onDeleted?.(routeMap.name);
      onOpenChange(false);
    } catch (error) {
      const references = usedByFromError(error);
      if (references.length > 0) {
        setUsedBy(references);
        toast.error("Route map is in use", {
          description: `${routeMap.name} is referenced ${references.length} time${references.length === 1 ? "" : "s"}. Detach it from BGP policy first.`,
        });
        return;
      }
      const message =
        error instanceof Error
          ? error.message
          : "Could not delete the route map.";
      setServerError(message);
      toast.error("Could not delete route map", { description: message });
    }
  };

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !deleteRouteMap.isPending) onOpenChange(false);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <Trash2 className="size-4 text-destructive" />
            Delete route map {routeMap?.name}?
          </AlertDialogTitle>
          <AlertDialogDescription>
            The route map and all of its rules will be removed from the router.
            This cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>

        {routeMap?.in_use && (
          <InlineAlert tone="warning" title="Referenced by BGP policy">
            This route map is currently referenced. Deletion will be refused
            until the reference is removed.
            {routeMap.used_by.length > 0 && (
              <ul className="mt-2 space-y-1 font-mono text-[11px]">
                {routeMap.used_by.map((reference) => (
                  <li key={reference} className="break-all">
                    {reference}
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
                  The API reports this route map is still referenced. Remove
                  these references and try again:
                </p>
                <ul className="mt-2 space-y-1 font-mono text-[11px]">
                  {usedBy.map((reference) => (
                    <li key={reference} className="break-all">
                      {reference}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              serverError
            )}
          </InlineAlert>
        )}

        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <Badge variant="muted" className="font-mono text-[9px]">
            {routeMap?.rules.length ?? 0} rules
          </Badge>
          <span>
            Rules are deleted with the route map. BGP sessions using it as
            import/export policy will fail validation until reconfigured.
          </span>
        </div>

        {deleteRouteMap.isPending && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Spinner /> Deleting route map…
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={deleteRouteMap.isPending}>
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            disabled={deleteRouteMap.isPending}
            onClick={(event) => {
              event.preventDefault();
              void handleDelete();
            }}
          >
            <Trash2 className="size-4" /> Delete route map
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
