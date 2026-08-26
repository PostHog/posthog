import { cn } from "@posthog/quill";
import logoLoading from "@posthog/ui/assets/images/logo-loading.gif";
import logoStatic from "@posthog/ui/assets/images/logo-static.png";
import { useReducedMotion } from "framer-motion";

interface AnimatedLogoProps {
  size?: number;
  className?: string;
}

export function AnimatedLogo({ size = 96, className }: AnimatedLogoProps) {
  const reducedMotion = useReducedMotion();
  return (
    <img
      src={reducedMotion ? logoStatic : logoLoading}
      alt=""
      data-testid="app-loading-logo"
      width={size}
      height={size}
      draggable={false}
      className={cn("pointer-events-none select-none", className)}
    />
  );
}
