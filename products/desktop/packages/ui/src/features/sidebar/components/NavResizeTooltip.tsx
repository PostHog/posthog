import { Kbd } from "@posthog/quill";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";

/**
 * Someone reaching for the nav's edge is often after the room, not the width, so
 * the grip's tooltip offers the shorter way to the same thing.
 */
export function NavResizeTooltip() {
  return (
    <>
      Resize
      <span className="flex items-center gap-1 text-background/70">
        <Kbd>{formatHotkey(SHORTCUTS.TOGGLE_LEFT_SIDEBAR)}</Kbd>
        to toggle
      </span>
    </>
  );
}
