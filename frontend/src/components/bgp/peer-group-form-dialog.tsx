"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Save,
  Tags,
} from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import {
  useCreatePeerGroup,
  useRouteMaps,
  useUpdatePeerGroup,
} from "@/lib/queries";
import { isValidAsn } from "@/lib/validation";
import type {
  AddressFamilies,
  BgpPeerGroup,
  BgpPeerGroupCreate,
  BgpPeerGroupUpdate,
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

const peerGroupSchema = z
  .object({
    name: z
      .string()
      .trim()
      .min(1, "Name is required")
      .max(64, "Name must be 64 characters or fewer")
      .refine(
        (value) => /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/.test(value),
        "Use letters, digits, dots, underscores or hyphens",
      ),
    remote_as: z
      .string()
      .trim()
      .min(1, "Remote AS is required")
      .refine(isValidAsn, "Remote AS must be an integer from 1 to 4294967295"),
    description: z
      .string()
      .max(255, "Description must be 255 characters or fewer")
      .optional(),
    update_source: z.string().max(64, "Update source is too long").optional(),
    ebgp_multihop: optionalPort(1, 255),
    password: z.string().max(128, "Password is too long").optional(),
    remove_password: z.boolean(),
    address_families: z.custom<AddressFamilies>(
      (value) => !!value && typeof value === "object",
      "Invalid address families",
    ),
  })
  .superRefine((values, ctx) => {
    if (Object.keys(values.address_families ?? {}).length === 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["address_families"],
        message: "Activate at least one address family",
      });
    }
  });

type PeerGroupFormValues = z.infer<typeof peerGroupSchema>;

function defaultsFor(group: BgpPeerGroup | null): PeerGroupFormValues {
  return {
    name: group?.name ?? "",
    remote_as: group?.remote_as != null ? String(group.remote_as) : "",
    description: group?.description ?? "",
    update_source: group?.update_source ?? "",
    ebgp_multihop:
      group?.ebgp_multihop != null ? String(group.ebgp_multihop) : "",
    password: "",
    remove_password: false,
    address_families: group
      ? withAfDefaults(group.address_families)
      : { "ipv4-unicast": makeAfSettings() },
  };
}

export function PeerGroupFormDialog({
  open,
  onOpenChange,
  routerId,
  group,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  group: BgpPeerGroup | null;
}) {
  const isEdit = !!group;
  const [serverError, setServerError] = React.useState<string | null>(null);
  const [showPassword, setShowPassword] = React.useState(false);
  const createGroup = useCreatePeerGroup(routerId);
  const updateGroup = useUpdatePeerGroup(routerId);
  const routeMapsQuery = useRouteMaps(routerId);
  const routeMapNames = React.useMemo(
    () => (routeMapsQuery.data?.items ?? []).map((routeMap) => routeMap.name),
    [routeMapsQuery.data],
  );
  const pending = createGroup.isPending || updateGroup.isPending;

  const form = useForm<PeerGroupFormValues>({
    resolver: zodResolver(peerGroupSchema),
    defaultValues: defaultsFor(group),
    mode: "onSubmit",
  });

  React.useEffect(() => {
    if (!open) return;
    form.reset(defaultsFor(group));
    setServerError(null);
    setShowPassword(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, group?.name, routerId]);

  const families = form.watch("address_families");
  const removePassword = form.watch("remove_password");

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const base = {
      remote_as: Number(values.remote_as),
      description: values.description?.trim() ? values.description.trim() : null,
      update_source: values.update_source?.trim()
        ? values.update_source.trim()
        : null,
      ebgp_multihop: values.ebgp_multihop?.trim()
        ? Number(values.ebgp_multihop)
        : null,
      address_families: values.address_families,
    };

    try {
      if (isEdit && group) {
        const payload: BgpPeerGroupUpdate = { ...base };
        if (values.remove_password) {
          payload.password = "";
        } else if (values.password?.trim()) {
          payload.password = values.password;
        }
        await updateGroup.mutateAsync({ name: group.name, payload });
        toast.success("Peer group updated", {
          description: `${group.name} saved.`,
        });
      } else {
        const payload: BgpPeerGroupCreate = {
          name: values.name.trim(),
          ...base,
          password: values.password?.trim() ? values.password : undefined,
        };
        await createGroup.mutateAsync(payload);
        toast.success("Peer group created", {
          description: `${payload.name} can now be referenced by neighbors.`,
        });
      }
      onOpenChange(false);
    } catch (error) {
      const applied = applyServerFormErrors(error, form.setError, [
        "name",
        "remote_as",
        "description",
        "update_source",
        "ebgp_multihop",
        "password",
        "address_families",
      ]);
      if (!applied) {
        setServerError(
          error instanceof ApiError
            ? error.message
            : "Could not save the peer group. Review the fields and try again.",
        );
      }
    }
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Tags className="size-4 text-primary" />
            {isEdit ? `Edit peer group ${group?.name}` : "Create peer group"}
          </DialogTitle>
          <DialogDescription>
            Peer groups share session parameters and address-family policy
            across multiple neighbors.
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not save peer group">
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
                    <FormLabel>Group name</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="transit"
                        className="font-mono"
                        disabled={isEdit || pending}
                        {...field}
                      />
                    </FormControl>
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
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Description</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="Transit peers"
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
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="ebgp_multihop"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>eBGP multihop</FormLabel>
                    <FormControl>
                      <Input
                        inputMode="numeric"
                        placeholder="Optional TTL"
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
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <div className="flex items-center justify-between gap-2">
                      <FormLabel className="gap-2">
                        Password
                        {isEdit && group?.password_configured && (
                          <Badge variant="success" className="gap-1 text-[9px]">
                            <KeyRound className="size-2.5" /> configured
                          </Badge>
                        )}
                      </FormLabel>
                      <span className="text-[10px] text-muted-foreground">
                        write-only
                      </span>
                    </div>
                    <FormControl>
                      <div className="relative">
                        <Input
                          type={showPassword ? "text" : "password"}
                          placeholder={
                            isEdit && group?.password_configured
                              ? "Leave blank to keep"
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
            </div>

            {isEdit && group?.password_configured && (
              <div className="flex items-start justify-between gap-3 rounded-lg border border-destructive/20 bg-destructive/[0.03] px-3 py-2.5">
                <div>
                  <p className="text-[13px] font-medium">
                    Remove configured password
                  </p>
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    Clears the stored password on save.
                  </p>
                </div>
                <Switch
                  checked={removePassword}
                  onCheckedChange={(checked) =>
                    form.setValue("remove_password", checked)
                  }
                  disabled={pending}
                  aria-label="Remove configured password"
                />
              </div>
            )}

            <div className="space-y-2">
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
                        namePrefix="peer-group"
                        routeMaps={routeMapNames}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormDescription className="text-[10px]">
              Neighbors referencing this group inherit its remote AS and family
              settings. Changing the group can affect multiple sessions.
            </FormDescription>

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
                    {isEdit ? "Save peer group" : "Create peer group"}
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
