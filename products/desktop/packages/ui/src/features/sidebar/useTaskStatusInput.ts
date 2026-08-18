import type { Task } from "@posthog/shared/domain-types";
import { useChannelTaskData } from "@posthog/ui/features/canvas/hooks/useChannelTaskData";
import type { TaskStatusInput } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { useTaskPrStatus } from "@posthog/ui/features/sidebar/useTaskPrStatus";
import { useWorkspace } from "@posthog/ui/features/workspace/useWorkspace";

/**
 * The state behind a task's status dot and badges, assembled from the places its
 * inputs actually live: renderer state (live session, workspace, viewed
 * timestamps) and a per-task PR query.
 */
export function useTaskStatusInput(
  task: Task | undefined,
  options?: {
    /**
     * Whether to resolve the PR's state. It is a query per task into the host,
     * where it hits git (and GitHub), so a list that only glances at its rows
     * leaves it off and shows the rest. The PR's existence still comes through
     * `prUrl`, which costs nothing.
     */
    withPrStatus?: boolean;
  },
): TaskStatusInput | null {
  const taskData = useChannelTaskData(task);
  const workspace = useWorkspace(task?.id);
  const { prState, hasDiff, prUrl } = useTaskPrStatus({
    // An empty id is the hook's own "nothing to look up", so this asks for no
    // query rather than one it throws away.
    id: options?.withPrStatus === false ? "" : (task?.id ?? ""),
    cloudPrUrl: taskData?.cloudPrUrl ?? null,
    taskRunEnvironment: taskData?.taskRunEnvironment ?? null,
  });

  if (!taskData) return null;
  return {
    workspaceMode:
      workspace?.mode ??
      (taskData.taskRunEnvironment === "cloud" ? "cloud" : undefined),
    isGenerating: taskData.isGenerating,
    isUnread: taskData.isUnread,
    isPinned: taskData.isPinned,
    isSuspended: taskData.isSuspended,
    needsPermission: taskData.needsPermission,
    taskRunStatus: taskData.taskRunStatus,
    runMode: taskData.runMode,
    originProduct: taskData.originProduct,
    slackThreadUrl: taskData.slackThreadUrl,
    prState,
    hasDiff,
    // The url is the early signal: a cloud run writes it the moment it opens the
    // PR, long before (or without ever) resolving the PR's state. A local run
    // has no cloud url, so the one the host cached against the task stands in.
    prUrl: taskData.cloudPrUrl ?? prUrl,
  };
}
