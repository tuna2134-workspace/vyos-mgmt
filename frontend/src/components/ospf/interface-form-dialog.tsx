"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Cable, Loader2, Plus, Save } from "lucide-react";
import { type Control, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ApiError } from "@/lib/api";
import { applyServerFormErrors } from "@/lib/form-errors";
import {
  useCreateOspfInterface,
  useUpdateOspfInterface,
} from "@/lib/queries";
import type {
  OspfArea,
  OspfInterface,
  OspfNetworkType,
  OspfVersion,
} from "@/lib/types";
import {
  INTERFACE_NAME_PATTERN,
  NETWORK_TYPE_LABEL,
  VERSION_VYOS_PATH,
  isOptionalIntegerInRange,
  optionalInteger,
} from "@/components/ospf/shared";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { InlineAlert } from "@/components/states";

/** Empty string = device default (`null` on the wire). */
const DEVICE_DEFAULT = "__default__";

const OPTIONAL_INTEGER_FIELDS = [
  ["cost", 1, 65535, "Cost"],
  ["hello_interval", 1, 65535, "Hello interval"],
  ["dead_interval", 1, 65535, "Dead interval"],
  ["priority", 0, 255, "Priority"],
  ["retransmit_interval", 1, 65535, "Retransmit interval"],
  ["transmit_delay", 1, 65535, "Transmit delay"],
] as const;

const NUMBER_FIELD_NAMES = OPTIONAL_INTEGER_FIELDS.map(([name]) => name);

function makeInterfaceSchema(isCreate: boolean) {
  return z
    .object({
      name: z.string(),
      area_id: z.string(),
      network_type: z.string(),
      cost: z.string(),
      hello_interval: z.string(),
      dead_interval: z.string(),
      priority: z.string(),
      passive: z.boolean(),
      bfd: z.boolean(),
      mtu_ignore: z.boolean(),
      retransmit_interval: z.string(),
      transmit_delay: z.string(),
    })
    .superRefine((values, ctx) => {
      if (isCreate) {
        const name = values.name.trim();
        if (!name) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["name"],
            message: "Interface name is required",
          });
        } else if (!INTERFACE_NAME_PATTERN.test(name)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["name"],
            message:
              "Start with a letter; then letters, digits, dots, underscores or hyphens (up to 64 characters)",
          });
        }
      }

      if (!values.area_id) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["area_id"],
          message: "Select the area this interface belongs to",
        });
      }

      for (const [field, min, max, label] of OPTIONAL_INTEGER_FIELDS) {
        if (!isOptionalIntegerInRange(values[field], min, max)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: [field],
            message: `${label} must be between ${min} and ${max}`,
          });
        }
      }
    });
}

type InterfaceFormValues = z.infer<ReturnType<typeof makeInterfaceSchema>>;

function numberField(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function FlagToggle({
  control,
  name,
  label,
  description,
  disabled,
}: {
  control: Control<InterfaceFormValues>;
  name: "passive" | "bfd" | "mtu_ignore";
  label: string;
  description: string;
  disabled?: boolean;
}) {
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem className="flex items-center justify-between gap-2 rounded-lg border border-border/70 px-3 py-2.5">
          <div className="min-w-0 space-y-0.5">
            <FormLabel className="text-[12px]">{label}</FormLabel>
            <p className="text-[10px] leading-relaxed text-muted-foreground">
              {description}
            </p>
          </div>
          <FormControl>
            <Switch
              checked={field.value}
              onCheckedChange={field.onChange}
              disabled={disabled}
              aria-label={label}
            />
          </FormControl>
        </FormItem>
      )}
    />
  );
}

