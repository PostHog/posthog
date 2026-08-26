import { LifebuoyIcon } from "@phosphor-icons/react";
import { Badge } from "@posthog/quill";
import type { MouseEventHandler } from "react";
import { SidebarItem } from "../SidebarItem";
import { SidebarCountBadge } from "./SidebarCountBadge";

interface SupportItemProps {
  isActive: boolean;
  onClick: MouseEventHandler<Element>;
  openCount?: number;
  depth?: number;
}

export function SupportItem({
  isActive,
  onClick,
  openCount = 0,
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
            count={openCount}
            title={`${openCount} open tickets assigned to you`}
          />
        </>
      }
      badge={<Badge variant="info">Alpha</Badge>}
      isActive={isActive}
      onClick={onClick}
    />
  );
}
