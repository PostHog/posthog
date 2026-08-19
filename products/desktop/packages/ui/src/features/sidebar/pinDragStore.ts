import { create } from "zustand";

interface PinDragState {
  /**
   * A session row is being dragged in or out of a pinned run.
   *
   * The flag alone, not the drag itself: the drag belongs to the list running
   * it (`usePinDrag`), and what leaves that list is only the fact that one is
   * happening — which the shared preview card needs, because it sits above both
   * sidebars and has to stand down for the length of a drag.
   */
  dragging: boolean;
  setDragging: (dragging: boolean) => void;
}

export const usePinDragStore = create<PinDragState>((set) => ({
  dragging: false,
  setDragging: (dragging) => set({ dragging }),
}));

/** True while a session row is being dragged, for anything that must stand down. */
export function useIsPinDragging(): boolean {
  return usePinDragStore((s) => s.dragging);
}
