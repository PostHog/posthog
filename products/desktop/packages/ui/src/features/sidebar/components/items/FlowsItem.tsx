import { FlowArrowIcon } from "@phosphor-icons/react";
import type { MouseEventHandler } from "react";
import { SidebarItem } from "../SidebarItem";

interface FlowsItemProps {
  isActive: boolean;
  onClick: MouseEventHandler<Element>;
  depth?: number;
}

export function FlowsItem({ isActive, onClick, depth = 0 }: FlowsItemProps) {
  return (
    <SidebarItem
      depth={depth}
      icon={<FlowArrowIcon size={16} weight={isActive ? "fill" : "regular"} />}
      label="Flows"
      isActive={isActive}
      onClick={onClick}
    />
  );
}
