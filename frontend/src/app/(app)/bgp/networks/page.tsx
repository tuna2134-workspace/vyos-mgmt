"use client";

import * as React from "react";
import Link from "next/link";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Globe2,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useAuth } from "@/lib/auth";
import {
  queryKeys,
  useBgpConfig,
  useCreateNetwork,
  useDeleteNetwork,
} from "@/lib/queries";
import { canWrite } from "@/lib/roles";
import { errorMessage } from "@/lib/api";
import { isPrefix, prefixMatchesAf } from "@/lib/validation";
import type { BgpNetwork, Router } from "@/lib/types";
import {
  BgpPageHeading,
  BgpRouterBoundary,
  NoBgpConfigured,
} from "@/components/bgp/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Stat, StatStrip } from "@/components/ui/stat";
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
import {
  EmptyState,
  ErrorPanel,
  InlineAlert,
  Spinner,
  TableSkeleton,
} from "@/components/states";

const networkSchema = z
  .object({
    af: z.enum(["ipv4-unicast", "ipv6-unicast"]),
    prefix: z
      .string()
      .trim()
      .min(1, "Prefix is required")
      .refine(isPrefix, "Enter a network prefix with host bits set to zero"),
  })
  .superRefine((values, ctx) => {
    if (!isPrefix(values.prefix)) return;
    if (!prefixMatchesAf(values.prefix, values.af)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["prefix"],
        message: `Prefix does not match ${values.af === "ipv4-unicast" ? "IPv4" : "IPv6"}`,
      });
    }
  });

type NetworkFormValues = z.infer<typeof networkSchema>;

