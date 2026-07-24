import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import {
  insertTaskDedup,
  removeTaskFromList,
} from "@posthog/core/tasks/taskDelete";
import {
  TASK_DELETION_SERVICE,
  type TaskDeletionService,
} from "@posthog/core/tasks/taskDeletionService";
import { useService } from "@posthog/di/react";
import type { Task } from "@posthog/shared/domain-types";
import { destroyTaskTerminals } from "@posthog/ui/features/terminal/destroyTaskTerminals";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { taskKeys } from "./taskKeys";

const log = logger.scope("tasks");

// Never throws: the task is already deleted server-side, so a cleanup failure
// must not reject the mutation and roll back the optimistic list removal.
export async function releaseDeletedTaskResources(
  taskId: string,
  sessionService: SessionService,
): Promise<void> {
  try {
    await sessionService.disconnectFromTask(taskId);
  } catch (error) {
    log.error("Failed to disconnect session for deleted task", error);
  }
  try {
    destroyTaskTerminals(taskId);
  } catch (error) {
    log.error("Failed to release terminals for deleted task", error);
  }
}

export function useCreateTask() {
  const queryClient = useQueryClient();

  const invalidateTasks = (newTask?: Task) => {
    if (newTask) {
      // Only seed list caches that aren't scoped to a specific origin_product.
      // An origin-scoped list (e.g. the slack-origin list behind useSlackTasks)
      // is read by the sidebar to brand a task's icon by id membership, so
      // seeding a freshly created, non-slack task into it would make that task
      // briefly render as a Slack task until the list refetches. Origin-less
      // lists, by contrast, should mirror every new task.
      queryClient.setQueriesData<Task[]>(
        {
          queryKey: taskKeys.lists(),
          predicate: (query) => {
            const isOriginScopedList = Boolean(
              taskKeys.filtersOf(query.queryKey)?.originProduct,
            );
            return !isOriginScopedList;
          },
        },
        (old) => insertTaskDedup(old, newTask),
      );
    }
    queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
  };

  const mutation = useAuthenticatedMutation(
    (
      client,
      {
        description,
        repository,
        github_integration,
      }: {
        description: string;
        repository?: string;
        github_integration?: number;
        createdFrom?: "cli" | "command-menu";
      },
    ) =>
      client.createTask({
        description,
        repository,
        github_integration,
      }) as unknown as Promise<Task>,
  );

  return { ...mutation, invalidateTasks };
}

interface DeleteTaskOptions {
  taskId: string;
  taskTitle: string;
  hasWorktree: boolean;
}

export function useDeleteTask() {
  const queryClient = useQueryClient();
  const deletionService = useService<TaskDeletionService>(
    TASK_DELETION_SERVICE,
  );
  const sessionService = useService<SessionService>(SESSION_SERVICE);

  const mutation = useAuthenticatedMutation(
    async (client, taskId: string) => {
      const result = await deletionService.deleteTask(client, taskId);
      await releaseDeletedTaskResources(taskId, sessionService);
      return result;
    },
    {
      onMutate: async (taskId) => {
        await queryClient.cancelQueries({ queryKey: taskKeys.lists() });

        const previousQueries: Array<{ queryKey: unknown; data: Task[] }> = [];
        const queries = queryClient.getQueriesData<Task[]>({
          queryKey: taskKeys.lists(),
        });
        for (const [queryKey, data] of queries) {
          if (data) {
            previousQueries.push({ queryKey, data });
          }
        }

        queryClient.setQueriesData<Task[]>(
          { queryKey: taskKeys.lists() },
          (old) => removeTaskFromList(old, taskId),
        );

        return { previousQueries };
      },
      onError: (_err, _taskId, context) => {
        const ctx = context as
          | {
              previousQueries: Array<{
                queryKey: readonly unknown[];
                data: Task[];
              }>;
            }
          | undefined;
        if (ctx?.previousQueries) {
          for (const { queryKey, data } of ctx.previousQueries) {
            queryClient.setQueryData(queryKey, data);
          }
        }
      },
      onSettled: () => {
        queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
      },
    },
  );

  const deleteWithConfirm = useCallback(
    (options: DeleteTaskOptions) =>
      deletionService.confirmAndDelete(options, mutation.mutateAsync),
    [deletionService, mutation.mutateAsync],
  );

  return { ...mutation, deleteWithConfirm };
}
