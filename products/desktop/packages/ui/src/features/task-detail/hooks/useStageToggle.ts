import type { ChangedFile } from "@posthog/shared/domain-types";
import { useWorkspaceTRPC } from "@posthog/workspace-client/trpc";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { logger } from "../../../shell/logger";
import { invalidateGitWorkingTreeQueries } from "../../git-interaction/gitCacheKeys";
import { updateGitCacheFromSnapshot } from "../../git-interaction/utils/updateGitCache";

const log = logger.scope("use-stage-toggle");

export function useStageToggle(repoPath: string | undefined) {
  const queryClient = useQueryClient();
  const trpc = useWorkspaceTRPC();
  const stageFiles = useMutation(trpc.git.stageFiles.mutationOptions());
  const unstageFiles = useMutation(trpc.git.unstageFiles.mutationOptions());

  return useCallback(
    async (file: ChangedFile) => {
      if (!repoPath) return;
      const endpoint = file.staged ? unstageFiles : stageFiles;
      try {
        const result = await endpoint.mutateAsync({
          directoryPath: repoPath,
          paths: [file.originalPath ?? file.path],
        });
        updateGitCacheFromSnapshot(queryClient, repoPath, result);
        invalidateGitWorkingTreeQueries(repoPath);
      } catch (error) {
        log.error("Failed to toggle staging", { file: file.path, error });
      }
    },
    [repoPath, queryClient, stageFiles, unstageFiles],
  );
}
