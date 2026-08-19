import { useEffect, useRef } from "react";

export const PEEK_REVEAL_THRESHOLD = 24;
export const PEEK_CLOSE_MARGIN = 64;
// An abandoned window (pointer left, or focus moved to another app) closes the
// peek on a timer rather than instantly: quick enough that it's gone when the
// user looks back, slow enough that crossing the window edge or switching apps
// never reads as the peek glitching shut.
export const PEEK_ABANDON_CLOSE_DELAY_MS = 5000;

export function shouldRevealOnEdge({
  pointer,
  wasInside,
  threshold,
}: {
  pointer: number;
  wasInside: boolean;
  threshold: number;
}): boolean {
  return pointer <= threshold && !wasInside;
}

export function shouldCloseOnExit({
  pointer,
  width,
  margin,
}: {
  pointer: number;
  width: number;
  margin: number;
}): boolean {
  return pointer > width + margin;
}

interface UseSidebarEdgeHoverPeekOptions {
  enabled: boolean;
  peeked: boolean;
  side: "left" | "right";
  width: number;
  onReveal: () => void;
  onClose: () => void;
}

export function useSidebarEdgeHoverPeek({
  enabled,
  peeked,
  side,
  width,
  onReveal,
  onClose,
}: UseSidebarEdgeHoverPeekOptions): void {
  const stateRef = useRef({ enabled, peeked, side, width, onReveal, onClose });
  stateRef.current = { enabled, peeked, side, width, onReveal, onClose };

  useEffect(() => {
    let wasInside = false;
    let abandonCloseTimer: ReturnType<typeof setTimeout> | null = null;

    const cancelAbandonClose = () => {
      if (abandonCloseTimer) {
        clearTimeout(abandonCloseTimer);
        abandonCloseTimer = null;
      }
    };

    const handleMouseMove = (e: MouseEvent) => {
      // The pointer is back inside, so it hasn't abandoned the window.
      cancelAbandonClose();
      const state = stateRef.current;
      const pointer =
        state.side === "left" ? e.clientX : window.innerWidth - e.clientX;

      if (state.enabled) {
        if (state.peeked) {
          if (
            shouldCloseOnExit({
              pointer,
              width: state.width,
              margin: PEEK_CLOSE_MARGIN,
            })
          ) {
            state.onClose();
          }
        } else if (
          shouldRevealOnEdge({
            pointer,
            wasInside,
            threshold: PEEK_REVEAL_THRESHOLD,
          }) &&
          // An unfocused window still gets mousemove but also spurious
          // pointer-exit events; revealing there makes the peek stutter.
          document.hasFocus()
        ) {
          state.onReveal();
        }
      }

      wasInside = pointer <= PEEK_REVEAL_THRESHOLD;
    };

    // Mousemove can't close the peek once the pointer is outside the window,
    // so abandoning the window (app switch, pointer exit) closes it too.
    const closeIfPeeked = () => {
      const state = stateRef.current;
      if (state.enabled && state.peeked) state.onClose();
    };

    const scheduleAbandonClose = () => {
      if (abandonCloseTimer) return;
      abandonCloseTimer = setTimeout(() => {
        abandonCloseTimer = null;
        closeIfPeeked();
      }, PEEK_ABANDON_CLOSE_DELAY_MS);
    };

    const handleWindowFocus = () => {
      // Came back before the close fired; the peek is still wanted.
      cancelAbandonClose();
    };

    const handlePointerExit = () => {
      // Re-entering the edge from outside the window should reveal again.
      wasInside = false;
      scheduleAbandonClose();
    };

    document.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("blur", scheduleAbandonClose);
    window.addEventListener("focus", handleWindowFocus);
    document.documentElement.addEventListener("mouseleave", handlePointerExit);
    return () => {
      cancelAbandonClose();
      document.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("blur", scheduleAbandonClose);
      window.removeEventListener("focus", handleWindowFocus);
      document.documentElement.removeEventListener(
        "mouseleave",
        handlePointerExit,
      );
    };
  }, []);
}
