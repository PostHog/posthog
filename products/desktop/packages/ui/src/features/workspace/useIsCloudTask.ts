import type { Task } from "@posthog/shared/domain-types";
import { useWorkspace } from "./useWorkspace";

export function useIsCloudTask(taskId: string, task?: Task): boolean {
  const workspace = useWorkspace(taskId);
  if (workspace?.mode === "cloud") return true;
  return task?.latest_run?.environment === "cloud";
}
