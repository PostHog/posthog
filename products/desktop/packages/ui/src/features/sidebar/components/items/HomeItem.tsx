import { HouseIcon } from "@phosphor-icons/react";
import { SidebarItem } from "../SidebarItem";

interface HomeItemProps {
  isActive: boolean;
  onClick: () => void;
  depth?: number;
}

export function HomeItem({ isActive, onClick, depth = 0 }: HomeItemProps) {
  return (
    <SidebarItem
      depth={depth}
      icon={<HouseIcon size={16} weight={isActive ? "fill" : "regular"} />}
      label="Home"
      isActive={isActive}
      onClick={onClick}
    />
  );
}
