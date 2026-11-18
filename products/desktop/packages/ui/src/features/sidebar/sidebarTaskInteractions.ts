import type { Task } from "@posthog/shared/domain-types";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { navigateToTaskDetail } from "@posthog/ui/router/navigationBridge";
import { openTask } from "@posthog/ui/router/useOpenTask";
import type { QueryClient } from "@tanstack/react-query";

function getCachedTask(queryClient: QueryClient, taskId: string): Task | null {
  const detail = queryClient.getQueryData<Task>(
    taskDetailQuery(taskId).queryKey,
  );
  if (detail) return detail;

  for (const [, tasks] of queryClient.getQueriesData<Task[]>({
    queryKey: taskKeys.lists(),
  })) {
    const task = tasks?.find((candidate) => candidate.id === taskId);
    if (task) return task;
  }
  return null;
}

async function fetchTask(
  queryClient: QueryClient,
  taskId: string,
): Promise<Task> {
  return queryClient.fetchQuery({
    ...taskDetailQuery(taskId),
    retry: false,
  });
}

export async function openSidebarTask(
  queryClient: QueryClient,
  taskId: string,
): Promise<void> {
  const task = await resolveSidebarTask(queryClient, taskId);
  if (!task) {
    navigateToTaskDetail(taskId);
    return;
  }
  await openTask(task);
}

export async function resolveSidebarTask(
  queryClient: QueryClient,
  taskId: string,
): Promise<Task | null> {
  const cached = getCachedTask(queryClient, taskId);
  if (cached) return cached;

  try {
    return await fetchTask(queryClient, taskId);
  } catch {
    return null;
  }
}
