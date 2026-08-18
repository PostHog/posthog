import type { WorkspaceMode } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useTaskStatusInput } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import { useBluebirdFlag } from "@posthog/ui/features/feature-flags/useBluebirdFlag";
import {
  TaskBadgeStack,
  TaskStatusDot,
  TaskStatusTooltips,
} from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import {
  type TaskStatusInput,
  taskDot,
} from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { WorkspaceModeBadge } from "@posthog/ui/features/task-detail/components/WorkspaceModeBadge";
import type { ReactNode } from "react";

/**
 * The session's state for the window header, or `null` where the header keeps
 * its old workspace-mode glyph — outside project-bluebird, and before the
 * task's state has landed.
 */
function useHeaderStatus(task: Task): TaskStatusInput | null {
  const bluebird = useBluebirdFlag();
  // The PR lookup is the one part that reaches the host, so it goes no further
  // than the surface that draws it.
  const status = useTaskStatusInput(task, { withPrStatus: bluebird });
  return bluebird ? status : null;
}

/**
 * The header's marks are the space list's, so a session reads the same open in
 * front of you as it does in the list you opened it from. `no-drag` because the
 * header is a window drag region, and a mark whose tooltip never opens is a
 * mark that says nothing.
 */
function HeaderMarks({ children }: { children: ReactNode }) {
  return (
    <TaskStatusTooltips>
      <span className="no-drag flex shrink-0 items-center">{children}</span>
    </TaskStatusTooltips>
  );
}

/**
 * The mark before the session's title in the window header: its state dot,
 * whose tooltip names the state in the same words the space list uses.
 *
 * It replaces the cloud / laptop / worktree glyph, which said where the run
 * lives and nothing about whether it wants anything from you. Where the run
 * lives moves to {@link TaskHeaderBadges}, and in that vocabulary the cloud is
 * silent: running there is what a session does by default, so only the local
 * exception earns a badge.
 */
export function TaskHeaderMark({
  task,
  mode,
  checkoutPath,
}: {
  task: Task;
  mode?: WorkspaceMode;
  /** Directory the task runs in, for the workspace-mode glyph's tooltip. */
  checkoutPath?: string | null;
}) {
  const status = useHeaderStatus(task);
  if (!status) {
    return <WorkspaceModeBadge mode={mode} checkoutPath={checkoutPath} />;
  }
  return (
    <HeaderMarks>
      <TaskStatusDot dot={taskDot(status)} />
    </HeaderMarks>
  );
}

/**
 * The identity badges that ride after the title — where the session came from,
 * whether it runs on this machine, what came out of it — drawn exactly as a
 * space row draws them. Nothing at all when there is nothing to say, rather
 * than an empty group whose padding still moves the title's neighbours.
 */
export function TaskHeaderBadges({ task }: { task: Task }) {
  const status = useHeaderStatus(task);
  if (!status) return null;
  return (
    <HeaderMarks>
      <TaskBadgeStack status={status} pinned={status.isPinned} />
    </HeaderMarks>
  );
}
