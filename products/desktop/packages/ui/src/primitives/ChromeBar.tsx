import { cn } from "@posthog/quill";
import type { ReactElement, ReactNode } from "react";

/** A leading button carries its own padding; leading text does not. */
type ChromeBarInset = "control" | "text" | "even" | "title";

/**
 * How far a pane holds its contents off its left edge. The pane title bar
 * (`inset="title"`) and the body under it share this one value, so a title
 * starts on the same line as the page it names.
 */
export const PANE_INSET = "px-6";

/**
 * A leading quill `size="sm"` button carries 8px of its own padding, which
 * puts its glyph 8px right of the bar's inset. Content that starts with such a
 * button pulls that padding back, so every title starts on the inset whether
 * it is a breadcrumb or plain text.
 */
export const LEADING_BUTTON_PULL = "-ml-2";

const INSET_CLASS: Record<ChromeBarInset, string> = {
  control: "pr-2 pl-1",
  text: "pr-2 pl-3",
  even: "px-3",
  title: "pr-2 pl-6",
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
