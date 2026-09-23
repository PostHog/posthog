import { cn } from "@posthog/quill";
import { LoaderCircle } from "lucide-react";
import type { ComponentProps } from "react";

interface SpinProps extends ComponentProps<"span"> {
  spinning?: boolean;
}

// Chromium animates transforms on <svg> elements on the main thread, which costs a style
// recalc and layerize pass every frame; on an HTML wrapper the compositor runs it for free.
export function Spin({
  spinning = true,
  className,
  children,
  ...props
}: SpinProps) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0",
        spinning && "animate-spin motion-reduce:animate-none",
        className,
      )}
      {...props}
    >
      {children}
    </span>
  );
}

export type SpinnerSize = "xs" | "sm" | "md" | "lg";

const SIZE_CLASS: Record<SpinnerSize, string> = {
  xs: "size-2.5",
  sm: "size-3",
  md: "size-4",
  lg: "size-6",
};

interface SpinnerProps extends Omit<ComponentProps<"span">, "children"> {
  size?: SpinnerSize;
  spinning?: boolean;
  label?: string;
}

// Quill buttons and media slots size an svg that has no `size-*` class to match the
// icons beside it, so the default leaves the class off and falls back to 16px through
// the width and height attributes.
export function Spinner({
  size,
  spinning,
  label = "Loading",
  ...props
}: SpinnerProps) {
  return (
    <Spin spinning={spinning} role="status" aria-label={label} {...props}>
      <LoaderCircle
        size={16}
        aria-hidden="true"
        className={size && SIZE_CLASS[size]}
      />
    </Spin>
  );
}
