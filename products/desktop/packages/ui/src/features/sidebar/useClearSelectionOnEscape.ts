import { useTaskSelectionStore } from "@posthog/ui/features/sidebar/taskSelectionStore";
import { useEffect } from "react";

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

/**
 * Escape clears a bulk session selection. Lives in a hook because each session
 * list owns its own mount — only one is on screen at a time, and whichever it
 * is has to answer Escape.
 */
export function useClearSelectionOnEscape(): void {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (isEditableTarget(e.target)) return;
      const { selectedTaskIds, clearSelection } =
        useTaskSelectionStore.getState();
      if (selectedTaskIds.length === 0) return;
      clearSelection();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
}
