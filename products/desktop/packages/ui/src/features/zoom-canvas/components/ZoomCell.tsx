import { cn } from "@posthog/quill";
import { TaskDotMark } from "../../sidebar/components/items/TaskStatusDot";
import { taskDot } from "../../sidebar/components/items/taskStatusVocabulary";
import {
  cellDistance,
  cellOrigin,
  type GridPosition,
  type Viewport,
} from "../camera";
import type { ZoomCell as ZoomCellData } from "../useZoomGrid";
import { ZoomCellPreview } from "./ZoomCellPreview";
import { ZoomSessionCell } from "./ZoomSessionCell";

interface ZoomCellProps {
  cell: ZoomCellData;
  selection: GridPosition;
  viewport: Viewport;
  /** The camera's current scale, for sizing the counter-scaled label. */
  scale: number;
  isSelected: boolean;
  /** Render the live task rather than a preview. */
  isLive: boolean;
  /**
   * Dim cells by their distance from the selection. Off at world zoom, where
   * everything is far away and the point is to see all of it.
   */
  fadeWithDistance: boolean;
  /**
   * Draw the title at a fixed on-screen size over the cell. For the zoom
   * levels where the preview's own text has shrunk past reading.
   */
  showLabel: boolean;
  onSelect: () => void;
}

/** One cell: the live task when it is the selection, a cheap preview otherwise. */
export function ZoomCell({
  cell,
  selection,
  viewport,
  scale,
  isSelected,
  isLive,
  fadeWithDistance,
  showLabel,
  onSelect,
}: ZoomCellProps) {
  const origin = cellOrigin(cell.position, viewport);
  const distance = cellDistance(cell.position, selection);
  const opacity =
    isSelected || !fadeWithDistance ? 1 : Math.max(0.4, 1 - distance * 0.18);

  return (
    <div
      className="absolute"
      style={{
        left: origin.x,
        top: origin.y,
        width: viewport.width,
        height: viewport.height,
      }}
    >
      <div
        className={cn(
          "h-full w-full overflow-hidden rounded-lg border bg-(--gray-2) transition-[opacity,border-color] duration-500",
          isSelected ? "border-primary/60" : "border-(--gray-6)",
        )}
        style={{ opacity }}
      >
        {isLive ? (
          <ZoomSessionCell taskId={cell.task.id} />
        ) : (
          // A preview is a target, not a document: clicking it selects the
          // cell, and clicking the selection again flies into it.
          <button
            type="button"
            aria-label={`Go to ${cell.task.title}`}
            className="block h-full w-full cursor-pointer text-left"
            onClick={onSelect}
          >
            <ZoomCellPreview cell={cell} bodyOnly={showLabel} />
          </button>
        )}
      </div>

      {showLabel && (
        // Counter-scaled so the title holds its on-screen size however far back
        // the camera is, and width-clamped to the cell's on-screen width so a
        // long title clips instead of running across its neighbours.
        <div
          className="pointer-events-none absolute top-0 left-0 flex items-center gap-1.5 rounded-t-lg bg-(--gray-2)/90 px-2 py-1.5"
          style={{
            width: viewport.width * scale,
            transform: `scale(${1 / scale})`,
            transformOrigin: "left top",
            opacity,
          }}
        >
          <TaskDotMark dot={taskDot(cell.status)} />
          <span className="truncate font-medium text-(--gray-12) text-[12px]">
            {cell.task.title}
          </span>
        </div>
      )}
    </div>
  );
}
