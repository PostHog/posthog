import type { Schemas } from "@posthog/api-client";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import {
  applyRenameToDetail,
  applyRenameToList,
  applyRenameToSummaries,
  getTaskTitle,
  rollbackDetailData,
  rollbackListData,
  rollbackSummaryData,
  shouldRollbackSessionTitle,
} from "@posthog/core/tasks/taskRename";
import { useService } from "@posthog/di/react";
import type { Task } from "@posthog/shared/domain-types";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

export function useUpdateTask() {
  const queryClient = useQueryClient();

  return useAuthenticatedMutation(
    (
      client,
      {
        taskId,
        updates,
      }: {
        taskId: string;
        updates: Partial<Task>;
      },
    ) =>
      client.updateTask(
        taskId,
        updates as Parameters<typeof client.updateTask>[1],
      ),
    {
      onSuccess: (_, { taskId }) => {
        queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
        queryClient.invalidateQueries({ queryKey: taskKeys.detail(taskId) });
        queryClient.invalidateQueries({ queryKey: taskKeys.allSummaries() });
      },
    },
  );
}

export function useRenameTask() {
  const queryClient = useQueryClient();
  const updateTask = useUpdateTask();
  const sessionService = useService<SessionService>(SESSION_SERVICE);

  const renameTask = useCallback(
    async ({
      taskId,
      currentTitle,
      newTitle,
    }: {
      taskId: string;
      currentTitle: string;
      newTitle: string;
    }) => {
      const previousListQueries = queryClient.getQueriesData<Task[]>({
        queryKey: taskKeys.lists(),
      });
      const previousSummaryQueries = queryClient.getQueriesData<
        Schemas.TaskSummary[]
      >({
        queryKey: taskKeys.allSummaries(),
      });
      const previousDetail = queryClient.getQueryData<Task>(
        taskKeys.detail(taskId),
      );

      queryClient.setQueriesData<Task[]>(
        { queryKey: taskKeys.lists() },
        (old) => applyRenameToList(old, taskId, newTitle),
      );
      queryClient.setQueriesData<Schemas.TaskSummary[]>(
        { queryKey: taskKeys.allSummaries() },
        (old) => applyRenameToSummaries(old, taskId, newTitle),
      );

      if (previousDetail) {
        queryClient.setQueryData<Task>(
          taskKeys.detail(taskId),
          applyRenameToDetail(previousDetail, newTitle),
        );
      }

      sessionService.updateSessionTaskTitle(taskId, newTitle);

      try {
        await updateTask.mutateAsync({
          taskId,
          updates: { title: newTitle, title_manually_set: true },
        });
      } catch (error) {
        const listTitles = queryClient
          .getQueriesData<Task[]>({ queryKey: taskKeys.lists() })
          .map(([, tasks]) => getTaskTitle(tasks, taskId));
        const rollbackSession = shouldRollbackSessionTitle({
          detailTitle: queryClient.getQueryData<Task>(taskKeys.detail(taskId))
            ?.title,
          listTitles,
          newTitle,
        });

        for (const [queryKey, data] of previousListQueries) {
          queryClient.setQueryData<Task[] | undefined>(queryKey, (current) =>
            rollbackListData(current, data ?? [], taskId, newTitle),
          );
        }
        for (const [queryKey, data] of previousSummaryQueries) {
          queryClient.setQueryData<Schemas.TaskSummary[] | undefined>(
            queryKey,
            (current) =>
              rollbackSummaryData(current, data ?? [], taskId, newTitle),
          );
        }
        if (previousDetail) {
          queryClient.setQueryData<Task | undefined>(
            taskKeys.detail(taskId),
            (current) =>
              rollbackDetailData<Task>(current, previousDetail, newTitle),
          );
        }
        if (rollbackSession) {
          sessionService.updateSessionTaskTitle(taskId, currentTitle);
        }
        throw error;
      }
    },
    [queryClient, updateTask, sessionService],
  );

  return {
    renameTask,
    isPending: updateTask.isPending,
  };
}
