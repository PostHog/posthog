import {
  TASK_PREVIEW_PORTS_POLL_INTERVAL_MS,
  type TaskPreviewPorts,
} from "@posthog/core/task-preview/taskPreviewPorts";
import type { Task } from "@posthog/shared/domain-types";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useQuery } from "@tanstack/react-query";
import {
  taskPreviewPortsQueryKey,
  taskPreviewPortsService,
} from "./taskPreviewPortsService";

export function useTaskPreviewPorts(
  task: Task | undefined,
): TaskPreviewPorts | null {
  const { data } = useQuery({
    queryKey: [
      ...taskPreviewPortsQueryKey(task?.id ?? ""),
      task?.latest_run?.id ?? "none",
    ],
    queryFn: () =>
      task ? taskPreviewPortsService.getPreviewPorts(task) : null,
    enabled: !!task,
    meta: AUTH_SCOPED_QUERY_META,
    refetchInterval: (query) =>
      query.state.data?.settled ? false : TASK_PREVIEW_PORTS_POLL_INTERVAL_MS,
    placeholderData: (previous) => previous,
  });
  return data ?? null;
}
