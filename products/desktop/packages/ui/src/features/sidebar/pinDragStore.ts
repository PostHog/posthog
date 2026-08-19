import { create } from "zustand";

interface PinDragState {
  /**
   * The flag alone, not the drag itself, which belongs to `usePinDrag`. The
   * shared preview card sits above both sidebars and reads this to stand down.
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
