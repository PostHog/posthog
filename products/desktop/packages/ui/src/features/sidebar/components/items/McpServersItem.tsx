import { Plugs } from "@phosphor-icons/react";
import { SidebarItem } from "../SidebarItem";

interface McpServersItemProps {
  isActive: boolean;
  onClick: () => void;
  depth?: number;
}

export function McpServersItem({
  isActive,
  onClick,
  depth = 0,
}: McpServersItemProps) {
  return (
    <SidebarItem
      depth={depth}
      icon={<Plugs size={16} weight={isActive ? "fill" : "regular"} />}
      label="MCP servers"
      isActive={isActive}
      onClick={onClick}
    />
  );
}
