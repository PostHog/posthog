import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { hasOpenOverlay } from "@posthog/ui/utils/overlay";
import { useHotkeys } from "react-hotkeys-hook";

export function useBlurOnEscape() {
  useHotkeys(
    SHORTCUTS.BLUR,
    () => {
      if (hasOpenOverlay()) return;
      if (document.activeElement instanceof HTMLElement) {
        document.activeElement.blur();
      }
    },
    { enableOnFormTags: true, enableOnContentEditable: true },
  );

  useHotkeys(
    SHORTCUTS.SUBMIT_BLUR,
    () => {
      if (document.activeElement instanceof HTMLElement) {
        document.activeElement.blur();
      }
    },
    { enableOnFormTags: true, enableOnContentEditable: true },
  );
}
