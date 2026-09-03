import { taskActivityAt } from "@posthog/core/tasks/taskActivity";
import type { Task } from "@posthog/shared/domain-types";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { useEffect } from "react";

export function useMarkTaskViewed(
  task: Pick<Task, "id" | "created_at" | "updated_at" | "last_activity_at">,
): void {
  const { markAsViewed } = useTaskViewed();
  const activityAt = taskActivityAt(task);

  useEffect(() => {
    markAsViewed(task.id, activityAt);
  }, [activityAt, markAsViewed, task.id]);
}
