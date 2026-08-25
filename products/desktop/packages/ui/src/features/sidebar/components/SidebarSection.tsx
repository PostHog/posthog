import { CaretDownIcon, CaretRightIcon, Plus } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { INDENT_SIZE } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import * as Collapsible from "@radix-ui/react-collapsible";
import { useState } from "react";

interface SidebarSectionProps {
  id: string;
  label: string;
  icon?: React.ReactNode;
  isExpanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  addSpacingBefore?: boolean;
  onContextMenu?: (e: React.MouseEvent) => void;
  tooltipContent?: string;
  onNewTask?: () => void;
  newTaskTooltip?: string;
  dragHandleRef?: React.RefCallback<HTMLButtonElement>;
  /** Indents the header for sections nested inside another section. */
  depth?: number;
}

export function SidebarSection({
  label,
  icon,
  isExpanded,
  onToggle,
  children,
  addSpacingBefore,
  onContextMenu,
  tooltipContent,
  onNewTask,
  newTaskTooltip,
  dragHandleRef,
  depth,
}: SidebarSectionProps) {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <Collapsible.Root open={isExpanded} onOpenChange={onToggle}>
      <Collapsible.Trigger asChild>
        <Button
          ref={dragHandleRef}
          type="button"
          className="flex w-full items-center justify-between pl-2 not-hover:aria-expanded:bg-transparent"
          style={{
            marginTop: addSpacingBefore ? "12px" : undefined,
            // + 8 matches the base pl-2 padding set via className below.
            paddingLeft: depth ? `${depth * INDENT_SIZE + 8}px` : undefined,
          }}
          onContextMenu={onContextMenu}
          onMouseEnter={() => setIsHovered(true)}
          onMouseLeave={() => setIsHovered(false)}
        >
          <span className="flex min-w-0 flex-1 items-center gap-[4px]">
            {icon && (
              <span className="flex h-[18px] w-[18px] shrink-0 items-center justify-center text-gray-10">
                {isHovered ? (
                  isExpanded ? (
                    <CaretDownIcon size={12} />
                  ) : (
                    <CaretRightIcon size={12} />
                  )
                ) : (
                  icon
                )}
              </span>
            )}
            {tooltipContent ? (
              <Tooltip content={tooltipContent} side="right" align="start">
                <span className="overflow-hidden text-ellipsis whitespace-nowrap font-medium">
                  {label}
                </span>
              </Tooltip>
            ) : (
              <span className="overflow-hidden text-ellipsis whitespace-nowrap font-medium">
                {label}
              </span>
            )}
          </span>
          <span className="flex shrink-0 items-center gap-1 text-gray-10">
            {onNewTask && isHovered && (
              <Tooltip content={newTaskTooltip ?? "Start new task"} side="left">
                {/* biome-ignore lint/a11y/useSemanticElements: Cannot use button inside parent button (Collapsible.Trigger) */}
                <span
                  role="button"
                  tabIndex={0}
                  className="flex h-[18px] w-[18px] items-center justify-center rounded-sm border-0 bg-transparent p-0 hover:bg-gray-3"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    onNewTask();
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      e.stopPropagation();
                      onNewTask();
                    }
                  }}
                >
                  <Plus size={12} />
                </span>
              </Tooltip>
            )}
          </span>
        </Button>
      </Collapsible.Trigger>
      <Collapsible.Content>{children}</Collapsible.Content>
    </Collapsible.Root>
  );
}
