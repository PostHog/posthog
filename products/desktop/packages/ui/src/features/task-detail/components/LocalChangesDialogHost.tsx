import { useHostTRPC } from "@posthog/host-router/react";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { track } from "../../../shell/analytics";
import { useLocalChangesConfirmStore } from "../stores/localChangesConfirmStore";
import { LocalChangesDialog } from "./LocalChangesDialog";

const STASH_MESSAGE = "PostHog Desktop: local changes before task creation";
const STASH_ERROR = "Could not stash local changes. Check Git, then try again.";

export function LocalChangesDialogHost(): React.JSX.Element {
  const trpc = useHostTRPC();
  const isOpen = useLocalChangesConfirmStore((state) => state.isOpen);
  const repoPath = useLocalChangesConfirmStore((state) => state.repoPath);
  const stagedFiles = useLocalChangesConfirmStore((state) => state.stagedFiles);
  const unstagedFiles = useLocalChangesConfirmStore(
    (state) => state.unstagedFiles,
  );
  const untrackedFiles = useLocalChangesConfirmStore(
    (state) => state.untrackedFiles,
  );
  const cancel = useLocalChangesConfirmStore((state) => state.cancel);
  const continueTask = useLocalChangesConfirmStore((state) => state.continue);
  const stashAndContinue = useLocalChangesConfirmStore(
    (state) => state.stashAndContinue,
  );
  const [stashError, setStashError] = useState<string | null>(null);
  const stashMutation = useMutation(trpc.focus.stash.mutationOptions());

  useEffect(() => {
    if (!isOpen) setStashError(null);
  }, [isOpen]);

  const eventProperties = {
    staged_file_count: stagedFiles.length,
    unstaged_file_count: unstagedFiles.length,
    untracked_file_count: untrackedFiles.length,
  };

  const handleCancel = (): void => {
    track(ANALYTICS_EVENTS.LOCAL_CHANGES_WARNING_ACTION, {
      action: "cancel",
      ...eventProperties,
    });
    cancel();
  };

  const handleContinue = (): void => {
    track(ANALYTICS_EVENTS.LOCAL_CHANGES_WARNING_ACTION, {
      action: "continue",
      ...eventProperties,
    });
    continueTask();
  };

  const handleStashAndContinue = async (): Promise<void> => {
    setStashError(null);
    try {
      const result = await stashMutation.mutateAsync({
        repoPath,
        message: STASH_MESSAGE,
      });
      if (!result.success) {
        track(ANALYTICS_EVENTS.LOCAL_CHANGES_WARNING_ACTION, {
          action: "stash_and_continue",
          result: "failure",
          ...eventProperties,
        });
        setStashError(STASH_ERROR);
        return;
      }
      track(ANALYTICS_EVENTS.LOCAL_CHANGES_WARNING_ACTION, {
        action: "stash_and_continue",
        result: "success",
        ...eventProperties,
      });
      stashAndContinue();
    } catch {
      track(ANALYTICS_EVENTS.LOCAL_CHANGES_WARNING_ACTION, {
        action: "stash_and_continue",
        result: "failure",
        ...eventProperties,
      });
      setStashError(STASH_ERROR);
    }
  };

  return (
    <LocalChangesDialog
      open={isOpen}
      stagedFiles={stagedFiles}
      unstagedFiles={unstagedFiles}
      untrackedFiles={untrackedFiles}
      isStashing={stashMutation.isPending}
      stashError={stashError}
      onOpenChange={(open) => {
        if (!open) handleCancel();
      }}
      onCancel={handleCancel}
      onContinue={handleContinue}
      onStashAndContinue={() => void handleStashAndContinue()}
    />
  );
}
