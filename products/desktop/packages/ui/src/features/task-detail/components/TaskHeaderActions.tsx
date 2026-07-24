import { Cloud, Spinner } from "@phosphor-icons/react";
import { Button as QuillButton } from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { AutoresearchHeaderButton } from "@posthog/ui/features/autoresearch/AutoresearchHeaderButton";
import { useDiffStatsToggle } from "@posthog/ui/features/code-review/hooks/useDiffStatsToggle";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { DiffStatsBadge } from "@posthog/ui/features/diff-stats/DiffStatsBadge";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { BranchSelector } from "@posthog/ui/features/git-interaction/components/BranchSelector";
import { CloudGitInteractionHeader } from "@posthog/ui/features/git-interaction/components/CloudGitInteractionHeader";
import { TaskActionsMenu } from "@posthog/ui/features/git-interaction/components/TaskActionsMenu";
import { HandoffConfirmDialog } from "@posthog/ui/features/sessions/components/HandoffConfirmDialog";
import { StopCloudRunButton } from "@posthog/ui/features/sessions/components/StopCloudRunButton";
import { useHandoffDialogStore } from "@posthog/ui/features/sessions/handoffDialogStore";
import { useSessionCallbacks } from "@posthog/ui/features/sessions/hooks/useSessionCallbacks";
import { useSessionForTask } from "@posthog/ui/features/sessions/useSession";
import { SkillButtonsMenu } from "@posthog/ui/features/skill-buttons/components/SkillButtonsMenu";
import {
  useWorkspace,
  useWorkspaceLoaded,
} from "@posthog/ui/features/workspace/useWorkspace";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { Flex } from "@radix-ui/themes";
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
      <div className="no-drag flex items-center">
        <QuillButton
          variant="outline"
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
        </QuillButton>
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

function TaskDiffStatsBadge({ task }: { task: Task }) {
  const { filesChanged, linesAdded, linesRemoved, isOpen, toggle } =
    useDiffStatsToggle(task, "split");
  return (
    <Tooltip
      content={isOpen ? "Close review panel" : "Open review panel"}
      shortcut={formatHotkey(SHORTCUTS.TOGGLE_REVIEW_PANEL)}
      side="bottom"
    >
      <DiffStatsBadge
        filesChanged={filesChanged}
        linesAdded={linesAdded}
        linesRemoved={linesRemoved}
        active={isOpen}
        onClick={toggle}
      />
    </Tooltip>
  );
}

export function TaskHeaderActions({ task }: { task: Task }) {
  const workspace = useWorkspace(task.id);
  const workspaceLoaded = useWorkspaceLoaded();
  const isCloudTask = workspace?.mode === "cloud";

  return (
    <Flex
      align="center"
      justify="end"
      gap="1"
      pr="1"
      pl="1"
      className="h-full max-w-[50%] shrink-0 overflow-hidden"
    >
      <div className="no-drag">
        <SkillButtonsMenu taskId={task.id} />
      </div>
      <div className="no-drag">
        <AutoresearchHeaderButton taskId={task.id} />
      </div>
      {workspace && (workspace.branchName || workspace.baseBranch) && (
        <div className="no-drag flex h-full min-w-0 items-center">
          <BranchSelector
            repoPath={workspace.worktreePath ?? workspace.folderPath ?? null}
            currentBranch={workspace.branchName ?? workspace.baseBranch ?? null}
            taskId={task.id}
          />
        </div>
      )}
      <TaskDiffStatsBadge task={task} />

      {workspaceLoaded && (
        <>
          {isCloudTask ? (
            <>
              <StopCloudRunButton taskId={task.id} />
              <CloudGitInteractionHeader taskId={task.id} task={task} />
            </>
          ) : (
            <LocalHandoffButton taskId={task.id} task={task} />
          )}
          <TaskActionsMenu taskId={task.id} isCloud={isCloudTask} />
        </>
      )}
    </Flex>
  );
}
