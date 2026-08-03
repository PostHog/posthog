import { Lightning } from "@phosphor-icons/react";
import { CountBadge } from "@posthog/ui/primitives/CountBadge";
import { SidebarItem } from "../SidebarItem";

interface CommandCenterItemProps {
  isActive: boolean;
  onClick: () => void;
  activeCount?: number;
  depth?: number;
}

// A trailing count in a sidebar row rather than a notification pill: no fill,
// so it sits on the row's own background.
const ROW_COUNT_CLASS =
  "h-[16px] min-w-[16px] w-auto bg-transparent px-1 font-normal text-[11px] text-gray-11";

export function CommandCenterItem({
  isActive,
  onClick,
  activeCount,
  depth = 0,
}: CommandCenterItemProps) {
  return (
    <SidebarItem
      depth={depth}
      icon={<Lightning size={16} weight={isActive ? "fill" : "regular"} />}
      label="Command Center"
      isActive={isActive}
      onClick={onClick}
      // CountBadge renders nothing at zero, so no guard is needed here.
      endContent={
        <CountBadge
          count={activeCount ?? 0}
          tone="neutral"
          className={ROW_COUNT_CLASS}
          title={`${activeCount} active`}
        />
      }
    />
  );
}
