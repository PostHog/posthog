import { Button, cn } from "@posthog/quill";
import type { SidebarItemAction } from "@posthog/ui/features/sidebar/types";
import {
  OverflowTickerText,
  useOverflowTickerReveal,
} from "@posthog/ui/primitives/OverflowTickerText";
import type { ComponentPropsWithRef } from "react";

export const INDENT_SIZE = 8;

export function getSidebarItemPaddingLeft(depth: number): string {
  return `${depth * INDENT_SIZE + 8 + (depth > 0 ? 4 : 0)}px`;
}

interface SidebarItemProps
  extends Omit<
    ComponentPropsWithRef<"button">,
    "children" | "onDragStart" | "onDoubleClick"
  > {
  depth: number;
  icon?: React.ReactNode;
  label: React.ReactNode;
  subtitle?: React.ReactNode;
  isActive?: boolean;
  isSelected?: boolean;
  isDimmed?: boolean;
  draggable?: boolean;
  onDragStart?: (e: React.DragEvent) => void;
  onClick?: (e: React.MouseEvent) => void;
  onDoubleClick?: () => void;
  onContextMenu?: (e: React.MouseEvent) => void;
  action?: SidebarItemAction;
  /** Hugs the label but never truncates with it; pushes endContent right. */
  badge?: React.ReactNode;
  /**
   * Trailing controls — hover toolbars, avatars, spinners, status badges. They
   * sit flush with the row's edge, because an icon-sized control carries its
   * own padding and reads as inset twice over if the row adds more.
   */
  endContent?: React.ReactNode;
  /**
   * Trailing text — a shortcut hint, a count. Unlike a control it has no
   * padding of its own, so the row gives it the gap from the edge. Rendered
   * outside `endContent`, i.e. rightmost.
   */
  endHint?: React.ReactNode;
  disabled?: boolean;
}

export function SidebarItem({
  depth,
  icon,
  label,
  subtitle,
  isActive,
  isSelected,
  isDimmed,
  draggable,
  onDragStart,
  onClick,
  onDoubleClick,
  onContextMenu,
  badge,
  endContent,
  endHint,
  disabled,
  ref,
  className,
  ...buttonProps
}: SidebarItemProps) {
  const { reveal, hoverProps, focusProps } = useOverflowTickerReveal();

  return (
    <Button
      {...buttonProps}
      ref={ref}
      type="button"
      className={cn(
        "group flex w-full cursor-default text-left text-[13px] leading-snug transition-colors",
        "disabled:opacity-100",
        // A second row outgrows the button's fixed height, and the overflow
        // lands on the row below it. The padding stands in for the height the
        // row gives up.
        subtitle && "h-auto py-1",
        // The open row keeps its neutral background on its own, and takes the
        // accent only once it is part of a selection, a shade above the rows
        // picked around it.
        isActive && (isSelected ? "bg-primary/20" : "bg-fill-selected"),
        !isActive && isSelected && "bg-primary/10",
        // A bar on the leading edge rather than another background: the open
        // session already owns its background, and this lets it also say it is
        // part of a bulk selection.
        "relative data-in-selection:before:absolute data-in-selection:before:inset-y-0 data-in-selection:before:left-0 data-in-selection:before:w-0.5 data-in-selection:before:bg-primary data-in-selection:before:content-['']",
        isDimmed && "opacity-50",
        // Last, so a caller can override the row's cursor-default — the
        // spread above sits before this prop and would otherwise drop it.
        className,
      )}
      data-active={isActive || undefined}
      data-in-selection={isSelected || undefined}
      draggable={draggable}
      onDragStart={onDragStart}
      style={{
        paddingLeft: getSidebarItemPaddingLeft(depth),
        paddingRight: "4px",
      }}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onContextMenu={onContextMenu}
      {...hoverProps}
      {...focusProps}
      disabled={disabled}
    >
      {icon ? (
        <span className="flex shrink-0 items-center opacity-80 group-data-active:opacity-100">
          {icon}
        </span>
      ) : null}
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="flex min-h-[18px] items-center gap-1">
          <OverflowTickerText
            reveal={reveal}
            className={cn(!badge && "flex-1")}
          >
            {label}
          </OverflowTickerText>
          {badge ? (
            <span className="mr-auto ml-1 flex shrink-0 items-center">
              {badge}
            </span>
          ) : null}
          {endContent}
          {endHint ? (
            <span className="flex shrink-0 items-center pr-1">{endHint}</span>
          ) : null}
        </span>
        {subtitle ? (
          <span className="truncate text-muted-foreground/70 text-xxs group-data-active:text-muted-foreground">
            {subtitle}
          </span>
        ) : null}
      </span>
    </Button>
  );
}
