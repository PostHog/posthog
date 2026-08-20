import type { Task } from "@posthog/shared/domain-types";
import { isCloudTask, useWorkspace } from "./useWorkspace";

export function useIsCloudTask(taskId: string, task?: Task): boolean {
  const workspace = useWorkspace(taskId);
  if (!task) return workspace?.mode === "cloud";
  return isCloudTask(task, workspace);
}
