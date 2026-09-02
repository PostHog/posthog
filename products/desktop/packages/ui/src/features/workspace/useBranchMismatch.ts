import {
  isBranchMismatch,
  shouldWarnBranchMismatch,
} from "@posthog/core/workspace/branchMismatch";
import { useCallback, useEffect, useRef } from "react";
import { create } from "zustand";
import { useWorkspace } from "./useWorkspace";

interface BranchWarningState {
  dismissed: Record<string, boolean>;
  dismiss: (taskId: string) => void;
  reset: (taskId: string) => void;
}

export const useBranchWarningStore = create<BranchWarningState>()((set) => ({
  dismissed: {},
  dismiss: (taskId) =>
    set((state) => ({
      dismissed: { ...state.dismissed, [taskId]: true },
    })),
  reset: (taskId) =>
    set((state) => ({
      dismissed: { ...state.dismissed, [taskId]: false },
    })),
}));

function useBranchMismatch(taskId: string) {
  const workspace = useWorkspace(taskId);
  const linkedBranch = workspace?.linkedBranch ?? null;
  const currentBranch = workspace?.branchName ?? null;
  const isMismatch = isBranchMismatch(linkedBranch, currentBranch);

  const branchWarningDismissed = useBranchWarningStore(
    (s) => s.dismissed[taskId] ?? false,
  );
  const reset = useBranchWarningStore((s) => s.reset);

  const prevBranchRef = useRef(currentBranch);
  useEffect(() => {
    if (prevBranchRef.current !== currentBranch) {
      prevBranchRef.current = currentBranch;
      reset(taskId);
    }
  }, [currentBranch, taskId, reset]);

  const shouldWarn = shouldWarnBranchMismatch(
    linkedBranch,
    currentBranch,
    branchWarningDismissed,
  );

  return {
    linkedBranch,
    currentBranch,
    isMismatch,
    shouldWarn,
  };
}

export function useBranchMismatchGuard(taskId: string) {
  const { shouldWarn, linkedBranch, currentBranch } = useBranchMismatch(taskId);
  const dismiss = useBranchWarningStore((s) => s.dismiss);

  const dismissWarning = useCallback(() => {
    dismiss(taskId);
  }, [dismiss, taskId]);

  return { shouldWarn, linkedBranch, currentBranch, dismissWarning };
}
