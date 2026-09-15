import { SidebarSimpleIcon } from "@phosphor-icons/react";
import { Button, Kbd } from "@posthog/quill";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { cancelSidebarPeek } from "@posthog/ui/features/sidebar/sidebarPeekStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import type { ReactElement } from "react";

/**
 * Way back to a collapsed sidebar, for the panes whose empty state tells the
 * reader to pick something from it. Renders nothing while the sidebar is on
 * screen, so the empty state keeps its one instruction.
 */
export function OpenSidebarButton(): ReactElement | null {
  const open = useSidebarStore((state) => state.open);
  const setOpen = useSidebarStore((state) => state.setOpen);
  if (open) return null;

  return (
    <Button
      variant="outline"
      size="default"
      onClick={() => {
        cancelSidebarPeek();
        setOpen(true);
      }}
    >
      <SidebarSimpleIcon />
      Open the sidebar
      <Kbd>{formatHotkey(SHORTCUTS.TOGGLE_LEFT_SIDEBAR)}</Kbd>
    </Button>
  );
}
