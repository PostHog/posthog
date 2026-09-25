import type { TaskRunPreviewSession } from "@posthog/shared/domain-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

export function useTaskPreviewSession(
  taskId: string,
  runId: string,
  port: number,
  attempt: number,
  enabled: boolean,
) {
  return useAuthenticatedQuery<TaskRunPreviewSession>(
    ["task-preview-session", taskId, runId, port, attempt],
    (client) => client.createTaskRunPreviewSession(taskId, runId, port),
    {
      enabled,
      staleTime: Number.POSITIVE_INFINITY,
      gcTime: 0,
      retry: false,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    },
  );
}
