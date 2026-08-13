import { GearSix } from "@phosphor-icons/react";
import { SidebarItem } from "../SidebarItem";

interface ConfigureItemProps {
  onClick: () => void;
  depth?: number;
}

export function ConfigureItem({ onClick, depth = 0 }: ConfigureItemProps) {
  return (
    <SidebarItem
      depth={depth}
      icon={<GearSix size={16} />}
      label="Settings"
      onClick={onClick}
    />
  );
}
