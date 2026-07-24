import type { Task } from "@posthog/shared/domain-types";
import { useQuery } from "@tanstack/react-query";
import { taskDetailQuery } from "../../tasks/queries";

export function useRefreshedTask(taskId: string, initialTask: Task): Task {
  const { data } = useQuery({
    ...taskDetailQuery(taskId),
    initialData: initialTask,
    refetchOnMount: "always",
  });

  return data;
}
