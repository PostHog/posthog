import { formatRelativeTimeShort } from "@posthog/shared";
import { TaskDotMark } from "../../sidebar/components/items/TaskStatusDot";
import { taskDot } from "../../sidebar/components/items/taskStatusVocabulary";
import type { ZoomCell } from "../useZoomGrid";

/**
 * A cell the camera isn't focused on. Deliberately cheap — no queries, no
 * agent stream, no panels — because every cell on the canvas that isn't the
 * selection renders one of these, at every zoom level.
 *
 * It is drawn at full cell size and then scaled down by the camera, so the type
 * here is sized for a whole window: what survives the shrink is the shape
 * (a header, a body, a status dot), not the words.
 */
export function ZoomCellPreview({
  cell,
  bodyOnly = false,
}: {
  cell: ZoomCell;
  /**
   * Drop the header. Set from world zoom, where the cell already carries a
   * counter-scaled title and this one has shrunk to an illegible smudge under
   * it.
   */
  bodyOnly?: boolean;
}) {
  const dot = taskDot(cell.status);

  return (
    <div className="flex h-full w-full flex-col gap-8 p-10">
      {!bodyOnly && (
        <div className="flex items-start gap-4">
          <span className="mt-3 scale-[3]">
            <TaskDotMark dot={dot} />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <p className="truncate font-medium text-(--gray-12) text-4xl leading-tight">
              {cell.task.title}
            </p>
            <p className="truncate text-(--gray-10) text-2xl">
              {cell.task.branchName ?? cell.columnName}
              <span className="px-3 text-(--gray-8)">·</span>
              {formatRelativeTimeShort(cell.task.lastActivityAt)}
              <span className="px-3 text-(--gray-8)">·</span>
              {dot.label}
            </p>
          </div>
        </div>
      )}

      {/* Stand-in for the thread. Reads as "there is a conversation in here"
          from far enough back that no real message would be legible anyway. */}
      <div aria-hidden className="flex flex-1 flex-col gap-5">
        {PREVIEW_LINE_WIDTHS.map((width, index) => (
          <div
            // Fixed decorative bars — index is the only identity they have.
            // biome-ignore lint/suspicious/noArrayIndexKey: static list
            key={index}
            className="h-5 rounded-full bg-(--gray-5)"
            style={{ width }}
          />
        ))}
      </div>
    </div>
  );
}

const PREVIEW_LINE_WIDTHS = [
  "82%",
  "68%",
  "90%",
  "44%",
  "76%",
  "58%",
  "86%",
  "37%",
];
