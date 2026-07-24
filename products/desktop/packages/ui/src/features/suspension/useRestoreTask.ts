import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import {
  invalidateGitBranchQueries,
  invalidateGitWorkingTreeQueries,
} from "@posthog/ui/features/git-interaction/gitCacheKeys";
import { toast } from "@posthog/ui/primitives/toast";
import { logger } from "@posthog/ui/shell/logger";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { WORKSPACE_QUERY_KEY } from "../workspace/identifiers";

const log = logger.scope("restore-task");

export function useRestoreTask() {
  const trpc = useHostTRPC();
  const hostClient = useHostTRPCClient();
  const queryClient = useQueryClient();
  const [isRestoring, setIsRestoring] = useState(false);

  const suspensionPathKey = trpc.suspension.pathFilter().queryKey;
  const restoreMutation = useMutation(
    trpc.suspension.restore.mutationOptions(),
  );

  const restoreTask = async (taskId: string, recreateBranch?: boolean) => {
    setIsRestoring(true);

    try {
      const result = await restoreMutation.mutateAsync({
        taskId,
        recreateBranch,
      });

      queryClient.invalidateQueries({ queryKey: suspensionPathKey });
      queryClient.invalidateQueries({ queryKey: WORKSPACE_QUERY_KEY });

      const workspaces = await hostClient.workspace.getAll.query();
      const workspace = workspaces[taskId] ?? null;
      const repoPath = workspace?.worktreePath ?? workspace?.folderPath;
      if (repoPath) {
        invalidateGitWorkingTreeQueries(repoPath);
        invalidateGitBranchQueries(repoPath);
      }

      log.info("Task restored", {
        taskId,
        worktreeName: result.worktreeName,
      });

      return result;
    } catch (error) {
      log.error("Failed to restore task", error);

      const message =
        error instanceof Error ? error.message : "Failed to restore worktree";

      if (message.includes("is already used by worktree")) {
        toast.error(
          "Branch is in use by another worktree. Try restoring with a new branch.",
        );
      } else {
        toast.error(message);
      }

      throw error;
    } finally {
      setIsRestoring(false);
    }
  };

  return { restoreTask, isRestoring };
}
