import { dedupeTaskIds } from "@posthog/core/sidebar/selection";
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
