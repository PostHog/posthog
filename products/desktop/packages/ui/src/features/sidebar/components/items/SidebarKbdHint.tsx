import { Kbd } from "@posthog/quill";
import { formatHotkey } from "@posthog/ui/features/command/keyboard-shortcuts";

interface SidebarKbdHintProps {
  /** Raw shortcut string from SHORTCUTS, e.g. "mod+k". */
  keys: string;
}

/**
 * Keyboard shortcut hint for a sidebar nav item. Hidden until the parent
 * SidebarItem (which carries the `group` class) is hovered. Toggled via
 * `display` so it takes no space when idle and preceding `endContent` sits
 * flush to the edge — no transition, to match the rest of the sidebar.
 */
export function SidebarKbdHint({ keys }: SidebarKbdHintProps) {
  return (
    <Kbd className="hidden whitespace-nowrap group-hover:inline-flex">
      {formatHotkey(keys)}
    </Kbd>
  );
}
