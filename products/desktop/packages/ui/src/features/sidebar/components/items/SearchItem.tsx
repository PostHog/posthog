import { MagnifyingGlass } from "@phosphor-icons/react";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import type { MouseEventHandler } from "react";
import { SidebarItem } from "../SidebarItem";
import { SidebarKbdHint } from "./SidebarKbdHint";

interface SearchItemProps {
  onClick: MouseEventHandler<Element>;
  depth?: number;
}

export function SearchItem({ onClick, depth = 0 }: SearchItemProps) {
  return (
    <SidebarItem
      depth={depth}
      icon={<MagnifyingGlass size={16} />}
      label="Search"
      onClick={onClick}
      endHint={<SidebarKbdHint keys={SHORTCUTS.COMMAND_MENU} />}
    />
  );
}
