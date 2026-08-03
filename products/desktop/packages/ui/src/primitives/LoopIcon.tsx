import { ArrowClockwiseIcon, type IconProps } from "@phosphor-icons/react";
import { cn } from "@posthog/quill";

export function LoopIcon({ className, ...props }: IconProps) {
  return (
    <ArrowClockwiseIcon
      {...props}
      className={cn(
        "transition-transform duration-800 ease-[cubic-bezier(0.22,1,0.36,1)] motion-safe:group-hover:rotate-360 motion-safe:hover:rotate-360",
        className,
      )}
    />
  );
}
