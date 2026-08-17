import { Button, Kbd } from "@posthog/quill";
import type { ZoomLevel } from "../camera";
import type { ZoomCell, ZoomColumn } from "../useZoomGrid";

const ZOOM_LABEL: Record<ZoomLevel, string> = {
  session: "Task",
  arena: "Nearby",
  world: "Everything",
};

/**
 * Where the camera is and what it is looking at, plus the one action that
 * matters from anywhere on the canvas: go to whatever is waiting on you.
 */
export function ZoomHud({
  column,
  cell,
  zoom,
  attentionCount,
  onJumpToAttention,
}: {
  column: ZoomColumn | null;
  cell: ZoomCell | null;
  zoom: ZoomLevel;
  attentionCount: number;
  onJumpToAttention: () => void;
}) {
  return (
    <div className="pointer-events-auto absolute bottom-4 left-4 z-30 flex items-center gap-3 rounded-md border border-border bg-background/85 py-1.5 pr-2 pl-3 backdrop-blur-sm">
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="shrink-0 font-medium text-(--gray-12) text-[12px]">
          {column?.name ?? "No projects yet"}
        </span>
        {cell && (
          <span className="max-w-[280px] truncate text-(--gray-10) text-[12px]">
            {cell.task.title}
          </span>
        )}
      </div>

      <span className="h-3.5 w-px bg-border" />

      <span className="flex items-center gap-1.5 text-(--gray-10) text-[11px]">
        {ZOOM_LABEL[zoom]}
        {zoom === "session" ? (
          <>
            <Kbd>esc</Kbd> out
          </>
        ) : (
          <>
            <Kbd>↵</Kbd> in
          </>
        )}
      </span>

      {attentionCount > 0 && (
        <Button size="sm" variant="outline" onClick={onJumpToAttention}>
          {attentionCount} waiting
          <Kbd>⌥N</Kbd>
        </Button>
      )}
    </div>
  );
}
