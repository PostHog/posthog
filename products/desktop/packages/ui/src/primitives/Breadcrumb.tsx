import { Button, cn, Text } from "@posthog/quill";
import type { ReactElement, ReactNode } from "react";

/**
 * One segment of the breadcrumb. Always a Button, so every segment carries the
 * same padding, height and icon gap whether or not it goes anywhere — the leaf
 * used to be bare text, which left it visually adrift from its siblings.
 *
 * Without `onClick` or `render` the segment is genuinely inert: `aria-disabled`
 * (so quill drops the hover fill and assistive tech reads it as unavailable)
 * plus `pointer-events-none`, and out of the tab order. The disabled dimming is
 * overridden — a breadcrumb has to stay readable.
 */
export function BreadcrumbSegment({
  icon,
  label,
  strong,
  muted,
  shrink,
  onClick,
  render,
  contextMenu = false,
  className,
  ...rest
}: {
  icon?: ReactNode;
  label: string;
  /** The leaf gives up width first, since it carries the longest name. */
  shrink?: boolean;
  /** The root segment carries the space name, which reads heavier. */
  strong?: boolean;
  /** The leaf is the current page, so it sits back from the linked segments. */
  muted?: boolean;
  /** Navigates, or (on a renamable leaf) opens the inline editor. */
  onClick?: () => void;
  render?: ReactElement;
  contextMenu?: boolean;
  className?: string;
}) {
  const interactive = Boolean(onClick) || Boolean(render);

  return (
    <Button
      {...rest}
      {...(render ? { render } : { type: "button" as const })}
      size="sm"
      aria-disabled={interactive ? undefined : true}
      tabIndex={interactive ? undefined : -1}
      onClick={onClick}
      className={cn(
        "no-drag min-w-0",
        // `shrink` beats quill's own `shrink-0`. Only the leaf takes it: a
        // segment that cannot shrink keeps its full width in a row that has
        // run out, and paints its label over the marks after it. The fixed
        // segments stay whole, so a long session name is what gives.
        shrink && "shrink",
        // Live segments (a link, or a click-to-rename leaf) behave like
        // any other button: pointer cursor and hover fill. Inert ones read as
        // plain text — full opacity, ordinary cursor, and no hover (quill's
        // hover rules already skip aria-disabled) — and leave the tab order.
        interactive || contextMenu
          ? "cursor-pointer!"
          : "pointer-events-none cursor-default! opacity-100!",
        className,
      )}
    >
      {icon && (
        <span className="flex shrink-0 text-muted-foreground/80">{icon}</span>
      )}
      {/* No `title`: the native tooltip duplicated the styled one, and on the
          fixed segments there was nothing worth revealing. */}
      <Text
        className={cn(
          "min-w-0 truncate whitespace-nowrap text-[13px]",
          strong && "font-medium",
          muted && "text-muted-foreground",
        )}
      >
        {label}
      </Text>
    </Button>
  );
}

export function BreadcrumbSeparator() {
  return (
    <Text className="shrink-0 text-[13px] text-muted-foreground/20">/</Text>
  );
}
