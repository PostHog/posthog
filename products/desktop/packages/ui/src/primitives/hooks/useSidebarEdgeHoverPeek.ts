import { useEffect, useRef } from "react";

export const PEEK_REVEAL_THRESHOLD = 24;
export const PEEK_CLOSE_MARGIN = 64;

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

    const handleMouseMove = (e: MouseEvent) => {
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
          })
        ) {
          state.onReveal();
        }
      }

      wasInside = pointer <= PEEK_REVEAL_THRESHOLD;
    };

    document.addEventListener("mousemove", handleMouseMove);
    return () => document.removeEventListener("mousemove", handleMouseMove);
  }, []);
}
