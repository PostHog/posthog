import { LifebuoyIcon } from "@phosphor-icons/react";
import { Badge } from "@posthog/quill";
import { SidebarItem } from "../SidebarItem";
import { SidebarCountBadge } from "./SidebarCountBadge";

interface SupportItemProps {
  isActive: boolean;
  onClick: () => void;
  unreadCount?: number;
  depth?: number;
}

export function SupportItem({
  isActive,
  onClick,
  unreadCount = 0,
  depth = 0,
}: SupportItemProps) {
  return (
    <SidebarItem
      depth={depth}
      icon={<LifebuoyIcon size={16} weight={isActive ? "fill" : "regular"} />}
      label={
        <>
          Support
          <SidebarCountBadge
            count={unreadCount}
            title={`${unreadCount} tickets with unread replies`}
          />
        </>
      }
      badge={<Badge variant="info">Alpha</Badge>}
      isActive={isActive}
      onClick={onClick}
    />
  );
}
