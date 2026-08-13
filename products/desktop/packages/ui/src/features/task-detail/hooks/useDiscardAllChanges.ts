import { useWorkspaceTRPC } from "@posthog/workspace-client/trpc";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { showMessageBox } from "../../../utils/dialog";
import { updateGitCacheFromSnapshot } from "../../git-interaction/utils/updateGitCache";

export function useDiscardAllChanges(repoPath: string | undefined) {
  const queryClient = useQueryClient();
  const trpc = useWorkspaceTRPC();
  const discardAllChanges = useMutation(
    trpc.git.discardAllChanges.mutationOptions(),
  );

  return useCallback(async () => {
    if (!repoPath) return;

    const dialogResult = await showMessageBox({
      type: "warning",
      title: "Revert all local changes",
      message:
        "This will discard all uncommitted changes, including new files. A backup will be kept in a git stash.",
      buttons: ["Cancel", "Revert All"],
      defaultId: 1,
      cancelId: 0,
    });

    if (dialogResult.response !== 1) return;

    const result = await discardAllChanges.mutateAsync({
      directoryPath: repoPath,
    });

    if (result.state) {
      updateGitCacheFromSnapshot(queryClient, repoPath, result.state);
    }
  }, [repoPath, queryClient, discardAllChanges]);
}
