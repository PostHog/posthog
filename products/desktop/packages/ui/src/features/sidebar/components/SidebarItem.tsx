import {
  Button,
  cn,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import type { SidebarItemAction } from "@posthog/ui/features/sidebar/types";
import {
  OverflowTickerText,
  useOverflowTickerReveal,
} from "@posthog/ui/primitives/OverflowTickerText";
import { type ComponentPropsWithRef, useCallback } from "react";

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

function SidebarItemLabel({
  label,
  grow,
  className,
}: {
  label: React.ReactNode;
  grow: boolean;
  className?: string;
}) {
  const canTooltip = typeof label === "string" || typeof label === "number";

  const measureRef = useCallback((el: HTMLSpanElement | null) => {
    if (!el) return;
    const update = () => {
      el.style.pointerEvents = el.scrollWidth > el.clientWidth ? "" : "none";
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const span = (
    <span
      ref={measureRef}
      className={cn("min-w-0 truncate", grow && "flex-1", className)}
    >
      {label}
    </span>
  );

  if (!canTooltip) return span;

  return (
    <TooltipProvider delay={600}>
      <Tooltip>
        <TooltipTrigger render={span} />
        <TooltipContent side="top" className="max-w-[900px] break-words">
          {label}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
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
        // Quill's Button pins a fixed single-line height that would clip the second line.
        subtitle && "h-auto! min-h-7 py-1",
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
          <SidebarItemLabel
            label={subtitle}
            grow={false}
            className="text-[11px] text-gray-10 leading-tight group-data-active:text-gray-11"
          />
        ) : null}
      </span>
    </Button>
  );
}
