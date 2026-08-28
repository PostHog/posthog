import { Lightbulb } from "@phosphor-icons/react";
import { SidebarItem } from "../SidebarItem";

interface SkillsItemProps {
  isActive: boolean;
  onClick: () => void;
  depth?: number;
}

export function SkillsItem({ isActive, onClick, depth = 0 }: SkillsItemProps) {
  return (
    <SidebarItem
      depth={depth}
      icon={<Lightbulb size={16} weight={isActive ? "fill" : "regular"} />}
      label="Skills"
      isActive={isActive}
      onClick={onClick}
    />
  );
}
