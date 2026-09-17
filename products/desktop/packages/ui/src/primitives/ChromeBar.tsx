import { cn } from "@posthog/quill";
import type { ReactElement, ReactNode } from "react";

/** A leading button carries its own padding; leading text does not. */
type ChromeBarInset = "control" | "text" | "even";

const INSET_CLASS: Record<ChromeBarInset, string> = {
  control: "pr-2 pl-1",
  text: "pr-2 pl-3",
  even: "px-3",
};

/**
 * The bar across the top of a pane, a column, or a side panel. Every such bar
 * in the app is this one, so they stay the same height and colour.
 *
 * `actions` is what reaches the far end. Children spread instead only look
 * right-aligned while the title is long enough to push them.
 */
export function ChromeBar({
  children,
  actions,
  inset = "text",
  className,
}: {
  children?: ReactNode;
  actions?: ReactNode;
  inset?: ChromeBarInset;
  className?: string;
}): ReactElement {
  return (
    <div
      className={cn(
        "flex h-10 shrink-0 items-center gap-2 border-border border-b",
        INSET_CLASS[inset],
        className,
      )}
    >
      {children}
      {actions && (
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {actions}
        </div>
      )}
    </div>
  );
}
