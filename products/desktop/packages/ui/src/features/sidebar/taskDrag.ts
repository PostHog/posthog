import { dedupeTaskIds } from "@posthog/core/sidebar/selection";
import type {
  TaskData,
  TaskGroup,
} from "@posthog/core/sidebar/sidebarData.types";
import { taskDragIdsSchema } from "@posthog/ui/features/sidebar/schemas";
import { useTaskSelectionStore } from "@posthog/ui/features/sidebar/taskSelectionStore";

export const TASK_DRAG_TYPE = "text/x-task-id";
export const TASK_IDS_DRAG_TYPE = "application/x-posthog-task-ids";

export function taskIdsForDrag(
  draggedTaskId: string,
  selectedTaskIds: readonly string[],
): string[] {
  if (!selectedTaskIds.includes(draggedTaskId)) return [draggedTaskId];
  return dedupeTaskIds([
    draggedTaskId,
    ...selectedTaskIds.filter((taskId) => taskId !== draggedTaskId),
  ]);
}

/**
 * The other sessions a drag on `grabbedId` carries: the rest of the selection
 * when the grabbed row belongs to one, and nothing when it doesn't. Resolved
 * against the list that is showing, so an id the list can't place is dropped
 * rather than travelling as a hole.
 */
export function taskDragSiblings<T>(
  grabbedId: string,
  candidates: readonly T[],
  idOf: (item: T) => string | null,
): T[] {
  const siblingIds = taskIdsForDrag(
    grabbedId,
    useTaskSelectionStore.getState().selectedTaskIds,
  ).filter((id) => id !== grabbedId);
  if (siblingIds.length === 0) return [];

  const byId = new Map<string, T>();
  for (const candidate of candidates) {
    const id = idOf(candidate);
    if (id !== null) byId.set(id, candidate);
  }
  return siblingIds.flatMap((id) => {
    const found = byId.get(id);
    return found ? [found] : [];
  });
}

/**
 * The rows a batch drag resolves its siblings against: whichever list the active
 * organize mode actually renders, plus the always-shown pinned run. by-project
 * caps each group on its own, so a row visible there can sit past the flat
 * window — resolving that batch against flatTasks would silently drop it.
 */
export function dragSiblingCandidates(
  organizeMode: "by-project" | "chronological",
  lists: {
    pinnedTasks: TaskData[];
    flatTasks: TaskData[];
    groupedTasks: TaskGroup[];
  },
): TaskData[] {
  const rendered =
    organizeMode === "by-project"
      ? lists.groupedTasks.flatMap((group) => group.tasks)
      : lists.flatTasks;
  return [...lists.pinnedTasks, ...rendered];
}

// Set by a target that takes a session drop for its own purpose, read once by
// the pin drag that started it. A module-level flag rather than a field on the
// event: the pin drag reads it on `dragend`, which is a different event from
// the `drop` the target handled.
let taskDropConsumed = false;

/**
 * Marks the session drop in flight as taken. A Command Center tile files what
 * was dropped on it, so the pin drag behind the same gesture must not also
 * unpin it.
 */
export function consumeTaskDrop(): void {
  taskDropConsumed = true;
}

/** Reads and clears the flag, so it can't survive into the next drag. */
export function takeConsumedTaskDrop(): boolean {
  const consumed = taskDropConsumed;
  taskDropConsumed = false;
  return consumed;
}

export function writeTaskDragData(
  dataTransfer: Pick<DataTransfer, "setData">,
  draggedTaskId: string,
): void {
  const taskIds = taskIdsForDrag(
    draggedTaskId,
    useTaskSelectionStore.getState().selectedTaskIds,
  );
  dataTransfer.setData(TASK_DRAG_TYPE, draggedTaskId);
  dataTransfer.setData(TASK_IDS_DRAG_TYPE, JSON.stringify(taskIds));
}

export function readTaskDragData(
  dataTransfer: Pick<DataTransfer, "getData">,
): string[] {
  const serializedTaskIds = dataTransfer.getData(TASK_IDS_DRAG_TYPE);
  if (serializedTaskIds) {
    let parsed: unknown = null;
    try {
      parsed = JSON.parse(serializedTaskIds);
    } catch {
      parsed = null;
    }
    const result = taskDragIdsSchema.safeParse(parsed);
    if (result.success) return dedupeTaskIds(result.data);
  }

  const taskId = dataTransfer.getData(TASK_DRAG_TYPE);
  return taskId ? [taskId] : [];
}
