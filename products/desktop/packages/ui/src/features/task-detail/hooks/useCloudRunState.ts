import { deriveCloudRunState } from "@posthog/core/task-detail/cloudRunState";
import { extractCloudToolChangedFiles } from "@posthog/core/task-detail/cloudToolChanges";
import type { Task } from "@posthog/shared/domain-types";
import { useMemo } from "react";
import { shallow } from "zustand/shallow";
import { resolveCloudPrUrl } from "../../git-interaction/cloudPrUrl";
import { useSessionSelector } from "../../sessions/useSession";
import { pickFreshestTask } from "../../tasks/taskFreshness";
import { useTasks } from "../../tasks/useTasks";
import { useCloudEventSummary } from "./useCloudEventSummary";

export function useCloudRunState(taskId: string, task: Task, enabled = true) {
  const { data: tasks = [] } = useTasks();
  const freshTask = useMemo(
    () =>
      pickFreshestTask(
        task,
        tasks.find((t) => t.id === taskId),
      ),
    [task, taskId, tasks],
  );

  const session = useSessionSelector(
    enabled ? taskId : undefined,
    (session) =>
      session
        ? {
            taskRunId: session.taskRunId,
            cloudStatus: session.cloudStatus,
            cloudBranch: session.cloudBranch,
            cloudOutput: session.cloudOutput,
          }
        : undefined,
    shallow,
  );

  const prUrl = resolveCloudPrUrl(freshTask, session);
  const { effectiveBranch, repo, cloudStatus, isRunActive } =
    deriveCloudRunState(freshTask, session, prUrl);

  const summary = useCloudEventSummary(taskId, enabled);
  const fallbackFiles = useMemo(
    () => extractCloudToolChangedFiles(summary.toolCalls),
    [summary],
  );

  return {
    freshTask,
    session,
    prUrl,
    effectiveBranch,
    repo,
    cloudStatus,
    isRunActive,
    fallbackFiles,
    toolCalls: summary.toolCalls,
  };
}
