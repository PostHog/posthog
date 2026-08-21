import { SidebarSimpleIcon } from "@phosphor-icons/react";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { IconButton } from "@radix-ui/themes";
import type React from "react";

export const SidebarTrigger: React.FC = () => {
  const toggle = useSidebarStore((state) => state.toggle);

  return (
    <Tooltip
      content="Toggle left sidebar"
      shortcut={formatHotkey(SHORTCUTS.TOGGLE_LEFT_SIDEBAR)}
      side="bottom"
    >
      <IconButton
        variant="ghost"
        color="gray"
        onClick={toggle}
        className="no-drag"
      >
        <SidebarSimpleIcon size={16} />
      </IconButton>
    </Tooltip>
  );
};
