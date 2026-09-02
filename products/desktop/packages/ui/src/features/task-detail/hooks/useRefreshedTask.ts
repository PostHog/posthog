import type { Task } from "@posthog/shared/domain-types";
import { useQuery } from "@tanstack/react-query";
import { taskDetailQuery } from "../../tasks/queries";

export function useRefreshedTask(taskId: string, initialTask: Task): Task {
  const { data } = useQuery({
    ...taskDetailQuery(taskId),
    initialData: initialTask,
    refetchOnMount: "always",
  });

  // The refetch can resolve without data (e.g. a stale / cross-project id
  // where getTask returns nothing), leaving `data` undefined despite the
  // Task return type. Fall back to the last-known task so consumers
  // (useTaskData → getTaskRepository) never read off undefined and crash.
  return data ?? initialTask;
}
