import { ReactNode, useState, MouseEvent } from "react";
import { cn } from "../lib/cn";

interface SpotlightProps {
  children: ReactNode;
  className?: string;
  spotlightColor?: string;
}

export function Spotlight({ children, className,
  // audit #51: rgba(94,200,255,0.18) is the old dark-theme cyan and
  // didn't match the other three panel overrides. Default to the
  // current palette cyan so all four Spotlights match.
  spotlightColor = "rgba(11,128,209,0.18)"
}: SpotlightProps) {
  const [pos, setPos] = useState({ x: -200, y: -200 });
  const [opacity, setOpacity] = useState(0);

  const onMove = (e: MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setPos({ x: e.clientX - r.left, y: e.clientY - r.top });
    setOpacity(1);
  };
  const onLeave = () => setOpacity(0);

  return (
    <div
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      className={cn("relative overflow-hidden rounded-2xl border border-line bg-panel", className)}
    >
      <div
        className="pointer-events-none absolute inset-0 transition-opacity duration-300"
        style={{
          opacity,
          background: `radial-gradient(400px circle at ${pos.x}px ${pos.y}px, ${spotlightColor}, transparent 60%)`,
        }}
      />
      {children}
    </div>
  );
}