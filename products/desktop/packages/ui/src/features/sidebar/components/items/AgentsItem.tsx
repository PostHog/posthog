import { Robot } from "@phosphor-icons/react";
import { SidebarItem } from "../SidebarItem";

interface AgentsItemProps {
  isActive: boolean;
  onClick: () => void;
  depth?: number;
}

export function AgentsItem({ isActive, onClick, depth = 0 }: AgentsItemProps) {
  return (
    <SidebarItem
      depth={depth}
      icon={<Robot size={16} weight={isActive ? "fill" : "regular"} />}
      label="Agents"
      isActive={isActive}
      onClick={onClick}
    />
  );
}
