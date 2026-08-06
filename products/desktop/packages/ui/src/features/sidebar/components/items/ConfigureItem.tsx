import { SlidersHorizontal } from "@phosphor-icons/react";
import { SidebarItem } from "../SidebarItem";

interface ConfigureItemProps {
  onClick: () => void;
  depth?: number;
}

export function ConfigureItem({ onClick, depth = 0 }: ConfigureItemProps) {
  return (
    <SidebarItem
      depth={depth}
      icon={<SlidersHorizontal size={16} />}
      label="Configure"
      onClick={onClick}
    />
  );
}
