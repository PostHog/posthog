import { useZoomGrid } from "../useZoomGrid";
import { ZoomCanvasView } from "./ZoomCanvasView";

/** The zoom canvas over the real task list. */
export function ZoomCanvas() {
  const grid = useZoomGrid();
  return <ZoomCanvasView grid={grid} />;
}
