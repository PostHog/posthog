/**
 * Geometry for the zoom canvas: a camera pointed down at a grid of task cells.
 *
 * Columns are projects, rows are the tasks inside one. Every measurement is in
 * canvas units, where one cell is exactly one viewport — so at session zoom the
 * camera sits at scale 1 and a cell fills the window with no resampling.
 */

/** How far back the camera sits. */
export type ZoomLevel = "session" | "arena" | "world";

/** Gap between neighbouring cells, in canvas units. */
export const CELL_GAP = 110;

/**
 * Cells across and down that the arena frames. The fraction is deliberate: at
 * 2.62 the four side neighbours are clipped by the window edge, which reads as
 * "there is more out there" far better than a tidy 3×3 does.
 */
const ARENA_SPAN = 2.62;

/**
 * Breathing room around the whole canvas at world zoom, in cells. Also what
 * the column headers sit in — they are drawn above row 0, outside the grid.
 */
const WORLD_MARGIN = 0.55;

export interface Viewport {
  width: number;
  height: number;
}

export interface GridSize {
  columns: number;
  rows: number;
}

export interface GridPosition {
  column: number;
  row: number;
}

export interface CanvasPoint {
  x: number;
  y: number;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/** Distance between one cell and the next, gap included. */
function cellPitch(viewport: Viewport): CanvasPoint {
  return { x: viewport.width + CELL_GAP, y: viewport.height + CELL_GAP };
}

export function cellOrigin(
  position: GridPosition,
  viewport: Viewport,
): CanvasPoint {
  const pitch = cellPitch(viewport);
  return { x: position.column * pitch.x, y: position.row * pitch.y };
}

export function cellCenter(
  position: GridPosition,
  viewport: Viewport,
): CanvasPoint {
  const origin = cellOrigin(position, viewport);
  return {
    x: origin.x + viewport.width / 2,
    y: origin.y + viewport.height / 2,
  };
}

/**
 * Scale the camera runs at for a zoom level.
 *
 * - `session` is 1, so the focused cell is pixel-for-pixel the window.
 * - `arena` frames the selection plus its clipped neighbours.
 * - `world` fits every column and row at once.
 */
export function scaleFor(
  zoom: ZoomLevel,
  viewport: Viewport,
  grid: GridSize,
): number {
  if (zoom === "session") return 1;

  const pitch = cellPitch(viewport);
  if (zoom === "arena") {
    return Math.min(
      viewport.width / (ARENA_SPAN * pitch.x),
      viewport.height / (ARENA_SPAN * pitch.y),
    );
  }

  // An empty grid would divide by the margin alone and blow the camera up.
  const columns = Math.max(grid.columns, 1);
  const rows = Math.max(grid.rows, 1);
  return Math.min(
    viewport.width / ((columns + WORLD_MARGIN) * pitch.x),
    viewport.height / ((rows + WORLD_MARGIN) * pitch.y),
  );
}

/** Centre of the whole canvas — what the camera frames at world zoom. */
export function worldCenter(viewport: Viewport, grid: GridSize): CanvasPoint {
  const pitch = cellPitch(viewport);
  const columns = Math.max(grid.columns, 1);
  const rows = Math.max(grid.rows, 1);
  return {
    x: (columns * pitch.x - CELL_GAP) / 2,
    y: (rows * pitch.y - CELL_GAP) / 2,
  };
}

export function zoomedIn(zoom: ZoomLevel): ZoomLevel {
  return zoom === "world" ? "arena" : "session";
}

export function zoomedOut(zoom: ZoomLevel): ZoomLevel {
  return zoom === "session" ? "arena" : "world";
}

/** Chebyshev distance — how many cells away one cell is from another. */
export function cellDistance(a: GridPosition, b: GridPosition): number {
  return Math.max(Math.abs(a.column - b.column), Math.abs(a.row - b.row));
}

/**
 * The CSS transform that puts `center` in the middle of the window at `scale`.
 * Applied to the canvas layer, whose own origin is its top-left corner.
 */
export function cameraTransform({
  viewport,
  center,
  scale,
}: {
  viewport: Viewport;
  center: CanvasPoint;
  scale: number;
}): string {
  const originX = viewport.width / 2;
  const originY = viewport.height / 2;
  return `translate(${originX}px, ${originY}px) scale(${scale}) translate(${-center.x}px, ${-center.y}px)`;
}
