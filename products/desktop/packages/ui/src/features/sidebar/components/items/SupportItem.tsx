import { LifebuoyIcon } from "@phosphor-icons/react";
import { Badge } from "@posthog/quill";
import { SidebarItem } from "../SidebarItem";

interface SupportItemProps {
  isActive: boolean;
  onClick: () => void;
  depth?: number;
}

export function SupportItem({
  isActive,
  onClick,
  depth = 0,
}: SupportItemProps) {
  return (
    <SidebarItem
      depth={depth}
      icon={<LifebuoyIcon size={16} weight={isActive ? "fill" : "regular"} />}
      label="Support"
      badge={<Badge variant="info">Alpha</Badge>}
      isActive={isActive}
      onClick={onClick}
    />
  );
}
