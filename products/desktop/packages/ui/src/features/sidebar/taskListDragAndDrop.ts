import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";

export type TaskTimestampKey = "lastActivityAt" | "createdAt";

export function isPointInsideRect(
  point: { x: number; y: number },
  rect: Pick<DOMRect, "top" | "right" | "bottom" | "left"> | null,
): boolean {
  return Boolean(
    rect &&
      point.x >= rect.left &&
      point.x <= rect.right &&
      point.y >= rect.top &&
      point.y <= rect.bottom,
  );
}

export function getPinnedInsertionIndex(
  pinnedTasks: TaskData[],
  draggedTask: TaskData,
  timestampKey: TaskTimestampKey,
): number {
  const tasksWithoutSource = pinnedTasks.filter(
    (task) => task.id !== draggedTask.id,
  );
  const insertionIndex = tasksWithoutSource.findIndex(
    (task) => task[timestampKey] < draggedTask[timestampKey],
  );
  return insertionIndex === -1 ? tasksWithoutSource.length : insertionIndex;
}

export function getPinDropAction(
  sourcePinned: boolean,
  overPinned: boolean,
): boolean | null {
  if (!sourcePinned && overPinned) return true;
  if (sourcePinned && !overPinned) return false;
  return null;
}
