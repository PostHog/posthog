import { Lightning } from "@phosphor-icons/react";
import { SidebarItem } from "../SidebarItem";

interface CommandCenterItemProps {
  isActive: boolean;
  onClick: () => void;
  activeCount?: number;
  depth?: number;
}

function formatActiveCount(count: number): string {
  if (count > 99) return "99+";
  return String(count);
}

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
      endContent={
        activeCount && activeCount > 0 ? (
          <span
            className="inline-flex h-[16px] min-w-[16px] items-center justify-center rounded-full px-1 text-[11px] text-gray-11 leading-none"
            title={`${activeCount} active`}
          >
            {formatActiveCount(activeCount)}
          </span>
        ) : undefined
      }
    />
  );
}
