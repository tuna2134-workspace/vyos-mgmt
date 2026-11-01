import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 [&>svg]:pointer-events-none [&>svg]:size-3",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary/12 text-primary dark:bg-primary/15 [&>svg]:text-primary",
        secondary: "border-border/70 bg-secondary text-secondary-foreground",
        destructive:
          "border-transparent bg-destructive/12 text-destructive dark:bg-destructive/20",
        outline: "border-border bg-transparent text-foreground",
        success:
          "border-transparent bg-emerald-500/12 text-emerald-600 dark:bg-emerald-400/15 dark:text-emerald-300",
        warning:
          "border-transparent bg-amber-500/14 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300",
        muted:
          "border-transparent bg-muted text-muted-foreground dark:bg-muted/70",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function Badge({
  className,
  variant,
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "span";

  return (
    <Comp
      data-slot="badge"
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  );
}

export { Badge, badgeVariants };
