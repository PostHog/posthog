import { Kbd } from "@posthog/quill";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";

/**
 * What the nav's resize grip says. The nav is the one panel with a key of its
 * own, and someone reaching for the edge to make it narrower is often after the
 * room, not the width - so the tooltip that explains the drag also offers the
 * shorter way to the same thing.
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
