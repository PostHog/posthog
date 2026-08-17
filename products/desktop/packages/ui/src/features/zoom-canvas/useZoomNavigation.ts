import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  clamp,
  type GridPosition,
  type ZoomLevel,
  zoomedIn,
  zoomedOut,
} from "./camera";
import type { ZoomCell, ZoomColumn, ZoomGrid } from "./useZoomGrid";
import { useZoomCanvasStore } from "./zoomCanvasStore";

export type ZoomDirection = "left" | "right" | "up" | "down";

/** How long the camera is treated as in flight after a move. */
const TRAVEL_MS = 340;

export interface ZoomNavigation {
  /** The selection, clamped to a cell that actually exists. */
  position: GridPosition;
  column: ZoomColumn | null;
  cell: ZoomCell | null;
  zoom: ZoomLevel;
  isTraveling: boolean;
  goTo: (position: GridPosition) => void;
  move: (direction: ZoomDirection) => void;
  stepIn: () => void;
  stepOut: () => void;
  goToNextAttention: () => void;
}

function cellAt(grid: ZoomGrid, position: GridPosition): ZoomCell | null {
  return grid.columns[position.column]?.cells[position.row] ?? null;
}

export function useZoomNavigation(grid: ZoomGrid): ZoomNavigation {
  const zoom = useZoomCanvasStore((state) => state.zoom);
  const setZoom = useZoomCanvasStore((state) => state.setZoom);
  const rawColumn = useZoomCanvasStore((state) => state.column);
  const desiredRow = useZoomCanvasStore((state) => state.desiredRow);
  const setPosition = useZoomCanvasStore((state) => state.setPosition);
  const anchorTaskId = useZoomCanvasStore((state) => state.anchorTaskId);
  const setAnchorTaskId = useZoomCanvasStore((state) => state.setAnchorTaskId);

  const [isTraveling, setIsTraveling] = useState(false);
  const travelTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const bump = useCallback(() => {
    setIsTraveling(true);
    clearTimeout(travelTimer.current);
    travelTimer.current = setTimeout(() => setIsTraveling(false), TRAVEL_MS);
  }, []);

  useEffect(() => () => clearTimeout(travelTimer.current), []);

  const position = useMemo<GridPosition>(() => {
    const column = clamp(rawColumn, 0, Math.max(grid.columns.length - 1, 0));
    const rows = grid.columns[column]?.cells.length ?? 0;
    return { column, row: clamp(desiredRow, 0, Math.max(rows - 1, 0)) };
  }, [rawColumn, desiredRow, grid]);

  const cell = cellAt(grid, position);
  const column = grid.columns[position.column] ?? null;

  const select = useCallback(
    (next: GridPosition, nextCell: ZoomCell | null) => {
      if (nextCell) setAnchorTaskId(nextCell.task.id);
      setPosition(next.column, next.row);
      bump();
    },
    [setPosition, setAnchorTaskId, bump],
  );

  // Adopt whatever the camera landed on when there is no anchor yet — first
  // paint, or a selection whose task has since left the canvas.
  useEffect(() => {
    if (!cell) return;
    if (anchorTaskId && grid.cells.some((c) => c.task.id === anchorTaskId)) {
      return;
    }
    setAnchorTaskId(cell.task.id);
  }, [cell, anchorTaskId, grid.cells, setAnchorTaskId]);

  useEffect(() => {
    if (!anchorTaskId) return;
    const moved = grid.cells.find(
      (candidate) => candidate.task.id === anchorTaskId,
    );
    if (!moved) return;
    if (
      moved.position.column === position.column &&
      moved.position.row === position.row
    ) {
      return;
    }
    // Follow the task, without a travel bump: the camera is correcting for a
    // list that moved under it, not making a move of its own.
    setPosition(moved.position.column, moved.position.row);
  }, [grid, position, anchorTaskId, setPosition]);

  const goTo = useCallback(
    (next: GridPosition) => {
      const clamped = {
        column: clamp(next.column, 0, Math.max(grid.columns.length - 1, 0)),
        row: next.row,
      };
      const rows = grid.columns[clamped.column]?.cells.length ?? 0;
      clamped.row = clamp(clamped.row, 0, Math.max(rows - 1, 0));
      select(clamped, cellAt(grid, clamped));
    },
    [grid, select],
  );

  const move = useCallback(
    (direction: ZoomDirection) => {
      if (direction === "left" || direction === "right") {
        const next = clamp(
          position.column + (direction === "right" ? 1 : -1),
          0,
          Math.max(grid.columns.length - 1, 0),
        );
        if (next === position.column) return;
        // The row is deliberately left alone — `desiredRow` carries the row
        // the user asked for across columns of different lengths.
        const rows = grid.columns[next]?.cells.length ?? 0;
        const landing = {
          column: next,
          row: clamp(desiredRow, 0, Math.max(rows - 1, 0)),
        };
        select({ column: next, row: desiredRow }, cellAt(grid, landing));
        return;
      }

      const rows = grid.columns[position.column]?.cells.length ?? 0;
      const next = clamp(
        position.row + (direction === "down" ? 1 : -1),
        0,
        Math.max(rows - 1, 0),
      );
      if (next === position.row) return;
      const landing = { column: position.column, row: next };
      select(landing, cellAt(grid, landing));
    },
    [grid, position, desiredRow, select],
  );

  const stepIn = useCallback(() => {
    if (zoom === "session") return;
    setZoom(zoomedIn(zoom));
    bump();
  }, [zoom, setZoom, bump]);

  const stepOut = useCallback(() => {
    if (zoom === "world") return;
    setZoom(zoomedOut(zoom));
    bump();
  }, [zoom, setZoom, bump]);

  const goToNextAttention = useCallback(() => {
    const waiting = grid.needsAttention;
    if (waiting.length === 0) return;
    const isAfterSelection = (candidate: ZoomCell) =>
      candidate.position.column > position.column ||
      (candidate.position.column === position.column &&
        candidate.position.row > position.row);
    // Wraps to the first one, so repeated presses cycle the whole queue.
    const next = waiting.find(isAfterSelection) ?? waiting[0];
    if (next) goTo(next.position);
  }, [grid.needsAttention, position, goTo]);

  return {
    position,
    column,
    cell,
    zoom,
    isTraveling,
    goTo,
    move,
    stepIn,
    stepOut,
    goToNextAttention,
  };
}
