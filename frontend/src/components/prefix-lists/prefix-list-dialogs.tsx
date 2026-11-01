"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { ListFilter, Loader2, Plus, Save, Trash2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import {
  useCreatePrefixList,
  useDeletePrefixList,
  useUpdatePrefixList,
} from "@/lib/queries";
import type { PrefixList, PrefixListFamily } from "@/lib/types";
import {
  FAMILY_LABEL,
  FAMILY_PLACEHOLDER,
  FAMILY_VYOS_PATH,
  PREFIX_LIST_NAME_PATTERN,
  PrefixListFamilyBadge,
} from "@/components/prefix-lists/shared";
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
import { Textarea } from "@/components/ui/textarea";
import { InlineAlert, Spinner } from "@/components/states";

const createSchema = z.object({
  family: z.enum(["ipv4", "ipv6"]),
  name: z
    .string()
    .trim()
    .min(1, "Name is required")
    .max(128, "Name must be 128 characters or fewer")
    .refine(
      (value) => PREFIX_LIST_NAME_PATTERN.test(value),
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

/* -------------------------------------------------------------------------- */
/* Create                                                                      */
/* -------------------------------------------------------------------------- */

export function PrefixListCreateDialog({
  open,
  onOpenChange,
  routerId,
  family,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  /** Preselected from the active IPv4/IPv6 tab; still changeable in the form. */
  family: PrefixListFamily;
  onCreated?: (prefixList: PrefixList) => void;
}) {
  const [serverError, setServerError] = React.useState<string | null>(null);
  const createPrefixList = useCreatePrefixList(routerId);

  const form = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { family, name: "", description: "" },
    mode: "onSubmit",
  });

  React.useEffect(() => {
    if (!open) return;
    form.reset({ family, name: "", description: "" });
    setServerError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, routerId, family]);

  const pending = createPrefixList.isPending;
  const selectedFamily = form.watch("family");

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const name = values.name.trim();
    try {
      const created = await createPrefixList.mutateAsync({
        name,
        family: values.family,
        description: values.description?.trim() || null,
      });
      onCreated?.(created);
      toast.success("Prefix list created", {
        description: `${name} (${FAMILY_LABEL[values.family]}) has no rules yet. Add a rule to start matching prefixes.`,
      });
      onOpenChange(false);
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.code === "prefix_list_exists"
      ) {
        form.setError("name", {
          type: "server",
          message: `A ${FAMILY_LABEL[values.family]} prefix list with this name already exists`,
        });
        return;
      }
      const applied = applyServerFormErrors(error, form.setError, [
        "name",
        "family",
        "description",
      ]);
      if (!applied) {
        setServerError(
          error instanceof Error
            ? error.message
            : "Could not create the prefix list.",
        );
      }
    }
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ListFilter className="size-4 text-primary" />
            New prefix list
          </DialogTitle>
          <DialogDescription>
            Create a named list under{" "}
            <code className="font-mono text-[11px]">policy prefix-list</code>{" "}
            (IPv4) or{" "}
            <code className="font-mono text-[11px]">policy prefix-list6</code>{" "}
            (IPv6). Rules are added afterwards.
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not create prefix list">
            {serverError}
          </InlineAlert>
        )}

        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <FormField
              control={form.control}
              name="family"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Address family</FormLabel>
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
                      <SelectItem value="ipv4">IPv4 · policy prefix-list</SelectItem>
                      <SelectItem value="ipv6">
                        IPv6 · policy prefix-list6
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    IPv4 and IPv6 names are independent: the same name may exist
                    in both families.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input
                      placeholder={FAMILY_PLACEHOLDER[selectedFamily].name}
                      className="font-mono"
                      autoCapitalize="none"
                      spellCheck={false}
                      autoFocus
                      disabled={pending}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Letters, digits, dots, underscores and hyphens; up to 128
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
                      placeholder="Transit customer prefixes"
                      rows={2}
                      className="resize-none text-sm"
                      disabled={pending}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Optional. Shown in the prefix-list list and route-map
                    reference hints.
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
                    <Plus className="size-4" /> Create prefix list
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
/* Edit description                                                            */
/* -------------------------------------------------------------------------- */

