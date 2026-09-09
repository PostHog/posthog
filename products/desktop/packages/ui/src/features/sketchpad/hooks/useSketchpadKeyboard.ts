import {
  fitToContent,
  type SketchpadBox,
  type SketchpadPaneRect,
  zoomTo,
} from "@posthog/core/sketchpad/sketchpadGeometry";
import type { SketchpadViewport } from "@posthog/shared";
import { useEffect, useRef } from "react";

export interface UseSketchpadKeyboardOptions {
  enabled?: boolean;
  paneRect: SketchpadPaneRect;
  fragments: readonly SketchpadBox[];
  viewport: SketchpadViewport;
  setViewport: (viewport: SketchpadViewport) => void;
  selectedIds: readonly string[];
  onDeleteSelected: (ids: string[]) => void;
  onClearSelection: () => void;
  onSelectAll: () => void;
  onUndo: () => void;
}

export function useSketchpadKeyboard(
  options: UseSketchpadKeyboardOptions,
): void {
  const latest = useRef(options);
  latest.current = options;

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      const current = latest.current;
      if (current.enabled === false) return;
      if (isTypingTarget(event.target)) return;

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        current.onUndo();
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "a") {
        event.preventDefault();
        current.onSelectAll();
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      const pane = current.paneRect;

      switch (event.key) {
        case "Delete":
        case "Backspace":
          if (current.selectedIds.length === 0) return;
          event.preventDefault();
          current.onDeleteSelected([...current.selectedIds]);
          return;
        case "Escape":
          current.onClearSelection();
          return;
        case "0":
          if (pane.width === 0 || pane.height === 0) return;
          event.preventDefault();
          current.setViewport(zoomTo(current.viewport, 1, pane));
          return;
        case "1":
          if (pane.width === 0 || pane.height === 0) return;
          event.preventDefault();
          current.setViewport(fitToContent(current.fragments, pane));
          return;
        default:
          return;
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    tag === "IFRAME"
  ) {
    return true;
  }
  return target.isContentEditable;
}