function NetworkFormDialog({
  open,
  onOpenChange,
  routerId,
  existing,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  existing: BgpNetwork[];
}) {
  const [serverError, setServerError] = React.useState<string | null>(null);
  const createNetwork = useCreateNetwork(routerId);

  const form = useForm<NetworkFormValues>({
    resolver: zodResolver(networkSchema),
    defaultValues: { af: "ipv4-unicast", prefix: "" },
    mode: "onSubmit",
  });

  React.useEffect(() => {
    if (!open) return;
    form.reset({ af: "ipv4-unicast", prefix: "" });
    setServerError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const af = form.watch("af");

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const duplicate = existing.some(
      (network) =>
        network.af === values.af &&
        network.prefix.toLowerCase() === values.prefix.toLowerCase(),
    );
    if (duplicate) {
      form.setError("prefix", {
        type: "manual",
        message: "This prefix is already advertised in that family",
      });
      return;
    }
    try {
      await createNetwork.mutateAsync({
        af: values.af,
        prefix: values.prefix.trim(),
      });
      toast.success("Prefix advertised", {
        description: `${values.prefix.trim()} added to ${values.af}.`,
      });
      onOpenChange(false);
    } catch (error) {
      setServerError(
        error instanceof Error
          ? error.message
          : "Could not add the advertised network.",
      );
    }
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !createNetwork.isPending && onOpenChange(next)}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Globe2 className="size-4 text-primary" />
            Advertise a prefix
          </DialogTitle>
          <DialogDescription>
            Add a network statement to the BGP configuration. The prefix must be
            a valid network address with no host bits set.
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not add network">
            {serverError}
          </InlineAlert>
        )}

        <Form {...form}>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <FormField
              control={form.control}
              name="af"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Address family</FormLabel>
                  <Select
                    value={field.value}
                    onValueChange={field.onChange}
                    disabled={createNetwork.isPending}
                  >
                    <FormControl>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="ipv4-unicast">IPv4 unicast</SelectItem>
                      <SelectItem value="ipv6-unicast">IPv6 unicast</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="prefix"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Network prefix</FormLabel>
                  <FormControl>
                    <Input
                      placeholder={
                        af === "ipv4-unicast"
                          ? "203.0.113.0/24"
                          : "2001:db8:100::/48"
                      }
                      className="font-mono"
                      autoCapitalize="none"
                      spellCheck={false}
                      disabled={createNetwork.isPending}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    {af === "ipv4-unicast"
                      ? "IPv4 network in CIDR notation."
                      : "IPv6 network in CIDR notation."}
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
                disabled={createNetwork.isPending}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={createNetwork.isPending}>
                {createNetwork.isPending ? (
                  <>
                    <Loader2 className="size-4 animate-spin" /> Adding…
                  </>
                ) : (
                  <>
                    <Plus className="size-4" /> Advertise prefix
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

function NetworksContent({ router }: { router: Router }) {
  const { user } = useAuth();
  const writer = canWrite(user?.role);
  const queryClient = useQueryClient();
  const configQuery = useBgpConfig(router.id);
  const deleteNetwork = useDeleteNetwork(router.id);
  const [open, setOpen] = React.useState(false);
  const [deleteTarget, setDeleteTarget] = React.useState<BgpNetwork | null>(
    null,
  );
  const [refreshing, setRefreshing] = React.useState(false);

  const config = configQuery.data;
  const networks = config?.networks ?? [];
  const ipv4 = networks.filter((n) => n.af === "ipv4-unicast");
  const ipv6 = networks.filter((n) => n.af === "ipv6-unicast");

  const refresh = async () => {
    setRefreshing(true);
    await queryClient.invalidateQueries({
      queryKey: queryKeys.bgpConfig(router.id),
    });
    setRefreshing(false);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteNetwork.mutateAsync(deleteTarget);
      toast.success("Prefix removed", {
        description: `${deleteTarget.prefix} is no longer advertised.`,
      });
      setDeleteTarget(null);
    } catch (error) {
      toast.error("Could not remove prefix", {
        description: errorMessage(error),
      });
    }
  };

  const heading = (
    <BgpPageHeading
      title="Advertised networks"
      routerName={router.name}
      description="Prefixes originated into BGP as network statements. IPv4 and IPv6 unicast are managed independently."
      actions={
        <>
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
          {writer && config?.configured && (
            <Button size="sm" onClick={() => setOpen(true)}>
              <Plus className="size-4" /> Advertise prefix
            </Button>
          )}
        </>
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

  if (!config.configured) {
    return (
      <>
        {heading}
        <NoBgpConfigured router={router} />
      </>
    );
  }

  return (
    <>
      {heading}

      {!writer && (
        <InlineAlert tone="info" title="Read-only view">
          Viewers can inspect advertised prefixes. Changes require the operator
          or administrator role.
        </InlineAlert>
      )}

      <StatStrip className="grid-cols-1 sm:grid-cols-3 xl:grid-cols-3">
        <Stat label="Total" value={networks.length} hint="Advertised prefixes" />
        <Stat
          label="IPv4 unicast"
          value={ipv4.length}
          hint="IPv4 network statements"
        />
        <Stat
          label="IPv6 unicast"
          value={ipv6.length}
          hint="IPv6 network statements"
        />
      </StatStrip>

      <Card variant="surface" className="gap-0 overflow-hidden py-0">
        {networks.length === 0 ? (
          <div className="p-5">
            <EmptyState
              compact
              icon={Globe2}
              title="No advertised networks"
              description="Advertise a prefix so upstream and downstream peers can learn your routes."
              action={
                writer ? (
                  <Button size="sm" onClick={() => setOpen(true)}>
                    <Plus className="size-4" /> Advertise prefix
                  </Button>
                ) : undefined
              }
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-border/60 bg-muted/25">
                  {["Prefix", "Family", "Origin", ""].map((label, i) => (
                    <th
                      key={label || i}
                      className="px-4 py-2.5 text-left text-[10px] font-semibold tracking-[0.12em] whitespace-nowrap text-muted-foreground uppercase"
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {networks.map((network) => (
                  <tr
                    key={`${network.af}-${network.prefix}`}
                    className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/25"
                  >
                    <td className="px-4 py-3">
                      <span className="font-mono text-[12px] font-medium">
                        {network.prefix}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <Badge
                        variant="outline"
                        className="border-border/80 bg-muted/40 font-mono text-[9px]"
                      >
                        {network.af}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-[11px] text-muted-foreground">
                      network statement
                    </td>
                    <td className="px-4 py-3 text-right">
                      {writer ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 gap-1 px-2 text-[11px] text-destructive hover:text-destructive"
                          onClick={() => setDeleteTarget(network)}
                        >
                          <Trash2 className="size-3" /> Remove
                        </Button>
                      ) : (
                        <span className="text-[10px] text-muted-foreground">
                          read-only
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="flex flex-col gap-2 border-t border-border/70 pt-3 text-[11px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <span>
          Prefixes are advertised only if a route for them exists on the device.
        </span>
        <Link
          href="/bgp/neighbors/"
          className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
        >
          Review neighbors <ArrowRight className="size-3" />
        </Link>
      </div>

      {open && (
        <NetworkFormDialog
          open={open}
          onOpenChange={setOpen}
          routerId={router.id}
          existing={networks}
        />
      )}

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(next) => {
          if (!next && !deleteNetwork.isPending) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Stop advertising {deleteTarget?.prefix}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              The network statement will be removed from the device. Peers may
              withdraw routes that depended on this announcement.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteNetwork.isPending && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Spinner /> Removing prefix…
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteNetwork.isPending}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleteNetwork.isPending}
              onClick={(event) => {
                event.preventDefault();
                void handleDelete();
              }}
            >
              <Trash2 className="size-4" /> Remove prefix
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

export default function NetworksPage() {
  return (
    <BgpRouterBoundary>
      {(router) => <NetworksContent router={router} />}
    </BgpRouterBoundary>
  );
}
