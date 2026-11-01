import { cn } from "@/lib/utils";

export function LogoMark({
  className,
  size = 36,
}: {
  className?: string;
  size?: number;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      role="img"
      aria-label="VyOS Control logo"
      className={cn("shrink-0", className)}
    >
      <defs>
        <linearGradient id="vyos-mark-bg" x1="4" y1="4" x2="44" y2="44">
          <stop stopColor="#0e7490" />
          <stop offset="0.55" stopColor="#0891b2" />
          <stop offset="1" stopColor="#10b981" />
        </linearGradient>
        <linearGradient id="vyos-mark-line" x1="10" y1="10" x2="38" y2="38">
          <stop stopColor="#ecfeff" />
          <stop offset="1" stopColor="#a7f3d0" />
        </linearGradient>
      </defs>
      <rect
        x="2"
        y="2"
        width="44"
        height="44"
        rx="12"
        fill="url(#vyos-mark-bg)"
      />
      <rect
        x="2.75"
        y="2.75"
        width="42.5"
        height="42.5"
        rx="11.25"
        stroke="white"
        strokeOpacity="0.18"
        strokeWidth="1.5"
      />
      <g stroke="url(#vyos-mark-line)" strokeWidth="1.9" strokeLinecap="round">
        <path d="M16 17.5 24 24l8-6.5" opacity="0.65" />
        <path d="M24 24v9" opacity="0.65" />
        <path d="M16 17.5 24 33l8-15.5" opacity="0.35" />
      </g>
      <g fill="#ecfeff">
        <circle cx="16" cy="17.5" r="3.1" />
        <circle cx="32" cy="17.5" r="3.1" />
        <circle cx="24" cy="33" r="3.1" />
      </g>
      <circle cx="24" cy="24" r="2.1" fill="#5eead4" />
    </svg>
  );
}

export function Logo({
  className,
  compact = false,
}: {
  className?: string;
  compact?: boolean;
}) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <LogoMark size={compact ? 30 : 34} />
      {!compact && (
        <div className="flex flex-col leading-none">
          <span className="text-[15px] font-semibold tracking-tight">
            VyOS <span className="text-primary">Control</span>
          </span>
          <span className="mt-1 text-[10px] font-medium tracking-[0.18em] text-muted-foreground uppercase">
            Network operations
          </span>
        </div>
      )}
    </div>
  );
}
