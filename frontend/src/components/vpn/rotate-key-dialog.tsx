"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { KeyRound, Loader2, RefreshCw, ShieldAlert } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError, errorMessage } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import {
  useGenerateWireGuardKeypair,
  useRotateWireGuardPrivateKey,
} from "@/lib/queries";
import type { WireGuardInterfaceDetail, WireGuardKeypair } from "@/lib/types";
import { isWireGuardKey } from "@/lib/validation";
import { KeyValueBlock, SecretKeyInput } from "@/components/vpn/shared";
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
  FormField,
  FormItem,
  FormMessage,
} from "@/components/ui/form";
import { InlineAlert, Spinner } from "@/components/states";

const rotateSchema = z.object({
  private_key: z.string().superRefine((value, ctx) => {
    if (!value.trim()) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "A new private key is required",
      });
    } else if (!isWireGuardKey(value)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Enter a Base64 32-byte key (44 characters ending with =)",
      });
    }
  }),
});

type RotateFormValues = z.infer<typeof rotateSchema>;

/**
 * Replace the interface private key. The private key is write-only: nothing is
 * pre-filled, and the new public key returned by key generation is the only
 * thing worth copying out — peers must be updated out of band.
 */
export function RotateKeyDialog({
  open,
  onOpenChange,
  routerId,
  iface,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  iface: WireGuardInterfaceDetail | null;
}) {
  const rotate = useRotateWireGuardPrivateKey(routerId);
  const generateKeypair = useGenerateWireGuardKeypair(routerId);
  const [serverError, setServerError] = React.useState<string | null>(null);
  const [generated, setGenerated] = React.useState<WireGuardKeypair | null>(
    null,
  );

  const form = useForm<RotateFormValues>({
    resolver: zodResolver(rotateSchema),
    defaultValues: { private_key: "" },
    mode: "onSubmit",
  });

  const privateKey = form.watch("private_key");
  const derivedPublicKey =
    generated && generated.private_key === privateKey
      ? generated.public_key
      : null;

  React.useEffect(() => {
    if (!open) return;
    form.reset({ private_key: "" });
    setServerError(null);
    setGenerated(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, iface?.name, routerId]);

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
        description: "The private key was filled in. Rotate to apply it.",
      });
    } catch (error) {
      toast.error("Could not generate a keypair", {
        description: errorMessage(error),
      });
    }
  };

  const onSubmit = form.handleSubmit(async (values) => {
    if (!iface) return;
    setServerError(null);
    try {
      await rotate.mutateAsync({
        name: iface.name,
        payload: { private_key: values.private_key.trim() },
      });
      toast.success(`${iface.name} private key rotated`, {
        description:
          "Update every peer with the interface's new public key out of band.",
      });
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError && error.code === "validation_error") {
        if (
          applyServerFormErrors(error, form.setError, ["private_key"])
        ) {
          return;
        }
      }
      setServerError(errorMessage(error));
    }
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!rotate.isPending && !generateKeypair.isPending) onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <RefreshCw className="size-4 text-primary" />
            Rotate key · {iface?.name}
          </DialogTitle>
          <DialogDescription>
            Replace the interface private key. The new key is written to the
            router; the old public key stops being valid immediately.
          </DialogDescription>
        </DialogHeader>

        <InlineAlert tone="warning" title="Peers must be updated out of band">
          Rotating the key changes the interface public key. Every remote peer
          must be configured with the new public key before the tunnel recovers;
          existing sessions drop when the change is committed.
        </InlineAlert>

        {serverError && (
          <InlineAlert tone="error" title="Could not rotate the key">
            {serverError}
          </InlineAlert>
        )}

        {iface?.public_key && (
          <KeyValueBlock
            label="Current public key"
            value={iface.public_key}
            copyLabel="Copy current public key"
            hint="Record this before rotating if a rollback may be needed."
          />
        )}

        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-3" noValidate>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <label
                htmlFor="wg-rotate-private-key"
                className="text-sm font-medium"
              >
                New private key
              </label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void handleGenerate()}
                disabled={rotate.isPending || generateKeypair.isPending}
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
                  <SecretKeyInput
                    id="wg-rotate-private-key"
                    value={field.value}
                    onChange={field.onChange}
                    onBlur={field.onBlur}
                    name={field.name}
                    inputRef={field.ref}
                    label="New private key"
                    placeholder="Base64 32-byte private key"
                    disabled={rotate.isPending}
                  />
                  <FormMessage />
                </FormItem>
              )}
            />

            {derivedPublicKey && (
              <KeyValueBlock
                label="New public key"
                value={derivedPublicKey}
                copyLabel="Copy new public key"
                hint="Configure this on every peer. It becomes active after the rotation is committed."
              />
            )}

            {rotate.isPending && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Spinner /> Rotating the key…
              </div>
            )}

            <DialogFooter className="gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={rotate.isPending}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={rotate.isPending || !iface}
              >
                {rotate.isPending ? (
                  <>
                    <Loader2 className="size-4 animate-spin" /> Rotating…
                  </>
                ) : (
                  <>
                    <ShieldAlert className="size-4" /> Rotate key
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
