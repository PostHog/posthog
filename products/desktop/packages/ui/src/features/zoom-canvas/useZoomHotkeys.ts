import { hasOpenOverlay } from "@posthog/ui/utils/overlay";
import { useHotkeys } from "react-hotkeys-hook";
import { SHORTCUTS } from "../command/keyboard-shortcuts";
import type { ZoomDirection, ZoomNavigation } from "./useZoomNavigation";

/** Where a keystroke means text, not movement. */
function isEditableTarget(): boolean {
  const element = document.activeElement;
  if (!(element instanceof HTMLElement)) return false;
  return (
    element instanceof HTMLInputElement ||
    element instanceof HTMLTextAreaElement ||
    element.isContentEditable
  );
}

const ARROW_DIRECTIONS: Record<string, ZoomDirection> = {
  left: "left",
  right: "right",
  up: "up",
  down: "down",
};

/**
 * The camera's keyboard. Bare arrows move the selection only while zoomed out,
 * so inside a session they still belong to the chat; the modified keys work at
 * every zoom level.
 */
export function useZoomHotkeys(navigation: ZoomNavigation): void {
  const zoomedOut = navigation.zoom !== "session";

  useHotkeys(
    "escape",
    (event) => {
      if (hasOpenOverlay()) return;
      // Focus in the composer means the first Escape blurs it (useBlurOnEscape);
      // the camera answers the next one.
      if (isEditableTarget()) return;
      event.preventDefault();
      navigation.stepOut();
    },
    { enableOnFormTags: true, enableOnContentEditable: true },
    [navigation],
  );

  useHotkeys(
    "enter",
    (event) => {
      if (hasOpenOverlay()) return;
      if (!zoomedOut) return;
      event.preventDefault();
      navigation.stepIn();
    },
    [navigation, zoomedOut],
  );

  useHotkeys(
    ["left", "right", "up", "down"],
    (event, handler) => {
      if (hasOpenOverlay()) return;
      if (!zoomedOut) return;
      const direction = ARROW_DIRECTIONS[handler.keys?.[0] ?? ""];
      if (!direction) return;
      event.preventDefault();
      navigation.move(direction);
    },
    [navigation, zoomedOut],
  );

  useHotkeys(
    ["alt+left", "alt+right"],
    (event, handler) => {
      if (hasOpenOverlay()) return;
      const direction = ARROW_DIRECTIONS[handler.keys?.[0] ?? ""];
      if (!direction) return;
      event.preventDefault();
      navigation.move(direction);
    },
    { enableOnFormTags: true, enableOnContentEditable: true },
    [navigation],
  );

  // Rows reuse the app's existing newer/older-task keys (⌘↑ / ⌘↓) rather than
  // inventing a second pair for the same idea.
  useHotkeys(
    [SHORTCUTS.SPACE_UP, SHORTCUTS.SPACE_DOWN],
    (event, handler) => {
      if (hasOpenOverlay()) return;
      const direction = ARROW_DIRECTIONS[handler.keys?.[0] ?? ""];
      if (!direction) return;
      event.preventDefault();
      navigation.move(direction);
    },
    { enableOnFormTags: true, enableOnContentEditable: true },
    [navigation],
  );

  useHotkeys(
    "alt+n",
    (event) => {
      if (hasOpenOverlay()) return;
      event.preventDefault();
      navigation.goToNextAttention();
    },
    { enableOnFormTags: true, enableOnContentEditable: true },
    [navigation],
  );
}
