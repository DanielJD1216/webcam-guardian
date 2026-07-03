import { cn } from "../lib/cn";

type Variant = "stopped" | "running" | "error";

export function StatusPill({ state, label, className }: { state: Variant; label: string; className?: string }) {
  const colorClass = {
    stopped: "bg-red/15 text-red border-red/30",
    running: "bg-green/15 text-green border-green/30 animate-pulse-slow",
    error:   "bg-yellow/15 text-yellow border-yellow/30",
  }[state];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium",
        colorClass,
        className,
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          state === "running" ? "bg-green animate-pulse-slow" :
          state === "error" ? "bg-yellow animate-pulse" :
          "bg-red",
        )}
      />
      {label}
    </span>
  );
}