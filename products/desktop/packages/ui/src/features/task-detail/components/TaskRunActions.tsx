import { Cloud, Spinner } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { CloudGitInteractionHeader } from "@posthog/ui/features/git-interaction/components/CloudGitInteractionHeader";
import { TaskActionsMenu } from "@posthog/ui/features/git-interaction/components/TaskActionsMenu";
import { HandoffConfirmDialog } from "@posthog/ui/features/sessions/components/HandoffConfirmDialog";
import { StopCloudRunButton } from "@posthog/ui/features/sessions/components/StopCloudRunButton";
import { useHandoffDialogStore } from "@posthog/ui/features/sessions/handoffDialogStore";
import { useSessionCallbacks } from "@posthog/ui/features/sessions/hooks/useSessionCallbacks";
import { useSessionForTask } from "@posthog/ui/features/sessions/useSession";
import {
  useIsCloudTask,
  useWorkspace,
  useWorkspaceLoaded,
} from "@posthog/ui/features/workspace/useWorkspace";
import { useState } from "react";

const CLOUD_HANDOFF_FLAG = "phc-cloud-handoff";

function LocalHandoffButton({ taskId, task }: { taskId: string; task: Task }) {
  const session = useSessionForTask(taskId);
  const workspace = useWorkspace(taskId);
  const repoPath = workspace?.folderPath ?? null;
  const authStatus = useAuthStateValue((s) => s.status);
  const cloudHandoffEnabled =
    useFeatureFlag(CLOUD_HANDOFF_FLAG) || import.meta.env.DEV;
  const { initiateHandoffToCloud } = useSessionCallbacks({
    taskId,
    task,
    session: session ?? undefined,
    repoPath,
  });

  const confirmOpen = useHandoffDialogStore((s) => s.confirmOpen);
  const direction = useHandoffDialogStore((s) => s.direction);
  const branchName = useHandoffDialogStore((s) => s.branchName);
  const openConfirm = useHandoffDialogStore((s) => s.openConfirm);
  const closeConfirm = useHandoffDialogStore((s) => s.closeConfirm);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (authStatus !== "authenticated") return null;
  if (!cloudHandoffEnabled) return null;

  const handleConfirm = async () => {
    setError(null);
    setIsSubmitting(true);
    try {
      await initiateHandoffToCloud();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Handoff failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  const inProgress = session?.handoffInProgress ?? false;

  return (
    <>
      <div className="flex items-center">
        <Button
          size="sm"
          disabled={inProgress}
          onClick={() =>
            openConfirm(taskId, "to-cloud", workspace?.branchName ?? null)
          }
        >
          {inProgress ? (
            <Spinner size={14} className="shrink-0 animate-spin" />
          ) : (
            <Cloud size={14} weight="regular" className="shrink-0" />
          )}
          {inProgress ? "Transferring..." : "Continue in cloud"}
        </Button>
      </div>
      {confirmOpen && direction === "to-cloud" && (
        <HandoffConfirmDialog
          open={confirmOpen}
          onOpenChange={(open) => {
            if (!open) {
              closeConfirm();
              setError(null);
            }
          }}
          direction="to-cloud"
          branchName={branchName}
          onConfirm={handleConfirm}
          isSubmitting={isSubmitting}
          error={error}
        />
      )}
    </>
  );
}

export function TaskRunActions({ task }: { task: Task }) {
  const workspaceLoaded = useWorkspaceLoaded();
  const isCloudTask = useIsCloudTask(task);

  if (!workspaceLoaded) return null;

  return (
    <div className="flex w-full flex-wrap items-center justify-end gap-1">
      {isCloudTask ? (
        <>
          <CloudGitInteractionHeader taskId={task.id} task={task} />
          <StopCloudRunButton taskId={task.id} />
        </>
      ) : (
        <LocalHandoffButton taskId={task.id} task={task} />
      )}
      <TaskActionsMenu taskId={task.id} isCloud={isCloudTask} />
    </div>
  );
}