export function PrefixListEditDialog({
  open,
  onOpenChange,
  routerId,
  prefixList,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  prefixList: PrefixList | null;
}) {
  const [serverError, setServerError] = React.useState<string | null>(null);
  const updatePrefixList = useUpdatePrefixList(routerId);

  const form = useForm<EditValues>({
    resolver: zodResolver(editSchema),
    defaultValues: { description: "" },
    mode: "onSubmit",
  });

  React.useEffect(() => {
    if (!open) return;
    form.reset({ description: prefixList?.description ?? "" });
    setServerError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, prefixList?.family, prefixList?.name, routerId]);

  const pending = updatePrefixList.isPending;

  const onSubmit = form.handleSubmit(async (values) => {
    if (!prefixList) return;
    setServerError(null);
    try {
      await updatePrefixList.mutateAsync({
        family: prefixList.family,
        name: prefixList.name,
        payload: { description: values.description?.trim() || null },
      });
      toast.success("Description updated", {
        description: `${prefixList.name} saved on the router.`,
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
            : "Could not update the prefix list.",
        );
      }
    }
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ListFilter className="size-4 text-primary" />
            Edit prefix list
          </DialogTitle>
          <DialogDescription>
            Update the description for{" "}
            <span className="font-mono text-foreground">{prefixList?.name}</span>{" "}
            ({prefixList ? FAMILY_LABEL[prefixList.family] : "—"}). Only the
            description is editable; rules are managed separately.
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not update prefix list">
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
                      placeholder="Transit customer prefixes"
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

/* -------------------------------------------------------------------------- */
/* Delete                                                                      */
/* -------------------------------------------------------------------------- */

function usedByFromError(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [];
  const details = error.details;
  if (!details || Array.isArray(details)) return [];
  const raw = (details as Record<string, unknown>).used_by;
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is string => typeof item === "string");
}

export function PrefixListDeleteDialog({
  open,
  onOpenChange,
  routerId,
  prefixList,
  onDeleted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  prefixList: PrefixList | null;
  onDeleted?: (list: PrefixList) => void;
}) {
  const [usedBy, setUsedBy] = React.useState<string[]>([]);
  const [serverError, setServerError] = React.useState<string | null>(null);
  const deletePrefixList = useDeletePrefixList(routerId);

  React.useEffect(() => {
    if (!open) return;
    setUsedBy([]);
    setServerError(null);
  }, [open, prefixList?.family, prefixList?.name]);

  const handleDelete = async () => {
    if (!prefixList) return;
    setUsedBy([]);
    setServerError(null);
    try {
      await deletePrefixList.mutateAsync({
        family: prefixList.family,
        name: prefixList.name,
      });
      toast.success("Prefix list deleted", {
        description: `${prefixList.name} was removed from ${FAMILY_VYOS_PATH[prefixList.family]}.`,
      });
      onDeleted?.(prefixList);
      onOpenChange(false);
    } catch (error) {
      const references = usedByFromError(error);
      if (references.length > 0) {
        setUsedBy(references);
        toast.error("Prefix list is in use", {
          description: `${prefixList.name} is referenced ${references.length} time${references.length === 1 ? "" : "s"}. Detach it from route-map or BGP policy first.`,
        });
        return;
      }
      const message =
        error instanceof Error
          ? error.message
          : "Could not delete the prefix list.";
      setServerError(message);
      toast.error("Could not delete prefix list", { description: message });
    }
  };

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !deletePrefixList.isPending) onOpenChange(false);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <Trash2 className="size-4 text-destructive" />
            Delete prefix list {prefixList?.name}?
          </AlertDialogTitle>
          <AlertDialogDescription>
            The {prefixList ? FAMILY_LABEL[prefixList.family] : ""} prefix list
            and all of its rules will be removed from{" "}
            <span className="font-mono">
              {prefixList ? FAMILY_VYOS_PATH[prefixList.family] : "the router"}
            </span>
            . This cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>

        {prefixList?.in_use && (
          <InlineAlert tone="warning" title="Referenced by policy">
            This prefix list is currently referenced. Deletion will be refused
            until the references are removed.
            {prefixList.used_by.length > 0 && (
              <ul className="mt-2 space-y-1 font-mono text-[11px]">
                {prefixList.used_by.map((reference) => (
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
                  The API reports this prefix list is still referenced. Remove
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
          {prefixList && (
            <>
              <PrefixListFamilyBadge family={prefixList.family} />
              <Badge variant="muted" className="font-mono text-[9px]">
                {prefixList.rules.length} rules
              </Badge>
            </>
          )}
          <span>
            Rules are deleted with the list. Route-map matches referencing this
            name will fail validation until reconfigured.
          </span>
        </div>

        {deletePrefixList.isPending && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Spinner /> Deleting prefix list…
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={deletePrefixList.isPending}>
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            disabled={deletePrefixList.isPending}
            onClick={(event) => {
              event.preventDefault();
              void handleDelete();
            }}
          >
            <Trash2 className="size-4" /> Delete prefix list
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
