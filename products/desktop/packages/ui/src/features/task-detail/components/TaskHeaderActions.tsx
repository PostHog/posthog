import type { Task } from "@posthog/shared/domain-types";
import { AutoresearchHeaderButton } from "@posthog/ui/features/autoresearch/AutoresearchHeaderButton";
import { useDiffStatsToggle } from "@posthog/ui/features/code-review/hooks/useDiffStatsToggle";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { DiffStatsBadge } from "@posthog/ui/features/diff-stats/DiffStatsBadge";
import { BranchSelector } from "@posthog/ui/features/git-interaction/components/BranchSelector";
import { TaskActionsMenu } from "@posthog/ui/features/git-interaction/components/TaskActionsMenu";
import { useReviewInRightPanel } from "@posthog/ui/features/navigation/useReviewInRightPanel";
import {
  useIsCloudTask,
  useWorkspace,
  useWorkspaceLoaded,
} from "@posthog/ui/features/workspace/useWorkspace";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { TaskAnalysisButton } from "./TaskAnalysisButton";
import { TaskOverflowMenu } from "./TaskOverflowMenu";

function TaskDiffStatsBadge({ task }: { task: Task }) {
  const { filesChanged, linesAdded, linesRemoved, isOpen, toggle } =
    useDiffStatsToggle(task);
  return (
    <Tooltip
      content={isOpen ? "Close diff view" : "Open diff view"}
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
  const isCloudTask = useIsCloudTask(task);
  // The badge is this row's way into the review, so it comes off where the
  // right panel's switcher already offers one.
  const showDiffBadge = !useReviewInRightPanel();

  return (
    <div className="flex h-full max-w-[50%] shrink-0 items-center justify-end gap-1 overflow-hidden px-1">
      <div className="no-drag">
        <AutoresearchHeaderButton taskId={task.id} />
      </div>
      <div className="no-drag">
        <TaskAnalysisButton task={task} />
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
      {showDiffBadge && <TaskDiffStatsBadge task={task} />}

      {workspaceLoaded && (
        <TaskActionsMenu taskId={task.id} isCloud={isCloudTask} />
      )}
      {/* Acting on the task itself needs nothing from the workspace, so the
          menu stays put while the rest of the row is still resolving. */}
      <TaskOverflowMenu task={task} />
    </div>
  );
}
