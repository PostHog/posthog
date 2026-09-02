import { getDiscardInfo } from "@posthog/core/task-detail/discardInfo";
import type { ChangedFile } from "@posthog/shared/domain-types";
import { useWorkspaceTRPC } from "@posthog/workspace-client/trpc";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { showMessageBox } from "../../../utils/dialog";
import { updateGitCacheFromSnapshot } from "../../git-interaction/utils/updateGitCache";

export function useDiscardFile(repoPath: string | undefined) {
  const queryClient = useQueryClient();
  const trpc = useWorkspaceTRPC();
  const discardFileChanges = useMutation(
    trpc.git.discardFileChanges.mutationOptions(),
  );

  return useCallback(
    async (file: ChangedFile, fileName: string) => {
      if (!repoPath) return;
      const { message, action } = getDiscardInfo(file, fileName);

      const dialogResult = await showMessageBox({
        type: "warning",
        title: "Discard changes",
        message,
        buttons: ["Cancel", action],
        defaultId: 1,
        cancelId: 0,
      });

      if (dialogResult.response !== 1) return;

      const result = await discardFileChanges.mutateAsync({
        directoryPath: repoPath,
        filePath: file.originalPath ?? file.path,
        fileStatus: file.status,
      });

      if (result.state) {
        updateGitCacheFromSnapshot(queryClient, repoPath, result.state);
      }
    },
    [repoPath, queryClient, discardFileChanges],
  );
}
