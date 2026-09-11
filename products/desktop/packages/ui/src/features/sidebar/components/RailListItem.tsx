import { AutocompleteItem, Button, cn } from "@posthog/quill";
import type { ComponentProps, ReactElement, ReactNode } from "react";

/**
 * Names the rail as a container so its rows can size themselves to it. Put it
 * on the sidebar column that holds the Self-driving, Activity, and space
 * lists; the rows' `@sm/rail:` and `@lg/rail:` variants resolve against it.
 */
export const RAIL_CONTAINER_CLASS = "@container/rail";

/**
 * How many lines the detail row keeps by rail width. One at the default width,
 * two once the reader has widened the rail past 384px, three past 512px.
 */
export const RAIL_DETAIL_CLAMP_CLASS =
  "line-clamp-1 @sm/rail:line-clamp-2 @lg/rail:line-clamp-3";

/** Hidden until the row is hovered or focused; opens stay visible while open. */
export const RAIL_HOVER_ACTIONS_CLASS =
  "opacity-0 transition-opacity focus-within:opacity-100 group-hover/rail-item:opacity-100 group-focus-within/rail-item:opacity-100 has-[[data-popup-open]]:opacity-100";

// The actions overlay the row (a button cannot hold other buttons), so the
// text lanes stop short of them by how many the row shows.
const ACTION_LANE_CLASS = ["", "pr-8", "pr-14", "pr-20"];

export interface RailListItemProps
  extends Omit<ComponentProps<typeof Button>, "children" | "title"> {
  /** Avatar, monogram, or icon in the row's left column. */
  leading: ReactNode;
  title: ReactNode;
  /** Sits beside the title, for example an unread badge. */
  titleAccessory?: ReactNode;
  /** Bold title, for an unread row. */
  emphasized?: boolean;
  /** Second row: age, actor, status. One line. */
  meta?: ReactNode;
  /** Third row: last turn or description. Clamped by rail width. */
  detail?: ReactNode;
  /** Off, the detail row shows in full, for the full-page list. */
  clampDetail?: boolean;
  isSelected?: boolean;
  compact?: boolean;
  /** Renders as a keyboard-walkable option of the enclosing `Autocomplete`. */
  asOption?: boolean;
  optionValue?: string;
  /** Controls drawn over the row's right edge. */
  actions?: ReactNode;
  /** How many controls `actions` shows, so the text stops short of them. */
  actionCount?: number;
  /** Whether the actions need a hover to show. */
  actionsVisibility?: "hover" | "always";
  wrapperClassName?: string;
}

/**
 * One row of a rail list: leading mark, title, a metadata line, and a detail
 * line that grows with the rail. Sessions, Self-driving reports, and any other
 * list a rail pane draws share this shape, so a reader learns one row.
 */
export function RailListItem({
  leading,
  title,
  titleAccessory,
  emphasized = false,
  meta,
  detail,
  clampDetail = true,
  isSelected = false,
  compact = false,
  asOption = false,
  optionValue,
  actions,
  actionCount = actions ? 1 : 0,
  actionsVisibility = "hover",
  wrapperClassName,
  className,
  ...props
}: RailListItemProps): ReactElement {
  const surfaceClassName = cn(
    "h-auto w-full items-start text-left",
    compact ? "py-1.5" : "py-2",
    ACTION_LANE_CLASS[Math.min(actionCount, ACTION_LANE_CLASS.length - 1)],
    asOption &&
      "ring-offset-0 data-highlighted:border-transparent data-highlighted:bg-fill-hover data-highlighted:ring-0 [&>span]:w-full [&>span]:items-start [&>span]:gap-2",
    isSelected && "bg-fill-selected",
    className,
  );

  const body = (
    <>
      <span className="mt-0.5 shrink-0">{leading}</span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span
            className={cn(
              "truncate text-[13px]",
              emphasized ? "font-semibold" : "font-medium",
            )}
          >
            {title}
          </span>
          {titleAccessory}
        </span>
        {meta && (
          <span className="flex min-w-0 items-center gap-1 text-muted-foreground text-xxs">
            {meta}
          </span>
        )}
        {detail && (
          <span
            className={cn(
              "mt-0.5 block break-words text-[12px] text-muted-foreground leading-snug",
              clampDetail
                ? cn("whitespace-normal", RAIL_DETAIL_CLAMP_CLASS)
                : "whitespace-pre-wrap",
            )}
          >
            {detail}
          </span>
        )}
      </span>
    </>
  );

  let surface: ReactElement;
  if (asOption) {
    if (!optionValue) {
      throw new Error("Rail list options require a value");
    }
    surface = (
      <AutocompleteItem
        value={optionValue}
        nativeButton
        className={surfaceClassName}
        {...(props as ComponentProps<typeof AutocompleteItem>)}
      >
        {body}
      </AutocompleteItem>
    );
  } else {
    surface = (
      <Button type="button" left className={surfaceClassName} {...props}>
        {body}
      </Button>
    );
  }

  if (!actions) {
    return (
      <div className={cn("group/rail-item relative", wrapperClassName)}>
        {surface}
      </div>
    );
  }

  return (
    <div className={cn("group/rail-item relative", wrapperClassName)}>
      {surface}
      <div
        className={cn(
          "absolute top-1.5 right-1.5 flex items-center gap-0.5",
          actionsVisibility === "hover" && RAIL_HOVER_ACTIONS_CLASS,
        )}
      >
        {actions}
      </div>
    </div>
  );
}
