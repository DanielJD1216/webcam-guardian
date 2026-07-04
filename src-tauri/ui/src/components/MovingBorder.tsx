import { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "../lib/cn";

interface MovingBorderProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  borderColor?: string;
  duration?: number;
  variant?: "primary" | "secondary" | "danger";
}

export function MovingBorder({
  children,
  // audit #51: the old "#5ec8ff" was the dark-theme cyan and was
  // nearly invisible against the light-theme panels. Default to the
  // current palette cyan so the animated border is actually visible.
  borderColor = "#0b80d1",
  duration = 6000,
  variant = "primary",
  className,
  ...props
}: MovingBorderProps) {
  const variantClasses = {
    primary: "bg-cyan text-bg font-semibold hover:bg-cyan/90",
    secondary: "bg-elev text-text hover:bg-line",
    danger: "bg-red/15 text-red hover:bg-red/25",
  }[variant];

  return (
    <button
      {...props}
      className={cn(
        "relative inline-flex items-center justify-center rounded-lg px-5 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-40",
        variantClasses,
        className,
      )}
    >
      <span
        className="pointer-events-none absolute inset-[-2px] rounded-[10px] opacity-60"
        style={{
          background: `conic-gradient(from var(--angle), transparent 0deg, ${borderColor} 60deg, transparent 180deg)`,
          animation: `border-spin ${duration}ms linear infinite`,
        }}
      />
      <span className="relative z-10 flex items-center gap-2">{children}</span>
      <style>{`button { --angle: 0deg; }`}</style>
    </button>
  );
}