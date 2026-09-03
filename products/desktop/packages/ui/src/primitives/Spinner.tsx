import { type IconProps, Spinner as SpinnerIcon } from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
import type { ReactNode } from "react";

interface SpinProps {
  spinning?: boolean;
  className?: string;
  children: ReactNode;
}

// Chromium animates transforms on <svg> elements on the main thread, which costs a style
// recalc and layerize pass every frame; on an HTML wrapper the compositor runs it for free.
export function Spin({ spinning = true, className, children }: SpinProps) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0",
        spinning && "animate-spin",
        className,
      )}
    >
      {children}
    </span>
  );
}

interface SpinnerProps extends IconProps {
  spinning?: boolean;
}

export function Spinner({ spinning, className, ...iconProps }: SpinnerProps) {
  return (
    <Spin spinning={spinning} className={className}>
      <SpinnerIcon {...iconProps} />
    </Spin>
  );
}
