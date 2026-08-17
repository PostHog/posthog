import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import type { TaskStatusInput } from "../sidebar/components/items/taskStatusVocabulary";

/**
 * A cell's state in the shared task vocabulary, so a dot on the canvas means
 * exactly what the same dot means in a task list.
 */
export function cellStatusInput(task: TaskData): TaskStatusInput {
  return {
    workspaceMode: task.workspaceMode,
    isGenerating: task.isGenerating,
    isUnread: task.isUnread,
    isPinned: task.isPinned,
    isSuspended: task.isSuspended,
    needsPermission: task.needsPermission,
    taskRunStatus: task.taskRunStatus,
    runMode: task.runMode,
    originProduct: task.originProduct,
    slackThreadUrl: task.slackThreadUrl,
    prUrl: task.cloudPrUrl,
  };
}

/**
 * Whether the task is waiting on a person — what ⌥N walks. Both halves count:
 * a permission prompt blocks the run outright, and unread output is the agent
 * having said something nobody has read.
 */
export function wantsAttention(task: TaskData): boolean {
  return task.needsPermission || task.isUnread;
}
