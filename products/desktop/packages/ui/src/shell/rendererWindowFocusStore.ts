import { create } from "zustand";

/**
 * True when the renderer document is visible and the window has OS focus.
 * Used to pause inbox polling when the Electron window is in the background.
 */
function computeWindowFocused(): boolean {
  if (typeof document === "undefined") {
    return false;
  }
  return document.visibilityState === "visible" && document.hasFocus();
}

export const useRendererWindowFocusStore = create<{ focused: boolean }>(() => ({
  focused: typeof document !== "undefined" ? computeWindowFocused() : false,
}));

let listenersAttached = false;

function ensureWindowFocusListeners(): void {
  if (typeof window === "undefined" || listenersAttached) {
    return;
  }
  listenersAttached = true;

  const sync = (): void => {
    useRendererWindowFocusStore.setState({ focused: computeWindowFocused() });
  };

  window.addEventListener("focus", sync);
  window.addEventListener("blur", sync);
  document.addEventListener("visibilitychange", sync);
}

ensureWindowFocusListeners();
