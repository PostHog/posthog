import { create } from "zustand";
import type { ZoomLevel } from "./camera";

interface ZoomCanvasStore {
  zoom: ZoomLevel;
  column: number;
  /**
   * The row the user asked for, kept un-clamped. Moving sideways never
   * rewrites it, so passing through a short column clamps for display only and
   * the row comes back on the other side.
   */
  desiredRow: number;
  /**
   * The task the selection is *about*. Tasks reorder constantly — a run
   * finishing floats its task up its column — so the coordinates alone would
   * slide the camera onto a neighbour that nobody selected.
   */
  anchorTaskId: string | null;
  setZoom: (zoom: ZoomLevel) => void;
  setPosition: (column: number, desiredRow: number) => void;
  setAnchorTaskId: (taskId: string | null) => void;
}

export const useZoomCanvasStore = create<ZoomCanvasStore>()((set) => ({
  zoom: "session",
  column: 0,
  desiredRow: 0,
  anchorTaskId: null,
  setZoom: (zoom) => set({ zoom }),
  setPosition: (column, desiredRow) => set({ column, desiredRow }),
  setAnchorTaskId: (anchorTaskId) => set({ anchorTaskId }),
}));
