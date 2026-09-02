import {
  buildWorktreeAdoptionInput,
  getErrorTitle,
} from "@posthog/core/task-detail/taskInput";
import {
  TASK_SERVICE,
  type TaskService,
} from "@posthog/core/task-detail/taskService";
import { useService } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { toastError } from "@posthog/ui/features/notifications/errorDetails";
import { useProvisioningStore } from "@posthog/ui/features/provisioning/store";
import { useCreateTask } from "@posthog/ui/features/tasks/useTaskCrudMutations";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

/**
 * Starts a task in an existing task-less worktree: creates a promptless task
 * named after the branch, adopts the worktree for its workspace, and opens the
 * task's chat + shell.
 */
export function useStartTaskFromWorktree(mainRepoPath: string) {
  const taskService = useService<TaskService>(TASK_SERVICE);
  const { invalidateTasks } = useCreateTask();
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const [startingBranches, setStartingBranches] = useState<ReadonlySet<string>>(
    new Set(),
  );

  const startTask = useCallback(
    async (branch: string) => {
      setStartingBranches((prev) => new Set(prev).add(branch));
      try {
        const result = await taskService.createTask(
          buildWorktreeAdoptionInput({ repoPath: mainRepoPath, branch }),
          (output) => {
            invalidateTasks(output.task);
            void openTask(output.task);
          },
        );

        if (!result.success) {
          toastError(getErrorTitle(result.failedStep), result.error);
          return;
        }
        if (result.data.provisioningError) {
          // The task was kept for retry; the task view shows a retry prompt.
          useProvisioningStore
            .getState()
            .setFailed(result.data.task.id, result.data.provisioningError);
          toastError(
            getErrorTitle("workspace_creation"),
            result.data.provisioningError,
          );
        }
        track(ANALYTICS_EVENTS.TASK_CREATED, {
          auto_run: false,
          created_from: "sidebar-worktree",
          workspace_mode: "worktree",
          has_branch: true,
        });
        // The adopted worktree now has a task, so it leaves the adoptable list.
        void queryClient.invalidateQueries(
          trpc.workspace.listAdoptableWorktrees.queryFilter({ mainRepoPath }),
        );
      } catch (error) {
        toastError("Failed to start task from worktree", error);
      } finally {
        setStartingBranches((prev) => {
          const next = new Set(prev);
          next.delete(branch);
          return next;
        });
      }
    },
    [taskService, invalidateTasks, mainRepoPath, queryClient, trpc],
  );

  return { startTask, startingBranches };
}
