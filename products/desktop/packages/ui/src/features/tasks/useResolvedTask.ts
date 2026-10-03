import type { Task } from "@posthog/shared/domain-types";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import {
  getCachedTask,
  getCachedTaskDetail,
  taskDetailQuery,
} from "@posthog/ui/features/tasks/queries";
import { pickFreshestTask } from "@posthog/ui/features/tasks/taskFreshness";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

/**
 * Turn a task id into something renderable, and count that as a view. The list
 * copy and the cache stand in until the detail fetch lands; freshness picks
 * between them, because a poll can hand back an older run than the one already
 * on screen.
 */
export function useResolvedTask(taskId: string | undefined): Task | undefined {
  const { data: tasks } = useTasks();
  const { markAsViewed } = useTaskViewed();

  const { data: fetched } = useQuery({
    ...taskDetailQuery(taskId ?? ""),
    enabled: Boolean(taskId),
  });

  useEffect(() => {
    if (taskId) markAsViewed(taskId);
  }, [taskId, markAsViewed]);

  if (!taskId) return undefined;
  const known =
    tasks?.find((task) => task.id === taskId) ??
    getCachedTaskDetail(taskId) ??
    getCachedTask(taskId) ??
    undefined;
  return pickFreshestTask(fetched, known);
}
