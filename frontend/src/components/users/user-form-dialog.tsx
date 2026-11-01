"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Save, UserRound } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import { useCreateUser, useUpdateUser, queryKeys } from "@/lib/queries";
import type { User, UserCreate, UserUpdate } from "@/lib/types";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { InlineAlert } from "@/components/states";

const emailSchema = z
  .string()
  .optional()
  .refine(
    (value) => !value || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value),
    "Enter a valid email address",
  );

function buildSchema(isEdit: boolean, isSelf: boolean) {
  return z
    .object({
      username: z
        .string()
        .trim()
        .min(3, "Username must be at least 3 characters")
        .max(64, "Username must be 64 characters or fewer")
        .refine(
          (value) => /^[a-z0-9._-]+$/.test(value),
          "Use lowercase letters, digits, dots, underscores or hyphens",
        ),
      email: emailSchema,
      password: z.string().optional(),
      role: z.enum(["admin", "operator", "viewer"]),
      is_active: z.boolean(),
    })
    .superRefine((values, ctx) => {
      const password = values.password ?? "";
      if (!isEdit && password.length < 12) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["password"],
          message: "Password must be at least 12 characters",
        });
      }
      if (isEdit && password.length > 0 && password.length < 12) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["password"],
          message: "New password must be at least 12 characters",
        });
      }
      if (isSelf && isEdit && values.role !== "admin") {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["role"],
          message: "You cannot change your own role",
        });
      }
      if (isSelf && isEdit && !values.is_active) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["is_active"],
          message: "You cannot deactivate your own account",
        });
      }
    });
}

type UserFormValues = z.infer<ReturnType<typeof buildSchema>>;

function defaultsFor(user: User | null): UserFormValues {
  return {
    username: user?.username ?? "",
    email: user?.email ?? "",
    password: "",
    role: user?.role ?? "operator",
    is_active: user?.is_active ?? true,
  };
}

export function UserFormDialog({
  open,
  onOpenChange,
  target,
  currentUserId,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  target: User | null;
  currentUserId: string;
  onSaved?: (user: User) => void;
}) {
  const isEdit = !!target;
  const isSelf = !!target && target.id === currentUserId;
  const queryClient = useQueryClient();
  const createUser = useCreateUser();
  const updateUser = useUpdateUser();
  const pending = createUser.isPending || updateUser.isPending;
  const [serverError, setServerError] = React.useState<string | null>(null);

  const schema = React.useMemo(
    () => buildSchema(isEdit, isSelf),
    [isEdit, isSelf],
  );

  const form = useForm<UserFormValues>({
    resolver: zodResolver(schema),
    defaultValues: defaultsFor(target),
    mode: "onSubmit",
  });

  React.useEffect(() => {
    if (!open) return;
    form.reset(defaultsFor(target));
    setServerError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, target?.id]);

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const email = values.email?.trim() ? values.email.trim() : null;
    try {
      if (isEdit && target) {
        const payload: UserUpdate = {
          email,
          role: values.role,
          is_active: values.is_active,
        };
        if (values.password?.trim()) payload.password = values.password;
        // The backend blocks self-demotion/deactivation regardless; keep UI
        // noise down by not sending unchanged self fields.
        if (isSelf) {
          delete payload.role;
          delete payload.is_active;
        }
        const updated = await updateUser.mutateAsync({
          userId: target.id,
          payload,
        });
        toast.success("User updated", {
          description: `${updated.username} saved${payload.password ? "; password reset" : ""}.`,
        });
        onSaved?.(updated);
      } else {
        const payload: UserCreate = {
          username: values.username.trim(),
          email,
          password: values.password ?? "",
          role: values.role,
        };
        const created = await createUser.mutateAsync(payload);
        toast.success("User created", {
          description: `${created.username} can now sign in with the assigned role.`,
        });
        onSaved?.(created);
      }
      await queryClient.invalidateQueries({ queryKey: queryKeys.users });
      onOpenChange(false);
    } catch (error) {
      const applied = applyServerFormErrors(error, form.setError, [
        "username",
        "email",
        "password",
        "role",
        "is_active",
      ]);
      if (!applied) {
        setServerError(
          error instanceof ApiError
            ? error.message
            : "Could not save the user. Check the fields and try again.",
        );
      }
    }
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserRound className="size-4 text-primary" />
            {isEdit ? `Edit ${target?.username}` : "Create user"}
          </DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update role, status or reset the password. Changes are audited."
              : "Create a console account. Usernames are lowercase and cannot be changed later."}
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not save user">
            {serverError}
          </InlineAlert>
        )}

        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="username"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Username</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="noc"
                        className="font-mono"
                        autoComplete="off"
                        autoCapitalize="none"
                        spellCheck={false}
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
                name="role"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Role</FormLabel>
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                      disabled={pending || (isSelf && isEdit)}
                    >
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="viewer">Viewer</SelectItem>
                        <SelectItem value="operator">Operator</SelectItem>
                        <SelectItem value="admin">Administrator</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input
                      type="email"
                      placeholder="noc@example.com"
                      autoComplete="off"
                      disabled={pending}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>Optional. Used for contact only.</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    {isEdit ? "Reset password" : "Password"}
                  </FormLabel>
                  <FormControl>
                    <Input
                      type="password"
                      autoComplete="new-password"
                      placeholder={isEdit ? "Leave blank to keep current" : "At least 12 characters"}
                      disabled={pending}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    {isEdit
                      ? "Setting a new password revokes that user's refresh tokens."
                      : "Minimum 12 characters. Share it through a secure channel."}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {isEdit && (
              <FormField
                control={form.control}
                name="is_active"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center justify-between rounded-lg border border-border/70 px-4 py-3">
                    <div className="space-y-0.5">
                      <FormLabel className="text-[13px]">Account active</FormLabel>
                      <p className="text-[11px] text-muted-foreground">
                        Inactive users cannot sign in; their sessions are not
                        renewed.
                      </p>
                    </div>
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                        disabled={pending || isSelf}
                        aria-label="Account active"
                      />
                    </FormControl>
                  </FormItem>
                )}
              />
            )}

            {isSelf && (
              <InlineAlert tone="info" className="text-[11px]">
                You cannot change your own role, deactivate yourself, or delete
                your own account.
              </InlineAlert>
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
                    {isEdit ? "Save user" : "Create user"}
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
