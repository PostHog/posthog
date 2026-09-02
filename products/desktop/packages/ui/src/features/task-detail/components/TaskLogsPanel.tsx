import { getTaskRepository } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { Box, Flex } from "@radix-ui/themes";
import { useCallback, useEffect } from "react";
import { BackgroundWrapper } from "../../../primitives/BackgroundWrapper";
import { ErrorBoundary } from "../../../primitives/ErrorBoundary";
import { useHostCapabilities } from "../../../shell/useHostCapabilities";
import { useFolders } from "../../folders/useFolders";
import { useDraftStore } from "../../message-editor/draftStore";
import { ProvisioningView } from "../../provisioning/ProvisioningView";
import { useProvisioningStore } from "../../provisioning/store";
import { SessionView } from "../../sessions/components/SessionView";
import { useSessionCallbacks } from "../../sessions/hooks/useSessionCallbacks";
import { useSessionConnection } from "../../sessions/hooks/useSessionConnection";
import { useSessionViewState } from "../../sessions/hooks/useSessionViewState";
import { useRestoreTask } from "../../suspension/useRestoreTask";
import { useSuspendedTaskIds } from "../../suspension/useSuspendedTaskIds";
import { useBranchMismatchDialog } from "../../workspace/useBranchMismatchDialog";
import { useWorkspaceLoaded } from "../../workspace/useWorkspace";
import { useCreateWorkspace } from "../../workspace/useWorkspaceMutations";
import { BranchMismatchDialog } from "../BranchMismatchDialog";
import { WorkspaceSetupPrompt } from "./WorkspaceSetupPrompt";

interface TaskLogsPanelProps {
  taskId: string;
  task: Task;
  /** Hide the message input — log-only view. */
  hideInput?: boolean;
}

export function TaskLogsPanel({ taskId, task, hideInput }: TaskLogsPanelProps) {
  // The folder-picker setup prompt is a local-workspace surface (local git repo
  // detection, folder picker). A cloud-only host has no local workspaces, so it
  // must never render — otherwise, in the window before a task is known-cloud
  // (isCloud derives from the workspace entry / latest run), the !isCloud branch
  // would mount it and resolve local-only services the host doesn't bind.
  const { localWorkspaces } = useHostCapabilities();
  const isWorkspaceLoaded = useWorkspaceLoaded();
  const { isPending: isCreatingWorkspace } = useCreateWorkspace();
  const repoKey = getTaskRepository(task);
  const { folders } = useFolders();
  const hasDirectoryMapping = repoKey
    ? folders.some((f) => f.remoteUrl === repoKey)
    : false;

  const suspendedTaskIds = useSuspendedTaskIds();
  const isSuspended = suspendedTaskIds.has(taskId);
  const { restoreTask, isRestoring } = useRestoreTask();

  const isProvisioning = useProvisioningStore((s) => s.activeTasks.has(taskId));
  const provisioningError = useProvisioningStore((s) => s.errors[taskId]);
  const clearProvisioning = useProvisioningStore((s) => s.clear);

  const { requestFocus } = useDraftStore((s) => s.actions);

  const {
    session,
    repoPath,
    isCloud,
    isRunning,
    hasError,
    events,
    isPromptPending,
    promptStartedAt,
    isInitializing,
    cloudBranch,
    cloudStatus,
    errorTitle,
    errorMessage,
    errorRetryable,
  } = useSessionViewState(taskId, task);

  useSessionConnection({
    taskId,
    task,
    session,
    repoPath,
    isCloud,
    isSuspended,
  });

  const {
    handleSendPrompt,
    handleCancelPrompt,
    handleRetry,
    handleNewSession,
    handleBashCommand,
  } = useSessionCallbacks({ taskId, task, session, repoPath });

  const { handleBeforeSubmit, dialogProps } = useBranchMismatchDialog({
    taskId,
    repoPath,
    onSendPrompt: handleSendPrompt,
  });

  const slackThreadUrl =
    typeof task.latest_run?.state?.slack_thread_url === "string"
      ? task.latest_run.state.slack_thread_url
      : undefined;

  useEffect(() => {
    requestFocus(taskId);
  }, [taskId, requestFocus]);

  // Once a retry provisions a workspace, drop the stale provisioning error so
  // the guard in ensureWorkspaceForTask stops firing and the retry prompt hides.
  useEffect(() => {
    if (repoPath && provisioningError) {
      clearProvisioning(taskId);
    }
  }, [repoPath, provisioningError, taskId, clearProvisioning]);

  const handleRestoreWorktree = useCallback(async () => {
    await restoreTask(taskId);
  }, [taskId, restoreTask]);

  if (isProvisioning) {
    return <ProvisioningView taskId={taskId} />;
  }

  // Worktree provisioning failed but the task was kept. Offer to retry setup
  // (worktree mode) on the existing task. Takes priority over the folder-picker
  // branch below, whose !hasDirectoryMapping gate wouldn't fire here since the
  // task's repo folder is already registered.
  if (
    localWorkspaces &&
    provisioningError &&
    !repoPath &&
    !isCloud &&
    !isSuspended &&
    isWorkspaceLoaded &&
    !isCreatingWorkspace
  ) {
    return (
      <BackgroundWrapper>
        <Box height="100%" width="100%">
          <WorkspaceSetupPrompt taskId={taskId} task={task} />
        </Box>
      </BackgroundWrapper>
    );
  }

  if (
    localWorkspaces &&
    !repoPath &&
    !isCloud &&
    !isSuspended &&
    isWorkspaceLoaded &&
    !hasDirectoryMapping &&
    !isCreatingWorkspace
  ) {
    return (
      <BackgroundWrapper>
        <Box height="100%" width="100%">
          <WorkspaceSetupPrompt taskId={taskId} task={task} />
        </Box>
      </BackgroundWrapper>
    );
  }

  return (
    <BackgroundWrapper>
      <Flex direction="column" height="100%" width="100%">
        <Box className="min-h-0 flex-1">
          <ErrorBoundary name="SessionView" resetKey={taskId}>
            <SessionView
              events={events}
              taskId={taskId}
              task={task}
              isRunning={isRunning}
              isSuspended={isSuspended}
              onRestoreWorktree={
                isSuspended ? handleRestoreWorktree : undefined
              }
              isRestoring={isRestoring}
              isPromptPending={isPromptPending}
              promptStartedAt={promptStartedAt}
              onBeforeSubmit={handleBeforeSubmit}
              onSendPrompt={handleSendPrompt}
              onBashCommand={isCloud ? undefined : handleBashCommand}
              onCancelPrompt={handleCancelPrompt}
              repoPath={repoPath}
              cloudBranch={cloudBranch}
              hasError={hasError}
              errorTitle={errorTitle}
              errorMessage={errorMessage ?? undefined}
              errorRetryable={errorRetryable}
              hideInput={hideInput}
              onRetry={handleRetry}
              onNewSession={isCloud ? undefined : handleNewSession}
              isInitializing={isInitializing}
              isCloud={isCloud}
              cloudStatus={cloudStatus}
              slackThreadUrl={slackThreadUrl}
            />
          </ErrorBoundary>
        </Box>
      </Flex>

      {dialogProps && <BranchMismatchDialog {...dialogProps} />}
    </BackgroundWrapper>
  );
}
