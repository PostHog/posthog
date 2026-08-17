import { cn } from "@posthog/quill";
import {
  DOT_TONE_VAR,
  taskDot,
} from "../../sidebar/components/items/taskStatusVocabulary";
import type { GridPosition } from "../camera";
import type { ZoomGrid } from "../useZoomGrid";

const TILE = 10;
const TILE_GAP = 3;

/**
 * The canvas in miniature: one tile per task, laid out exactly like the grid,
 * so a glance says where the work is without moving the camera.
 *
 * Hidden at world zoom, where the canvas already is the map.
 */
export function ZoomMinimap({
  grid,
  selection,
  onJump,
}: {
  grid: ZoomGrid;
  selection: GridPosition;
  onJump: (position: GridPosition) => void;
}) {
  if (grid.columns.length === 0) return null;

  return (
    <div
      className="pointer-events-auto absolute right-4 bottom-4 z-30 flex gap-[3px] rounded-md border border-border bg-background/85 p-2 backdrop-blur-sm"
      style={{ gap: TILE_GAP }}
    >
      {grid.columns.map((column, columnIndex) => (
        <div
          key={column.id}
          className="flex flex-col"
          style={{ gap: TILE_GAP }}
        >
          {column.cells.map((cell) => {
            const dot = taskDot(cell.status);
            const isSelected =
              columnIndex === selection.column &&
              cell.position.row === selection.row;
            return (
              <button
                key={cell.task.id}
                type="button"
                title={cell.task.title}
                aria-label={`Go to ${cell.task.title}`}
                aria-current={isSelected}
                onClick={() => onJump(cell.position)}
                className={cn(
                  "cursor-pointer rounded-[2px] transition-transform hover:scale-125",
                  dot.spinner && "ph-pulse motion-reduce:animate-none",
                )}
                style={{
                  width: TILE,
                  height: TILE,
                  backgroundColor: DOT_TONE_VAR[dot.tone],
                  opacity: dot.style === "hollow" ? 0.35 : 1,
                  outline: isSelected
                    ? "1.5px solid var(--gray-12)"
                    : undefined,
                  outlineOffset: 1.5,
                }}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}
