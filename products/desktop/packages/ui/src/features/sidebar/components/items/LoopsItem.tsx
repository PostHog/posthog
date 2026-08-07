import { Badge } from "@posthog/quill";
import { LoopIcon } from "@posthog/ui/primitives/LoopIcon";
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
      icon={<LoopIcon size={16} weight={isActive ? "fill" : "regular"} />}
      label="Loops"
      badge={<Badge variant="info">Alpha</Badge>}
      isActive={isActive}
      onClick={onClick}
    />
  );
}
