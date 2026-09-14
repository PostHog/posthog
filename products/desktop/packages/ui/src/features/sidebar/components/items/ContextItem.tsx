import { BookOpenTextIcon } from "@phosphor-icons/react";
import type { MouseEventHandler } from "react";
import { SidebarItem } from "../SidebarItem";

interface ContextItemProps {
  isActive: boolean;
  onClick: MouseEventHandler<Element>;
  depth?: number;
}

export function ContextItem({
  isActive,
  onClick,
  depth = 0,
}: ContextItemProps) {
  return (
    <SidebarItem
      depth={depth}
      icon={
        <BookOpenTextIcon size={16} weight={isActive ? "fill" : "regular"} />
      }
      label="Context"
      isActive={isActive}
      onClick={onClick}
    />
  );
}
