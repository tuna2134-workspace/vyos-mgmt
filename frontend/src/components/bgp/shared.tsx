"use client";

import * as React from "react";
import Link from "next/link";
import { Route, Waypoints } from "lucide-react";

import { canWrite } from "@/lib/roles";
import { useAuth } from "@/lib/auth";
import type {
  AddressFamilies,
  AddressFamilyKey,
  AddressFamilySettings,
  Router,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { AF_LABEL } from "@/lib/validation";
import { RouterBoundary } from "@/components/router-boundary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, PageHeader } from "@/components/states";

export const DEFAULT_AF_SETTINGS: AddressFamilySettings = {
  route_reflector_client: false,
  next_hop_self: false,
  soft_reconfiguration_inbound: false,
  default_originate: false,
  allowas_in: null,
  route_map_import: null,
  route_map_export: null,
};

export function makeAfSettings(
  overrides: Partial<AddressFamilySettings> = {},
): AddressFamilySettings {
  return { ...DEFAULT_AF_SETTINGS, ...overrides };
}

/** Copy API families and fill any fields an older payload may omit. */
export function withAfDefaults(
  families: AddressFamilies | undefined,
): AddressFamilies {
  if (!families) return {};
  const result: AddressFamilies = {};
  for (const key of Object.keys(families) as AddressFamilyKey[]) {
    const settings = families[key];
    if (settings) result[key] = makeAfSettings(settings);
  }
  return result;
}

export function enabledFamilies(families: AddressFamilies | undefined) {
  if (!families) return [];
  return (Object.keys(families) as AddressFamilyKey[]).filter(
    (key) => families[key] != null,
  );
}

/** BGP-flavoured wrapper around the shared router boundary. */
export function BgpRouterBoundary({
  children,
  loading,
}: {
  children: (router: Router) => React.ReactNode;
  loading?: React.ReactNode;
}) {
  return (
    <RouterBoundary
      loading={loading}
      emptyDescription="Add a VyOS device before configuring or monitoring BGP."
    >
      {children}
    </RouterBoundary>
  );
}

export function NoBgpConfigured({
  router,
  title = "BGP is not configured",
  description,
}: {
  router: Pick<Router, "id" | "name">;
  title?: string;
  description?: React.ReactNode;
}) {
  const { user } = useAuth();
  const writable = canWrite(user?.role);
  return (
    <EmptyState
      icon={Waypoints}
      title={title}
      description={
        description ?? (
          <>
            No BGP configuration exists on <strong>{router.name}</strong> yet.
            Set a local AS and router ID to start, then add neighbors and
            advertised networks.
          </>
        )
      }
      action={
        writable ? (
          <Button asChild>
            <Link href={`/bgp/settings/?router=${router.id}`}>
              Configure BGP
            </Link>
          </Button>
        ) : (
          <span className="text-xs text-muted-foreground">
            An operator or administrator can configure BGP.
          </span>
        )
      }
    />
  );
}

export function AddressFamilyBadges({
  families,
  className,
}: {
  families: AddressFamilies | undefined;
  className?: string;
}) {
  const enabled = enabledFamilies(families);
  if (enabled.length === 0) {
    return <span className="text-[11px] text-muted-foreground">none</span>;
  }
  return (
    <div className={cn("flex flex-wrap gap-1", className)}>
      {enabled.map((af) => (
        <Badge
          key={af}
          variant="outline"
          className="border-border/80 bg-muted/40 font-mono text-[9px]"
        >
          {af === "ipv4-unicast" ? "IPv4" : "IPv6"}
        </Badge>
      ))}
    </div>
  );
}

/**
 * Compact read-only display of the per-family BGP import/export route maps.
 * Returns `null` when no policy is attached so tables stay clean.
 */
export function RouteMapPolicy({
  families,
  className,
}: {
  families: AddressFamilies | undefined;
  className?: string;
}) {
  const entries = enabledFamilies(families)
    .map((af) => ({
      af,
      importName: families?.[af]?.route_map_import ?? null,
      exportName: families?.[af]?.route_map_export ?? null,
    }))
    .filter((entry) => entry.importName || entry.exportName);

  if (entries.length === 0) return null;

  return (
    <p
      className={cn(
        "mt-1 flex flex-wrap gap-x-2 gap-y-0.5 font-mono text-[9px] text-muted-foreground",
        className,
      )}
    >
      {entries.map((entry) => (
        <span
          key={entry.af}
          className="whitespace-nowrap"
          title={`${AF_LABEL[entry.af]} import/export route maps`}
        >
          <span className="text-muted-foreground/70">
            {entry.af === "ipv4-unicast" ? "v4" : "v6"}
          </span>
          {entry.importName && (
            <span title={`import: ${entry.importName}`}>
              {" "}
              <span className="text-primary">↓</span>{" "}
              <span className="text-foreground/80">{entry.importName}</span>
            </span>
          )}
          {entry.exportName && (
            <span title={`export: ${entry.exportName}`}>
              {" "}
              <span className="text-primary">↑</span>{" "}
              <span className="text-foreground/80">{entry.exportName}</span>
            </span>
          )}
        </span>
      ))}
    </p>
  );
}

function SettingRow({
  label,
  description,
  checked,
  onCheckedChange,
  disabled,
  id,
}: {
  label: string;
  description: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  id: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-border/60 bg-card/40 px-3 py-2.5">
      <div className="min-w-0">
        <Label htmlFor={id} className="cursor-pointer text-[13px]">
          {label}
        </Label>
        <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
          {description}
        </p>
      </div>
      <Switch
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
      />
    </div>
  );
}

const NO_ROUTE_MAP = "__none__";

function RouteMapSelect({
  id,
  label,
  value,
  names,
  onChange,
  disabled,
}: {
  id: string;
  label: string;
  value: string | null;
  names: string[];
  onChange: (next: string | null) => void;
  disabled?: boolean;
}) {
  // Keep a configured name selectable even when it is missing from the list
  // (deleted on the device, or the route-map list failed to load).
  const options = React.useMemo(() => {
    const set = new Set(names);
    if (value) set.add(value);
    return [...set].sort((a, b) => a.localeCompare(b));
  }, [names, value]);

  return (
    <div className="min-w-0 space-y-1">
      <Label htmlFor={id} className="text-[12px]">
        {label}
      </Label>
      <Select
        value={value ?? NO_ROUTE_MAP}
        onValueChange={(next) =>
          onChange(next === NO_ROUTE_MAP ? null : next)
        }
        disabled={disabled}
      >
        <SelectTrigger
          id={id}
          size="sm"
          className="w-full font-mono text-xs"
          aria-label={label}
        >
          <SelectValue placeholder="None" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NO_ROUTE_MAP}>None</SelectItem>
          {options.map((name) => (
            <SelectItem key={name} value={name}>
              {name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

/**
 * Controlled editor for the two managed address families. Presence of an AF
 * key means "activated"; the object is authoritative when submitted via PATCH.
 *
 * `routeMaps` supplies the router's existing route-map names for the
 * import/export policy selects. The API validates shape, not existence, so a
 * value that is not in the list is still selectable.
 */
export function AfSettingsEditor({
  value,
  onChange,
  disabled,
  namePrefix = "af",
  routeMaps = [],
}: {
  value: AddressFamilies;
  onChange: (next: AddressFamilies) => void;
  disabled?: boolean;
  namePrefix?: string;
  routeMaps?: string[];
}) {
  const id = React.useId();
  const [tab, setTab] = React.useState<AddressFamilyKey>("ipv4-unicast");
  const families: AddressFamilyKey[] = ["ipv4-unicast", "ipv6-unicast"];
  const current = value[tab];

  const update = React.useCallback(
    (patch: Partial<AddressFamilySettings>) => {
      if (!current) return;
      onChange({ ...value, [tab]: { ...current, ...patch } });
    },
    [current, onChange, tab, value],
  );

  const toggleFamily = (next: boolean) => {
    if (next) {
      onChange({ ...value, [tab]: makeAfSettings(current ?? {}) });
    } else {
      const copy = { ...value };
      delete copy[tab];
      onChange(copy);
    }
  };

  return (
    <div className="rounded-xl border border-border/80 bg-muted/20 p-3">
      <Tabs
        value={tab}
        onValueChange={(next) => setTab(next as AddressFamilyKey)}
      >
        <TabsList className="grid w-full grid-cols-2 bg-background/60">
          {families.map((af) => (
            <TabsTrigger key={af} value={af} className="gap-2 text-xs">
              {AF_LABEL[af]}
              <span
                className={cn(
                  "size-1.5 rounded-full",
                  value[af] ? "bg-emerald-500" : "bg-muted-foreground/40",
                )}
                aria-label={value[af] ? "activated" : "not activated"}
              />
            </TabsTrigger>
          ))}
        </TabsList>

        {families.map((af) => {
          const settings = value[af];
          const isEnabled = !!settings;
          return (
            <TabsContent key={af} value={af} className="mt-3 space-y-2">
              <div className="flex items-center justify-between rounded-lg border border-primary/20 bg-primary/[0.04] px-3 py-2.5">
                <div>
                  <p className="text-[13px] font-medium">
                    Activate {AF_LABEL[af]}
                  </p>
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    Deactivated families are omitted from the managed
                    configuration.
                  </p>
                </div>
                <Switch
                  checked={isEnabled}
                  onCheckedChange={toggleFamily}
                  disabled={disabled}
                  aria-label={`Activate ${AF_LABEL[af]}`}
                />
              </div>

              <SettingRow
                id={`${id}-${af}-rr`}
                label="Route reflector client"
                description="Mark this neighbor as an RR client in this family."
                checked={settings?.route_reflector_client ?? false}
                onCheckedChange={(checked) =>
                  update({ route_reflector_client: checked })
                }
                disabled={disabled || !isEnabled}
              />
              <SettingRow
                id={`${id}-${af}-nhs`}
                label="Next hop self"
                description="Rewrite the next hop toward this neighbor."
                checked={settings?.next_hop_self ?? false}
                onCheckedChange={(checked) => update({ next_hop_self: checked })}
                disabled={disabled || !isEnabled}
              />
              <SettingRow
                id={`${id}-${af}-soft`}
                label="Soft reconfiguration (inbound)"
                description="Store received routes to allow inbound policy refreshes without a hard reset."
                checked={settings?.soft_reconfiguration_inbound ?? false}
                onCheckedChange={(checked) =>
                  update({ soft_reconfiguration_inbound: checked })
                }
                disabled={disabled || !isEnabled}
              />
              <SettingRow
                id={`${id}-${af}-default`}
                label="Default originate"
                description="Originate a default route to this neighbor."
                checked={settings?.default_originate ?? false}
                onCheckedChange={(checked) =>
                  update({ default_originate: checked })
                }
                disabled={disabled || !isEnabled}
              />

              <div className="space-y-2 rounded-lg border border-primary/20 bg-primary/[0.03] px-3 py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-1.5">
                  <p className="flex items-center gap-1.5 text-[13px] font-medium">
                    <Route className="size-3.5 text-primary" />
                    Route-map policy
                  </p>
                  <Link
                    href="/route-maps/"
                    className="text-[10px] font-medium text-primary underline-offset-2 hover:underline"
                  >
                    Manage route maps
                  </Link>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <RouteMapSelect
                    id={`${namePrefix}-${id}-${af}-rm-in`}
                    label="Inbound route-map (import)"
                    value={settings?.route_map_import ?? null}
                    names={routeMaps}
                    onChange={(next) => update({ route_map_import: next })}
                    disabled={disabled || !isEnabled}
                  />
                  <RouteMapSelect
                    id={`${namePrefix}-${id}-${af}-rm-out`}
                    label="Outbound route-map (export)"
                    value={settings?.route_map_export ?? null}
                    names={routeMaps}
                    onChange={(next) => update({ route_map_export: next })}
                    disabled={disabled || !isEnabled}
                  />
                </div>
                <p className="text-[10px] leading-relaxed text-muted-foreground">
                  Maps to{" "}
                  <code className="font-mono">
                    route-map import|export &lt;name&gt;
                  </code>{" "}
                  in this address family. Route-map names are references; they
                  must exist on the device.
                </p>
              </div>

              <div className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-card/40 px-3 py-2.5">
                <div className="min-w-0">
                  <Label
                    htmlFor={`${namePrefix}-${id}-${af}-allowas`}
                    className="text-[13px]"
                  >
                    Allow AS in
                  </Label>
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    Accept routes containing this many repetitions of our AS
                    (1–10). Leave empty to disable.
                  </p>
                </div>
                <Input
                  id={`${namePrefix}-${id}-${af}-allowas`}
                  type="number"
                  min={1}
                  max={10}
                  inputMode="numeric"
                  className="h-8 w-20 text-center font-mono text-xs"
                  value={settings?.allowas_in ?? ""}
                  disabled={disabled || !isEnabled}
                  onChange={(event) => {
                    const raw = event.target.value;
                    if (raw === "") {
                      update({ allowas_in: null });
                      return;
                    }
                    const parsed = Number(raw);
                    if (!Number.isFinite(parsed)) return;
                    update({
                      allowas_in: Math.max(
                        1,
                        Math.min(10, Math.trunc(parsed)),
                      ),
                    });
                  }}
                  placeholder="—"
                />
              </div>
            </TabsContent>
          );
        })}
      </Tabs>
      <p className="mt-2.5 px-1 text-[10px] leading-relaxed text-muted-foreground">
        Only IPv4 and IPv6 unicast are managed here. Other families on the
        device are left untouched.
      </p>
    </div>
  );
}

export function BgpPageHeading({
  title,
  description,
  actions,
  routerName,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  routerName?: string;
}) {
  return (
    <PageHeader
      title={title}
      description={description}
      actions={actions}
      badge={
        routerName ? (
          <Badge
            variant="outline"
            className="gap-1.5 border-primary/25 bg-primary/5 font-mono text-[10px]"
          >
            <span className="size-1.5 rounded-full bg-primary" />
            {routerName}
          </Badge>
        ) : undefined
      }
    />
  );
}
