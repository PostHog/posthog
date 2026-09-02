import { requestErrorStatus } from "@posthog/api-client/fetcher";
import { resolveService } from "@posthog/di/container";
import { NotAuthenticatedError } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { getAuthenticatedClient } from "@posthog/ui/features/auth/authClientImperative";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";
import { queryOptions } from "@tanstack/react-query";

// Shared query definition so a route `loader` and the component (useQuery) hit
// the same cache entry. The queryFn resolves the authenticated client
// imperatively, so it works outside React (in loaders) as well as inside
// components.
export function taskDetailQuery(taskId: string) {
  return queryOptions({
    queryKey: taskKeys.detail(taskId),
    queryFn: async (): Promise<Task> => {
      const client = await getAuthenticatedClient();
      if (!client) throw new NotAuthenticatedError();
      return (await client.getTask(taskId)) as unknown as Task;
    },
    meta: AUTH_SCOPED_QUERY_META,
    // A 404 is a definitive answer (optimistic/cloud-pending tasks aren't
    // returnable by the API yet) - retrying it only multiplies the miss.
    retry: (failureCount, error) =>
      !isTaskDetailNotFoundError(error) && failureCount < 3,
  });
}

export function isTaskDetailNotFoundError(error: unknown): boolean {
  return requestErrorStatus(error) === 404;
}

// Read a task from the already-loaded sidebar list cache without fetching.
// Lets the task-detail route loader resolve synchronously from cache.
export function getCachedTask(taskId: string): Task | undefined {
  return resolveService<ImperativeQueryClient>(IMPERATIVE_QUERY_CLIENT)
    .getQueriesData<Task[]>({ queryKey: taskKeys.lists() })
    .flatMap(([, tasks]) => tasks ?? [])
    .find((t) => t.id === taskId);
}

// Read the seeded task-detail cache entry (set by openTask) without fetching.
// Resolved lazily so the query client is only touched at navigation time, after
// the host has bound IMPERATIVE_QUERY_CLIENT at boot.
export function getCachedTaskDetail(taskId: string): Task | undefined {
  return resolveService<ImperativeQueryClient>(
    IMPERATIVE_QUERY_CLIENT,
  ).getQueryData<Task>(taskDetailQuery(taskId).queryKey);
}
