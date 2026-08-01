import {
  type BranchMismatchDialogAction,
  buildBranchMismatchAnalyticsEvent,
  buildCheckoutBranchRequest,
  decideBeforeSubmit,
  resolveSwitchErrorMessage,
} from "@posthog/core/workspace/branchMismatchDialog";
import { useHostTRPC } from "@posthog/host-router/react";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useMutation } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { track } from "../../shell/analytics";
import { logger } from "../../shell/logger";
import { invalidateGitBranchQueries } from "../git-interaction/gitCacheKeys";
import { useGitQueries } from "../git-interaction/useGitQueries";
import { useBranchMismatchGuard } from "./useBranchMismatch";

const log = logger.scope("branch-mismatch");

interface UseBranchMismatchDialogOptions {
  taskId: string;
  repoPath: string | null;
  onSendPrompt: (text: string) => void;
}

export function useBranchMismatchDialog({
  taskId,
  repoPath,
  onSendPrompt,
}: UseBranchMismatchDialogOptions) {
  const { shouldWarn, linkedBranch, currentBranch, dismissWarning } =
    useBranchMismatchGuard(taskId);

  // State drives dialog visibility (`open`), refs avoid stale closures in
  // mutation callbacks (onSuccess / handleContinue) that capture at mount time.
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const pendingMessageRef = useRef<string | null>(null);
  const pendingClearRef = useRef<(() => void) | null>(null);
  const onSendPromptRef = useRef(onSendPrompt);
  onSendPromptRef.current = onSendPrompt;
  const [switchError, setSwitchError] = useState<string | null>(null);

  const { hasChanges: hasUncommittedChanges } = useGitQueries(
    repoPath ?? undefined,
  );

  const emitAction = useCallback(
    (action: BranchMismatchDialogAction) => {
      const analytics = buildBranchMismatchAnalyticsEvent(action, {
        taskId,
        linkedBranch,
        currentBranch,
        hasUncommittedChanges,
      });
      if (!analytics) return;
      if (analytics.event === ANALYTICS_EVENTS.BRANCH_MISMATCH_WARNING_SHOWN) {
        track(analytics.event, analytics.properties);
      } else {
        track(analytics.event, analytics.properties);
      }
    },
    [taskId, linkedBranch, currentBranch, hasUncommittedChanges],
  );

  const trpc = useHostTRPC();
  const { mutate: checkoutBranch, isPending: isSwitching } = useMutation(
    trpc.git.checkoutBranch.mutationOptions({
      onSuccess: () => {
        if (repoPath) invalidateGitBranchQueries(repoPath);
        dismissWarning();
        pendingClearRef.current?.();
        pendingClearRef.current = null;
        const message = pendingMessageRef.current;
        if (message) onSendPromptRef.current(message);
        setPendingMessage(null);
        pendingMessageRef.current = null;
      },
      onError: (error) => {
        log.error("Failed to switch branch", error);
        setSwitchError(resolveSwitchErrorMessage(error));
      },
    }),
  );

  const handleBeforeSubmit = useCallback(
    (text: string, clearEditor: () => void): boolean => {
      if (!decideBeforeSubmit(shouldWarn)) {
        setPendingMessage(text);
        pendingMessageRef.current = text;
        pendingClearRef.current = clearEditor;
        emitAction("shown");
        return false;
      }
      return true;
    },
    [shouldWarn, emitAction],
  );

  const handleSwitch = useCallback(() => {
    const request = buildCheckoutBranchRequest(repoPath, linkedBranch);
    if (!request) return;
    setSwitchError(null);
    emitAction("switch");
    checkoutBranch(request);
  }, [linkedBranch, repoPath, emitAction, checkoutBranch]);

  const handleContinue = useCallback(() => {
    emitAction("continue");
    dismissWarning();
    pendingClearRef.current?.();
    pendingClearRef.current = null;
    const message = pendingMessageRef.current;
    if (message) onSendPromptRef.current(message);
    setPendingMessage(null);
    pendingMessageRef.current = null;
    setSwitchError(null);
  }, [dismissWarning, emitAction]);

  const handleCancel = useCallback(() => {
    if (isSwitching) return;
    emitAction("cancel");
    setPendingMessage(null);
    pendingMessageRef.current = null;
    pendingClearRef.current = null;
    setSwitchError(null);
  }, [emitAction, isSwitching]);

  const dialogProps =
    linkedBranch && currentBranch
      ? {
          open: pendingMessage !== null,
          linkedBranch,
          currentBranch,
          hasUncommittedChanges,
          switchError,
          onSwitch: handleSwitch,
          onContinue: handleContinue,
          onCancel: handleCancel,
          isSwitching,
        }
      : null;

  return { handleBeforeSubmit, dialogProps };
}
