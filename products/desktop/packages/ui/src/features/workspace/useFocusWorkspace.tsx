import {
  buildEnableFocusParams,
  canFocusWorkspace,
  focusTerminalKey,
} from "@posthog/core/workspace/focusWorkspace";
import { useCallback, useMemo } from "react";
import { toast } from "../../primitives/toast";
import {
  selectIsFocusedOnWorktree,
  selectIsLoading,
  useFocusStore,
} from "../focus/focusStore";
import { showFocusSuccessToast } from "../focus/focusToast";
import { toastError } from "../notifications/errorDetails";
import { useTerminalStore } from "../terminal/terminalStore";
import { useWorkspace } from "./useWorkspace";

export function useFocusWorkspace(taskId: string) {
  const workspace = useWorkspace(taskId);
  const focusSession = useFocusStore((s) => s.session);
  const isFocusLoading = useFocusStore(selectIsLoading);
  const enableFocus = useFocusStore((s) => s.enableFocus);
  const disableFocus = useFocusStore((s) => s.disableFocus);

  const isFocused = useFocusStore(
    selectIsFocusedOnWorktree(workspace?.worktreePath ?? ""),
  );

  const getFocusTerminalKey = useCallback(
    (branch: string) => focusTerminalKey(taskId, branch),
    [taskId],
  );

  const focusTerminalKeyValue = useMemo(() => {
    if (!focusSession) return null;
    return getFocusTerminalKey(focusSession.branch);
  }, [focusSession, getFocusTerminalKey]);

  const handleUnfocus = useCallback(async () => {
    if (!focusSession) {
      toast.error("Could not return to original branch", {
        description: "No focused workspace found",
      });
      return;
    }

    const hadStash = !!focusSession.mainStashRef;
    const terminalKey = getFocusTerminalKey(focusSession.branch);
    const result = await disableFocus();
    if (result.success) {
      useTerminalStore.getState().clearTerminalState(terminalKey);
      toast.success(`Returned to ${focusSession.originalBranch}`, {
        description:
          result.stashPopWarning ??
          (hadStash ? "Your stashed changes were restored." : undefined),
      });
    } else {
      toastError(
        `Could not return to ${focusSession.originalBranch}`,
        result.error,
      );
    }
  }, [focusSession, disableFocus, getFocusTerminalKey]);

  const handleFocus = useCallback(async () => {
    if (!workspace) return;

    const params = buildEnableFocusParams(workspace);
    if (!canFocusWorkspace(workspace) || !params) {
      toast.error("Could not edit workspace", {
        description: "Only worktree-mode workspaces can be edited",
      });
      return;
    }

    const result = await enableFocus(params);

    if (result.success) {
      showFocusSuccessToast(params.branch, result);
    } else {
      toastError("Could not edit workspace", result.error);
    }
  }, [workspace, enableFocus]);

  const handleToggleFocus = useCallback(() => {
    if (isFocused) {
      handleUnfocus();
    } else {
      handleFocus();
    }
  }, [isFocused, handleUnfocus, handleFocus]);

  return {
    workspace,
    focusSession,
    isFocusLoading,
    isFocused,
    focusTerminalKey: focusTerminalKeyValue,
    handleFocus,
    handleUnfocus,
    handleToggleFocus,
  };
}
