import { TaskPreviewPortsService } from "@posthog/core/task-preview/taskPreviewPorts";
import { taskPreviewPortsHost } from "./taskPreviewPortsHost";

export const taskPreviewPortsService = new TaskPreviewPortsService(
  taskPreviewPortsHost,
);

export function taskPreviewPortsQueryKey(taskId?: string) {
  return taskId
    ? (["task-preview-ports", taskId] as const)
    : (["task-preview-ports"] as const);
}
