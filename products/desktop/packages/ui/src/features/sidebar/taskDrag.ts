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
