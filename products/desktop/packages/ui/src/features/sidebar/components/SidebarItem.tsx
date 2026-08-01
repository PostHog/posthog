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
  endContent?: React.ReactNode;
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
  disabled,
  ref,
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
        "disabled:opacity-100 data-active:bg-fill-selected data-selected:bg-(--gray-3)",
        isDimmed && "opacity-50",
      )}
      data-active={isActive || undefined}
      data-selected={(isSelected && !isActive) || undefined}
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
        </span>
        {subtitle ? (
          <span className="truncate text-gray-10 group-data-active:text-gray-11">
            {subtitle}
          </span>
        ) : null}
      </span>
    </Button>
  );
}
