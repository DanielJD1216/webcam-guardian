import { ReactNode } from "react";
import { cn } from "../lib/cn";

interface AnimatedGradientTextProps {
  children: ReactNode;
  className?: string;
}

export function AnimatedGradientText({ children, className }: AnimatedGradientTextProps) {
  return (
    <span
      className={cn(
        "inline-block bg-gradient-to-r from-cyan via-yellow to-cyan bg-[length:200%_auto] bg-clip-text text-transparent animate-gradient-x",
        className,
      )}
    >
      {children}
    </span>
  );
}