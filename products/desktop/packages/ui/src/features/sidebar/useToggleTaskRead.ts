import {
  isTaskUnread,
  taskLastActivityAt,
} from "@posthog/core/sidebar/buildSidebarData";
import { taskActivityAt } from "@posthog/core/tasks/taskActivity";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback } from "react";

interface TaskReadState {
  isUnread: boolean;
  /** The activity time behind the unread dot, from `taskLastActivityAt`. */
  lastActivityAt: number;
}

/** Flips a task between read and unread, for the row menus. */
export function useToggleTaskRead(): (
  taskId: string,
  state: TaskReadState,
) => void {
  const { markAsViewed, markAsUnread } = useTaskViewed();

  return useCallback(
    (taskId, { isUnread, lastActivityAt }) => {
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: isUnread ? "mark_task_read" : "mark_task_unread",
        surface: "sidebar",
        task_id: taskId,
      });
      if (isUnread) {
        markAsViewed(taskId);
      } else {
        markAsUnread(taskId, lastActivityAt);
      }
    },
    [markAsViewed, markAsUnread],
  );
}

/** A task's read state from the same rule as its unread dot, with the flip. */
export function useTaskReadItem(task: Task): {
  isUnread: boolean;
  toggle: () => void;
} {
  const { timestamps } = useTaskViewed();
  const toggleRead = useToggleTaskRead();
  const timestamp = timestamps[task.id];
  const activityAt = taskActivityAt(task);
  const isUnread = isTaskUnread(activityAt, timestamp);

  return {
    isUnread,
    toggle: () =>
      toggleRead(task.id, {
        isUnread,
        lastActivityAt: taskLastActivityAt(activityAt, timestamp),
      }),
  };
}
