import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { useEffect, useRef } from "react";

export function useMarkTaskViewed(taskId: string, activityAtMs: number): void {
  const { markAsViewed } = useTaskViewed();
  const activityAtMsRef = useRef(activityAtMs);
  activityAtMsRef.current = activityAtMs;

  useEffect(() => {
    markAsViewed(taskId, activityAtMsRef.current);
  }, [markAsViewed, taskId]);
}
