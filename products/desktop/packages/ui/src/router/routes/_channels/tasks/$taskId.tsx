import type { Task } from "@posthog/shared/domain-types";
import { ThreadSidebar } from "@posthog/ui/features/canvas/components/ThreadSidebar";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { TaskDetail } from "@posthog/ui/features/task-detail/components/TaskDetail";
import {
  getCachedTask,
  getCachedTaskDetail,
  isTaskDetailNotFoundError,
  taskDetailQuery,
} from "@posthog/ui/features/tasks/queries";
import { pickFreshestTask } from "@posthog/ui/features/tasks/taskFreshness";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { TaskDetailSkeleton } from "@posthog/ui/router/routeSkeletons";
import { yieldToPaint } from "@posthog/ui/router/yieldToPaint";
import { Button, Flex, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute, Navigate } from "@tanstack/react-router";
import { useEffect } from "react";

export const Route = createFileRoute("/_channels/tasks/$taskId")({
  component: TaskDetailRoute,
  pendingComponent: TaskDetailSkeleton,
  // Cache-only: return whatever is already cached (the detail entry seeded by
  // openTask, or the sidebar list) and never await the network. A
  // network-blocked loader would leave the route pending — and thus
  // un-navigable — whenever the fetch is slow or never resolves
  // (optimistic/cloud-pending tasks the API can't return). The cold-miss
  // fetch + skeleton live in the component instead. The single-frame yield
  // lets the pending skeleton paint before TaskDetail's heavy mount (chat
  // thread, terminal) blocks the main thread.
  loader: async ({ params }): Promise<Task | null> => {
    const task =
      getCachedTaskDetail(params.taskId) ??
      getCachedTask(params.taskId) ??
      null;
    await yieldToPaint();
    return task;
  },
  // The task's space rides as `?from=` (injected by the space-scoped legacy
  // redirect and by space-aware openers) rather than as a path segment, so a
  // task has exactly one canonical URL no matter which space link got you here.
  validateSearch: (search: Record<string, unknown>): { from?: string } => ({
    from: typeof search.from === "string" ? search.from : undefined,
  }),
});

function TaskDetailRoute() {
  const spacesLayout = useChannelsLayout();
  const { taskId } = Route.useParams();
  const { from } = Route.useSearch();
  const loaderTask = Route.useLoaderData();
  const { data: tasks } = useTasks();
  const fromList = tasks?.find((t) => t.id === taskId);
  const initialTask = pickFreshestTask(fromList, loaderTask);
  const { channels } = useChannels();
  const channelName = from
    ? channels.find((c) => c.id === from)?.name
    : undefined;

  // Opening a task through its space marks it viewed here: the spaces layout
  // doesn't mount SidebarMenu, which carries that side effect for unscoped
  // opens. Clears the task's unread state and lets a canvas's generation task
  // drop out of the nested sidebar row once the user has actually looked at it.
  const { markAsViewed } = useTaskViewed();
  useEffect(() => {
    if (from) markAsViewed(taskId);
  }, [from, taskId, markAsViewed]);

  // Always fetch so a stale cached copy converges on the server's latest run
  // state; render whichever copy is freshest.
  const {
    data: fetched,
    error,
    isError,
    isFetching,
    isSuccess,
    refetch,
  } = useQuery(taskDetailQuery(taskId));

  const task = pickFreshestTask(fetched, initialTask);

  // Cold deep-link / URL restore with nothing cached: if the fetch settled
  // with an error or empty result, redirect away rather than spin forever.
  // While a cached/list copy exists, a 404 is NOT authoritative (optimistic
  // and cloud-pending tasks aren't returnable by the API yet — see the loader
  // comment), so never redirect away from a usable task.
  const needsFetch = !initialTask;

  if (needsFetch && isTaskDetailNotFoundError(error)) {
    return <Navigate replace to="/new" />;
  }

  if (needsFetch && isError) {
    const message =
      error instanceof Error ? error.message : "Failed to load task";
    return (
      <Flex align="center" justify="center" height="100%" width="100%">
        <Flex direction="column" align="center" gap="3">
          <Text weight="medium">Failed to load task</Text>
          <Text color="gray" size="2">
            {message}
          </Text>
          <Button
            variant="soft"
            size="2"
            disabled={isFetching}
            onClick={() => void refetch()}
          >
            Try again
          </Button>
        </Flex>
      </Flex>
    );
  }

  if (needsFetch && isSuccess && !fetched) {
    return <Navigate replace to="/new" />;
  }

  if (!task) {
    return <TaskDetailSkeleton />;
  }

  if (!from) {
    return <TaskDetail task={task} />;
  }

  return (
    <div className="flex h-full min-w-0">
      <div className="min-w-0 flex-1">
        <TaskDetail
          task={task}
          channelName={channelName ?? "Space"}
          channelId={from}
        />
      </div>
      {/* The chrome's right panel carries the timeline, artifacts and comments
          under the spaces layout, so the session's own dock only serves the
          legacy one. */}
      {!spacesLayout && (
        <ThreadSidebar
          taskId={taskId}
          channelId={from}
          task={task}
          showTaskSummary={false}
          canOpenInPlace
        />
      )}
    </div>
  );
}
