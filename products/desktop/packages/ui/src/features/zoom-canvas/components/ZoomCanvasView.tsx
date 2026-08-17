import { SquaresFourIcon } from "@phosphor-icons/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import {
  cameraTransform,
  cellCenter,
  cellOrigin,
  scaleFor,
  worldCenter,
} from "../camera";
import { useCanvasViewport } from "../useCanvasViewport";
import type { ZoomGrid } from "../useZoomGrid";
import { useZoomHotkeys } from "../useZoomHotkeys";
import { useZoomNavigation } from "../useZoomNavigation";
import { ZoomCell } from "./ZoomCell";
import { ZoomHud } from "./ZoomHud";
import { ZoomMinimap } from "./ZoomMinimap";

/** Matches the camera's own easing — a settle, not a slide. */
const CAMERA_TRANSITION = "transform 760ms cubic-bezier(0.16, 1, 0.3, 1)";

/** How far the camera pulls back mid-move, for an arc instead of a pan. */
const TRAVEL_PULLBACK = 0.94;

/**
 * The whole app as one canvas: projects are columns, their tasks are rows, and
 * the window is a camera pointed down at it. Escape pulls the camera back
 * (task → nearby → everything) and Enter flies it in.
 *
 * Only the selected cell renders the real task view; every other cell is a
 * preview, so the canvas costs about what a single task view costs.
 */
export function ZoomCanvasView({ grid }: { grid: ZoomGrid }) {
  const [viewportRef, viewport] = useCanvasViewport();
  const navigation = useZoomNavigation(grid);
  useZoomHotkeys(navigation);

  const hasViewport = viewport.width > 0 && viewport.height > 0;
  const baseScale = scaleFor(navigation.zoom, viewport, grid.size);
  const scale =
    navigation.isTraveling && navigation.zoom === "session"
      ? baseScale * TRAVEL_PULLBACK
      : baseScale;
  const center =
    navigation.zoom === "world"
      ? worldCenter(viewport, grid.size)
      : cellCenter(navigation.position, viewport);
  const labelScale = scale > 0 ? 1 / scale : 1;

  return (
    <div
      ref={viewportRef}
      className="relative h-full w-full overflow-hidden bg-(--gray-1)"
    >
      {hasViewport && grid.columns.length > 0 && (
        // Deliberately unpromoted (no will-change / translateZ): the canvas is
        // many windows wide, and asking the compositor for one texture that
        // large makes it drop tiles. Left alone, only what the camera can see
        // is rasterized.
        <div
          className="absolute top-0 left-0"
          style={{
            transform: cameraTransform({ viewport, center, scale }),
            transformOrigin: "0 0",
            transition: CAMERA_TRANSITION,
          }}
        >
          {grid.columns.map((column, columnIndex) => {
            const origin = cellOrigin(
              { column: columnIndex, row: 0 },
              viewport,
            );
            return (
              <div
                key={column.id}
                className="pointer-events-none absolute flex items-baseline gap-2 transition-opacity duration-500"
                style={{
                  left: origin.x,
                  top: origin.y - 14,
                  // Counter-scaled to hold its on-screen size, then clamped to
                  // the column's on-screen width so headers can't run into
                  // each other when the camera is far back.
                  width: viewport.width * scale,
                  transform: `scale(${labelScale})`,
                  transformOrigin: "left bottom",
                  // A column header inside a task is noise — at session zoom
                  // the task's own header already says where you are.
                  opacity: navigation.zoom === "session" ? 0 : 1,
                }}
              >
                <span className="truncate font-semibold text-(--gray-12) text-[13px]">
                  {column.name}
                </span>
                <span className="shrink-0 text-(--gray-10) text-[11px]">
                  {column.cells.length}
                </span>
              </div>
            );
          })}

          {grid.cells.map((cell) => (
            <ZoomCell
              key={cell.task.id}
              cell={cell}
              selection={navigation.position}
              viewport={viewport}
              scale={scale}
              isSelected={cell.task.id === navigation.cell?.task.id}
              isLive={cell.task.id === navigation.cell?.task.id}
              fadeWithDistance={navigation.zoom === "arena"}
              showLabel={navigation.zoom === "world"}
              onSelect={() =>
                cell.task.id === navigation.cell?.task.id
                  ? navigation.stepIn()
                  : navigation.goTo(cell.position)
              }
            />
          ))}
        </div>
      )}

      {grid.columns.length === 0 && !grid.isLoading && (
        <div className="flex h-full items-center justify-center">
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <SquaresFourIcon size={28} />
              </EmptyMedia>
              <EmptyTitle>Nothing on the canvas yet</EmptyTitle>
              <EmptyDescription>
                Start a task and it takes a place on the grid.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        </div>
      )}

      {/* Keeps the eye in the middle of the camera. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-20"
        style={{ boxShadow: "inset 0 0 180px 40px var(--gray-1)" }}
      />

      <ZoomHud
        column={navigation.column}
        cell={navigation.cell}
        zoom={navigation.zoom}
        attentionCount={grid.needsAttention.length}
        onJumpToAttention={navigation.goToNextAttention}
      />

      {navigation.zoom !== "world" && (
        <ZoomMinimap
          grid={grid}
          selection={navigation.position}
          onJump={navigation.goTo}
        />
      )}
    </div>
  );
}
