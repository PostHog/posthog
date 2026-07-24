import { RepeatIcon } from "@phosphor-icons/react";
import { Badge } from "@posthog/quill";
import { SidebarItem } from "../SidebarItem";

interface LoopsItemProps {
  isActive: boolean;
  onClick: () => void;
  depth?: number;
}

export function LoopsItem({ isActive, onClick, depth = 0 }: LoopsItemProps) {
  return (
    <SidebarItem
      depth={depth}
      icon={<RepeatIcon size={16} weight={isActive ? "fill" : "regular"} />}
      label="Loops"
      badge={<Badge variant="info">Alpha</Badge>}
      isActive={isActive}
      onClick={onClick}
    />
  );
}
