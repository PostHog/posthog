import type { ChangedFile, Task } from "@posthog/shared/domain-types";
import { useMemo } from "react";
import {
  useBranchChangedFiles,
  usePrChangedFiles,
} from "../../git-interaction/useGitQueries";
import { useCloudRunState } from "./useCloudRunState";

const EMPTY_FILES: ChangedFile[] = [];

export function useCloudChangedFiles(
  taskId: string,
  task: Task,
  isActive = true,
) {
  const cloudRunState = useCloudRunState(taskId, task);
  const { prUrl, effectiveBranch, repo, isRunActive } = cloudRunState;

  const {
    data: prFiles,
    isPending: prPending,
    isError: prError,
  } = usePrChangedFiles(isActive ? prUrl : null, isRunActive);

  const {
    data: branchFiles,
    isPending: branchPending,
    isError: branchError,
  } = useBranchChangedFiles(
    isActive && !prUrl ? repo : null,
    isActive && !prUrl ? effectiveBranch : null,
    isRunActive,
  );

  const remoteFiles = useMemo((): ChangedFile[] => {
    const files = prUrl ? prFiles : branchFiles;
    return files ?? EMPTY_FILES;
  }, [prUrl, prFiles, branchFiles]);

  const isLoading = prUrl ? prPending : effectiveBranch ? branchPending : false;
  const hasError = prUrl ? prError : effectiveBranch ? branchError : false;

  const changedFiles =
    remoteFiles.length > 0 ? remoteFiles : cloudRunState.fallbackFiles;

  return {
    ...cloudRunState,
    changedFiles,
    remoteFiles,
    reviewFiles: changedFiles,
    isLoading,
    hasError,
  };
}
