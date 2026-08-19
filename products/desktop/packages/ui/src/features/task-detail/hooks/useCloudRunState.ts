import { deriveCloudRunState } from "@posthog/core/task-detail/cloudRunState";
import { extractCloudToolChangedFiles } from "@posthog/core/task-detail/cloudToolChanges";
import type { Task } from "@posthog/shared/domain-types";
import { useMemo, useRef } from "react";
import { shallow } from "zustand/shallow";
import { resolveCloudPrUrl } from "../../git-interaction/cloudPrUrl";
import { useSessionSelector } from "../../sessions/useSession";
import { pickFreshestTask } from "../../tasks/taskFreshness";
import { useTasks } from "../../tasks/useTasks";
import { useCloudEventSummary } from "./useCloudEventSummary";

export function useCloudRunState(taskId: string, task: Task) {
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
    taskId,
    (current) =>
      current
        ? {
            taskRunId: current.taskRunId,
            cloudBranch: current.cloudBranch,
            cloudStatus: current.cloudStatus,
            cloudOutput: current.cloudOutput,
          }
        : undefined,
    shallow,
  );

  const prUrl = resolveCloudPrUrl(freshTask, session);
  const { effectiveBranch, repo, cloudStatus, isRunActive } =
    deriveCloudRunState(freshTask, session, prUrl);

  const summary = useCloudEventSummary(taskId);
  const fallbackFilesRef = useRef<
    | {
        taskId: string;
        revision: number;
        files: ReturnType<typeof extractCloudToolChangedFiles>;
      }
    | undefined
  >(undefined);
  if (
    fallbackFilesRef.current?.taskId !== taskId ||
    fallbackFilesRef.current.revision !== summary.changedFilesRevision
  ) {
    fallbackFilesRef.current = {
      taskId,
      revision: summary.changedFilesRevision,
      files: extractCloudToolChangedFiles(summary.toolCalls),
    };
  }
  const fallbackFiles = fallbackFilesRef.current.files;

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
