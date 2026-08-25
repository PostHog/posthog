import type { Schemas } from "@posthog/api-client";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import {
  applyRenameToDetail,
  applyRenameToList,
  applyRenameToPage,
  applyRenameToSummaries,
  getTaskTitle,
  rollbackDetailData,
  rollbackListData,
  rollbackPageData,
  rollbackSummaryData,
  shouldRollbackSessionTitle,
} from "@posthog/core/tasks/taskRename";
import { useService } from "@posthog/di/react";
import type { Task } from "@posthog/shared/domain-types";
import { channelFeedQueryRoot } from "@posthog/ui/features/canvas/hooks/useChannelFeed";
import {
  type SpaceTaskPage,
  spaceTreeTasksQueryRoot,
} from "@posthog/ui/features/canvas/hooks/useRecentSpaceTasks";
import { TASK_CHANNELS_QUERY_KEY } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { taskFeedResultsQueryRoot } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

type TaskFeedResults = { tasks: Task[]; isComplete: boolean };

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
        queryClient.invalidateQueries({ queryKey: spaceTreeTasksQueryRoot });
        queryClient.invalidateQueries({ queryKey: channelFeedQueryRoot });
        queryClient.invalidateQueries({ queryKey: taskFeedResultsQueryRoot });
      },
    },
  );
}

/**
 * Hand a task off to a colleague: the backend makes them the owner, moves a
 * private-space task into the recipient's private space, and announces the
 * handoff in the task's thread. The next refresh may drop the task from the
 * requester's own lists, so nothing here is seeded optimistically.
 */
export function useHandoffTask() {
  const queryClient = useQueryClient();

  return useAuthenticatedMutation(
    (client, { taskId, userId }: { taskId: string; userId: number }) =>
      client.handoffTask(taskId, userId),
    {
      onSuccess: (_, { taskId }) => {
        queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
        queryClient.invalidateQueries({ queryKey: taskKeys.detail(taskId) });
        queryClient.invalidateQueries({ queryKey: taskKeys.allSummaries() });
        queryClient.invalidateQueries({ queryKey: channelFeedQueryRoot });
        // A recipient's private channel may be created by the handoff, and the
        // task's channel can change (private space moves to the recipient's).
        queryClient.invalidateQueries({ queryKey: TASK_CHANNELS_QUERY_KEY });
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
      // Every one of these caches is polled. A fetch already in flight resolves
      // with a title from before the rename and writes it over the optimistic
      // one, so the row goes back to the old name until the next poll — the
      // stale sidebar this rename path exists to avoid. Cancelling first also
      // keeps the rollback honest: it reads these caches to decide whether our
      // write is still the one on screen.
      await Promise.all(
        [
          taskKeys.lists(),
          channelFeedQueryRoot,
          taskKeys.allSummaries(),
          spaceTreeTasksQueryRoot,
          taskFeedResultsQueryRoot,
          taskKeys.detail(taskId),
        ].map((queryKey) => queryClient.cancelQueries({ queryKey })),
      );

      const previousListQueries = queryClient.getQueriesData<Task[]>({
        queryKey: taskKeys.lists(),
      });
      const previousChannelFeedQueries = queryClient.getQueriesData<Task[]>({
        queryKey: channelFeedQueryRoot,
      });
      const previousTaskFeedQueries =
        queryClient.getQueriesData<TaskFeedResults>({
          queryKey: taskFeedResultsQueryRoot,
        });
      const previousSummaryQueries = queryClient.getQueriesData<
        Schemas.TaskSummary[]
      >({
        queryKey: taskKeys.allSummaries(),
      });
      const previousSpaceTreeQueries =
        queryClient.getQueriesData<SpaceTaskPage>({
          queryKey: spaceTreeTasksQueryRoot,
        });
      const previousDetail = queryClient.getQueryData<Task>(
        taskKeys.detail(taskId),
      );

      queryClient.setQueriesData<Task[]>(
        { queryKey: taskKeys.lists() },
        (old) => applyRenameToList(old, taskId, newTitle),
      );
      queryClient.setQueriesData<Task[]>(
        { queryKey: channelFeedQueryRoot },
        (old) => applyRenameToList(old, taskId, newTitle),
      );
      queryClient.setQueriesData<Schemas.TaskSummary[]>(
        { queryKey: taskKeys.allSummaries() },
        (old) => applyRenameToSummaries(old, taskId, newTitle),
      );
      queryClient.setQueriesData<SpaceTaskPage>(
        { queryKey: spaceTreeTasksQueryRoot },
        (old) => applyRenameToPage(old, taskId, newTitle),
      );
      queryClient.setQueriesData<TaskFeedResults>(
        { queryKey: taskFeedResultsQueryRoot },
        (old) =>
          old
            ? {
                ...old,
                tasks:
                  applyRenameToList(old.tasks, taskId, newTitle) ?? old.tasks,
              }
            : old,
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
        const channelFeedTitles = queryClient
          .getQueriesData<Task[]>({ queryKey: channelFeedQueryRoot })
          .map(([, tasks]) => getTaskTitle(tasks, taskId));
        const spaceTreeTitles = queryClient
          .getQueriesData<SpaceTaskPage>({ queryKey: spaceTreeTasksQueryRoot })
          .map(([, page]) => getTaskTitle(page?.tasks, taskId));
        const taskFeedTitles = queryClient
          .getQueriesData<TaskFeedResults>({
            queryKey: taskFeedResultsQueryRoot,
          })
          .map(([, result]) => getTaskTitle(result?.tasks, taskId));
        const rollbackSession = shouldRollbackSessionTitle({
          detailTitle: queryClient.getQueryData<Task>(taskKeys.detail(taskId))
            ?.title,
          listTitles: [
            ...listTitles,
            ...channelFeedTitles,
            ...spaceTreeTitles,
            ...taskFeedTitles,
          ],
          newTitle,
        });

        for (const [queryKey, data] of previousListQueries) {
          queryClient.setQueryData<Task[] | undefined>(queryKey, (current) =>
            rollbackListData(current, data ?? [], taskId, newTitle),
          );
        }
        for (const [queryKey, data] of previousChannelFeedQueries) {
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
        for (const [queryKey, data] of previousSpaceTreeQueries) {
          if (!data) continue;
          queryClient.setQueryData<SpaceTaskPage | undefined>(
            queryKey,
            (current) =>
              rollbackPageData<SpaceTaskPage>(current, data, taskId, newTitle),
          );
        }
        for (const [queryKey, data] of previousTaskFeedQueries) {
          queryClient.setQueryData<TaskFeedResults | undefined>(
            queryKey,
            (current) =>
              current
                ? {
                    ...current,
                    tasks:
                      rollbackListData(
                        current.tasks,
                        data?.tasks ?? [],
                        taskId,
                        newTitle,
                      ) ?? current.tasks,
                  }
                : current,
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
