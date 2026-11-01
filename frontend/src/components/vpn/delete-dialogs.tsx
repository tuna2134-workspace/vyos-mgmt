"use client";

import { Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { errorMessage } from "@/lib/api";
import {
  useDeleteWireGuardInterface,
  useDeleteWireGuardPeer,
} from "@/lib/queries";
import type { WireGuardInterface, WireGuardPeer } from "@/lib/types";
import { wireGuardPath } from "@/components/vpn/shared";
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
import { InlineAlert, Spinner } from "@/components/states";

/** Deleting an interface also deletes every peer configured on it. */
export function WireGuardInterfaceDeleteDialog({
  open,
  onOpenChange,
  routerId,
  iface,
  onDeleted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  iface: WireGuardInterface | null;
  onDeleted?: (name: string) => void;
}) {
  const remove = useDeleteWireGuardInterface(routerId);

  const handleDelete = async () => {
    if (!iface) return;
    try {
      await remove.mutateAsync(iface.name);
      toast.success(`${iface.name} deleted`, {
        description:
          iface.peer_count > 0
            ? `${iface.peer_count} peer${iface.peer_count === 1 ? "" : "s"} removed with the interface.`
            : "The WireGuard interface was removed from the router.",
      });
      onDeleted?.(iface.name);
      onOpenChange(false);
    } catch (error) {
      toast.error("Could not delete the interface", {
        description: errorMessage(error),
      });
    }
  };

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!remove.isPending) onOpenChange(next);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <Trash2 className="size-4 text-destructive" />
            Delete {iface?.name}?
          </AlertDialogTitle>
          <AlertDialogDescription>
            This removes{" "}
            <code className="font-mono text-[11px]">
              {iface ? wireGuardPath(iface.name) : "the interface"}
            </code>{" "}
            and all of its peers from the router. Tunnels using this interface
            drop immediately and peer keys have to be recreated.
          </AlertDialogDescription>
        </AlertDialogHeader>

        {iface && iface.peer_count > 0 && (
          <InlineAlert tone="warning" title="Peers are deleted too">
            {iface.peer_count} peer{iface.peer_count === 1 ? "" : "s"}{" "}
            {iface.peer_count === 1 ? "is" : "are"} configured on this interface.
            There is no undo; the configuration must be rebuilt from scratch.
          </InlineAlert>
        )}

        {remove.isPending && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Spinner /> Deleting interface…
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={remove.isPending}>
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            disabled={remove.isPending || !iface}
            onClick={(event) => {
              event.preventDefault();
              void handleDelete();
            }}
          >
            {remove.isPending ? (
              <>
                <Loader2 className="size-4 animate-spin" /> Deleting…
              </>
            ) : (
              <>
                <Trash2 className="size-4" /> Delete interface
              </>
            )}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function WireGuardPeerDeleteDialog({
  open,
  onOpenChange,
  routerId,
  ifaceName,
  peer,
  onDeleted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  ifaceName: string;
  peer: WireGuardPeer | null;
  onDeleted?: (name: string) => void;
}) {
  const remove = useDeleteWireGuardPeer(routerId);

  const handleDelete = async () => {
    if (!peer) return;
    try {
      await remove.mutateAsync({ iface: ifaceName, peer: peer.name });
      toast.success(`Peer ${peer.name} deleted`, {
        description: `Removed from ${ifaceName}. Its allowed IPs are free for another peer.`,
      });
      onDeleted?.(peer.name);
      onOpenChange(false);
    } catch (error) {
      toast.error("Could not delete the peer", {
        description: errorMessage(error),
      });
    }
  };

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!remove.isPending) onOpenChange(next);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <Trash2 className="size-4 text-destructive" />
            Delete peer {peer?.name}?
          </AlertDialogTitle>
          <AlertDialogDescription>
            The peer is removed from{" "}
            <span className="font-mono">{ifaceName}</span>. Its tunnel stops and
            the allowed IP prefixes can be reassigned to another peer.
          </AlertDialogDescription>
        </AlertDialogHeader>

        {peer && peer.allowed_ips.length > 0 && (
          <p className="rounded-md border border-border/60 bg-muted/25 px-2.5 py-2 font-mono text-[10px] break-all text-muted-foreground">
            {peer.allowed_ips.join(", ")}
          </p>
        )}

        {remove.isPending && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Spinner /> Deleting peer…
          </div>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={remove.isPending}>
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            disabled={remove.isPending || !peer}
            onClick={(event) => {
              event.preventDefault();
              void handleDelete();
            }}
          >
            {remove.isPending ? (
              <>
                <Loader2 className="size-4 animate-spin" /> Deleting…
              </>
            ) : (
              <>
                <Trash2 className="size-4" /> Delete peer
              </>
            )}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