export function OspfInterfaceFormDialog({
  open,
  onOpenChange,
  routerId,
  version,
  areas,
  supportedNetworkTypes,
  ospfInterface,
  onGoToAreas,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routerId: string;
  version: OspfVersion;
  areas: OspfArea[];
  supportedNetworkTypes: OspfNetworkType[];
  /** `null` creates a new interface; otherwise edits all managed fields. */
  ospfInterface: OspfInterface | null;
  /** Switches the page to the Areas tab (this dialog closes first). */
  onGoToAreas?: () => void;
}) {
  const isCreate = ospfInterface === null;
  const [serverError, setServerError] = React.useState<string | null>(null);
  const createInterface = useCreateOspfInterface(routerId, version);
  const updateInterface = useUpdateOspfInterface(routerId, version);
  const pending = createInterface.isPending || updateInterface.isPending;

  const schema = React.useMemo(
    () => makeInterfaceSchema(isCreate),
    [isCreate],
  );
  const form = useForm<InterfaceFormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: "",
      area_id: areas[0]?.area_id ?? "",
      network_type: "",
      cost: "",
      hello_interval: "",
      dead_interval: "",
      priority: "",
      passive: false,
      bfd: false,
      mtu_ignore: false,
      retransmit_interval: "",
      transmit_delay: "",
    },
    mode: "onSubmit",
  });

  React.useEffect(() => {
    if (!open) return;
    form.reset({
      name: ospfInterface?.name ?? "",
      // Never silently retarget an existing interface: an interface whose area
      // is missing on the device starts unselected and must be fixed by hand.
      area_id: isCreate
        ? (areas[0]?.area_id ?? "")
        : (ospfInterface?.area_id ?? ""),
      network_type: ospfInterface?.network_type ?? "",
      cost: numberField(ospfInterface?.cost),
      hello_interval: numberField(ospfInterface?.hello_interval),
      dead_interval: numberField(ospfInterface?.dead_interval),
      priority: numberField(ospfInterface?.priority),
      passive: ospfInterface?.passive ?? false,
      bfd: ospfInterface?.bfd ?? false,
      mtu_ignore: ospfInterface?.mtu_ignore ?? false,
      retransmit_interval: numberField(ospfInterface?.retransmit_interval),
      transmit_delay: numberField(ospfInterface?.transmit_delay),
    });
    setServerError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, ospfInterface?.name, routerId, version]);

  // A stale area reference (deleted outside this console) stays selectable so
  // editing cannot silently move the interface to another area.
  const areaIds = React.useMemo(() => {
    const ids = areas.map((area) => area.area_id);
    if (
      ospfInterface?.area_id &&
      !ids.includes(ospfInterface.area_id)
    ) {
      ids.unshift(ospfInterface.area_id);
    }
    return ids;
  }, [areas, ospfInterface?.area_id]);

  const networkTypes = React.useMemo(() => {
    const values = supportedNetworkTypes.length
      ? supportedNetworkTypes
      : (Object.keys(NETWORK_TYPE_LABEL) as OspfNetworkType[]);
    if (
      ospfInterface?.network_type &&
      !values.includes(ospfInterface.network_type)
    ) {
      return [...values, ospfInterface.network_type];
    }
    return values;
  }, [supportedNetworkTypes, ospfInterface?.network_type]);

  const onSubmit = form.handleSubmit(async (values) => {
    setServerError(null);
    const payload = {
      area_id: values.area_id,
      network_type: values.network_type
        ? (values.network_type as OspfNetworkType)
        : null,
      cost: optionalInteger(values.cost),
      hello_interval: optionalInteger(values.hello_interval),
      dead_interval: optionalInteger(values.dead_interval),
      priority: optionalInteger(values.priority),
      passive: values.passive,
      bfd: values.bfd,
      mtu_ignore: values.mtu_ignore,
      retransmit_interval: optionalInteger(values.retransmit_interval),
      transmit_delay: optionalInteger(values.transmit_delay),
    };

    try {
      if (isCreate) {
        const name = values.name.trim();
        await createInterface.mutateAsync({ name, ...payload });
        toast.success("OSPF interface added", {
          description: `${name} is now active in area ${values.area_id}.`,
        });
      } else {
        await updateInterface.mutateAsync({
          name: ospfInterface.name,
          payload,
        });
        toast.success("OSPF interface updated", {
          description: `${ospfInterface.name} saved on the router.`,
        });
      }
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError && error.code === "ospf_interface_exists") {
        form.setError("name", {
          type: "server",
          message: "An OSPF interface with this name already exists",
        });
        return;
      }
      if (error instanceof ApiError && error.code === "ospf_area_not_found") {
        form.setError("area_id", {
          type: "server",
          message: "That area no longer exists on the device",
        });
        return;
      }
      const applied = applyServerFormErrors(error, form.setError, [
        "name",
        "area_id",
        "network_type",
        ...NUMBER_FIELD_NAMES,
        "passive",
        "bfd",
        "mtu_ignore",
      ]);
      if (!applied) {
        setServerError(
          error instanceof Error
            ? error.message
            : "Could not save the OSPF interface.",
        );
      }
    }
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Cable className="size-4 text-primary" />
            {isCreate
              ? "Activate an interface"
              : `Edit OSPF interface ${ospfInterface?.name}`}
          </DialogTitle>
          <DialogDescription>
            Stored under{" "}
            <code className="font-mono text-[11px]">
              {VERSION_VYOS_PATH[version]}
            </code>{" "}
            · interface. Every field is written on save; empty numeric fields
            fall back to the device default.
          </DialogDescription>
        </DialogHeader>

        {serverError && (
          <InlineAlert tone="error" title="Could not save interface">
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
                    <FormLabel>Interface</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="eth0"
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
                        ? "A VyOS interface name, e.g. eth0 or vtun0."
                        : "The interface name is immutable."}
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="area_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Area</FormLabel>
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                      disabled={pending || areaIds.length === 0}
                    >
                      <FormControl>
                        <SelectTrigger className="w-full font-mono text-xs">
                          <SelectValue placeholder="Select an area" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {areaIds.map((areaId) => (
                          <SelectItem key={areaId} value={areaId}>
                            {areaId}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      {areas.length === 0 ? (
                        <>
                          No areas exist yet.{" "}
                          <button
                            type="button"
                            onClick={onGoToAreas}
                            className="font-medium text-primary underline-offset-2 hover:underline"
                          >
                            Create an area
                          </button>{" "}
                          first.
                        </>
                      ) : (
                        "Interfaces must reference an existing area."
                      )}
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="network_type"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Network type</FormLabel>
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
                        {networkTypes.map((value) => (
                          <SelectItem key={value} value={value}>
                            {NETWORK_TYPE_LABEL[value] ?? value}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      Version-specific. OSPFv3 supports only broadcast and
                      point-to-point.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="cost"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Cost</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        inputMode="numeric"
                        min={1}
                        max={65535}
                        placeholder="Auto"
                        className="font-mono"
                        disabled={pending}
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>1–65535; empty = auto.</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              {(
                [
                  ["hello_interval", "Hello interval", "10"],
                  ["dead_interval", "Dead interval", "40"],
                  ["priority", "Priority", "1"],
                ] as const
              ).map(([name, label, placeholder]) => (
                <FormField
                  key={name}
                  control={form.control}
                  name={name}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{label}</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          inputMode="numeric"
                          placeholder={placeholder}
                          className="font-mono"
                          disabled={pending}
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              ))}
            </div>

            <div className="rounded-xl border border-border/70 bg-muted/20 p-3">
              <p className="mb-2 text-[10px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
                Advanced timers
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                {(
                  [
                    ["retransmit_interval", "Retransmit interval"],
                    ["transmit_delay", "Transmit delay"],
                  ] as const
                ).map(([name, label]) => (
                  <FormField
                    key={name}
                    control={form.control}
                    name={name}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{label}</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            inputMode="numeric"
                            placeholder="Default"
                            className="font-mono"
                            disabled={pending}
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>1–65535; empty = default.</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                ))}
              </div>
            </div>

            <div className="grid gap-2 sm:grid-cols-3">
              <FlagToggle
                control={form.control}
                name="passive"
                label="Passive"
                description="Do not form adjacencies."
                disabled={pending}
              />
              <FlagToggle
                control={form.control}
                name="bfd"
                label="BFD"
                description="Fast failure detection."
                disabled={pending}
              />
              <FlagToggle
                control={form.control}
                name="mtu_ignore"
                label="MTU-ignore"
                description="Ignore MTU mismatches."
                disabled={pending}
              />
            </div>

            <DialogFooter className="gap-2 border-t border-border/60 pt-4">
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
                disabled={pending || areaIds.length === 0}
              >
                {pending ? (
                  <>
                    <Loader2 className="size-4 animate-spin" /> Saving…
                  </>
                ) : isCreate ? (
                  <>
                    <Plus className="size-4" /> Activate interface
                  </>
                ) : (
                  <>
                    <Save className="size-4" /> Save interface
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
