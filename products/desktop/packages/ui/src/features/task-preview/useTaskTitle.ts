import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQuery } from "@tanstack/react-query";

export function useTaskTitle(taskId: string | undefined): string | undefined {
  const { data } = useQuery({
    ...taskDetailQuery(taskId ?? ""),
    enabled: Boolean(taskId),
    select: (task) => task.title,
  });
  return data || undefined;
}
