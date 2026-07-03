import { ReactNode } from "react";
import { cn } from "../lib/cn";

interface BackgroundGradientProps {
  children: ReactNode;
  className?: string;
}

export function BackgroundGradient({ children, className }: BackgroundGradientProps) {
  return (
    <div className={cn("relative isolate min-h-screen w-full", className)}>
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(ellipse 80% 50% at 20% 0%, rgba(94,200,255,0.12), transparent 60%), radial-gradient(ellipse 60% 50% at 80% 100%, rgba(255,200,87,0.10), transparent 60%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 opacity-[0.04]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.6) 1px, transparent 1px)",
          backgroundSize: "44px 44px",
          maskImage: "radial-gradient(ellipse at center, black 30%, transparent 70%)",
        }}
      />
      {children}
    </div>
  );
}