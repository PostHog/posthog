import { DotsThree } from "@phosphor-icons/react";
import { isTerminalStatus } from "@posthog/core/cloud-task/schemas";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { isTaskUnread } from "@posthog/core/sidebar/buildSidebarData";
import { taskActivityAt } from "@posthog/core/tasks/taskActivity";
import { useService } from "@posthog/di/react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
  Button as QuillButton,
} from "@posthog/quill";
import { sessionSupportsSideQuestion } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useTaskArchive } from "@posthog/ui/features/archive/useTaskArchive";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { StopCloudRunDialog } from "@posthog/ui/features/sessions/components/StopCloudRunDialog";
import { startSessionSummary } from "@posthog/ui/features/sessions/sessionSummary";
import { useSideQuestionStore } from "@posthog/ui/features/sessions/sideQuestionStore";
import { useSessionSelector } from "@posthog/ui/features/sessions/useSession";
import { TaskDotMark } from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import { taskDot } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { useState } from "react";
import { shallow } from "zustand/shallow";

/**
 * The task header's overflow menu: everything that acts on the task itself
 * rather than on its branch or its diff.
 */
export function TaskOverflowMenu({ task }: { task: Task }) {
  const { isCloud, cloudStatus, stopRequested, taskRunId, supportsSummary } =
    useSessionSelector(
      task.id,
      (session) => ({
        isCloud: session?.isCloud ?? false,
        cloudStatus: session?.cloudStatus ?? null,
        stopRequested: session?.stopRequested ?? false,
        taskRunId: session?.taskRunId ?? null,
        supportsSummary: session ? sessionSupportsSideQuestion(session) : false,
      }),
      shallow,
    );
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  // The store holds one side question per task, so a pending "/btw" answer
  // blocks a summary too.
  const sideQuestionPending = useSideQuestionStore(
    (s) => s.byTaskId[task.id]?.status === "pending",
  );
  const [stopConfirmOpen, setStopConfirmOpen] = useState(false);
  const { timestamps, markAsViewed, markAsUnread } = useTaskViewed();
  const activityAt = taskActivityAt(task);
  const isUnread = isTaskUnread(activityAt, timestamps[task.id]);
  const { requestArchive, dialog: archiveDialog } = useTaskArchive(task, {
    navigateUnscoped: !task.channel,
  });

  const canStop = isCloud && !isTerminalStatus(cloudStatus);
  const canSummarize = supportsSummary && taskRunId !== null;

  return (
    <>
      <div className="no-drag flex items-center">
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <QuillButton
                variant="outline"
                size="sm"
                aria-label="Task actions"
                className="px-1.5"
              />
            }
          >
            <DotsThree size={16} weight="bold" className="shrink-0" />
          </DropdownMenuTrigger>
          {/* quill pins a menu to its anchor's width, and this anchor is the
              width of a glyph. */}
          <DropdownMenuContent align="end" className="w-auto">
            {canStop && (
              <DropdownMenuItem
                disabled={stopRequested}
                onClick={() => setStopConfirmOpen(true)}
              >
                {stopRequested ? "Stopping..." : "Stop run"}
              </DropdownMenuItem>
            )}
            {canSummarize && (
              <DropdownMenuItem
                disabled={sideQuestionPending}
                onClick={() => {
                  if (!taskRunId) return;
                  startSessionSummary(sessionService, task.id, taskRunId);
                }}
              >
                Summarize for another agent
              </DropdownMenuItem>
            )}
            <DropdownMenuItem
              onClick={() =>
                isUnread
                  ? markAsViewed(task.id, Date.parse(activityAt))
                  : markAsUnread(task.id, Date.parse(activityAt))
              }
            >
              <TaskDotMark dot={taskDot({ isUnread })} />
              {isUnread ? "Mark as read" : "Mark as unread"}
            </DropdownMenuItem>
            <DropdownMenuItem onClick={requestArchive}>
              Archive
              <DropdownMenuShortcut>
                {formatHotkey(SHORTCUTS.ARCHIVE_TASK)}
              </DropdownMenuShortcut>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <StopCloudRunDialog
        open={stopConfirmOpen}
        taskId={task.id}
        title="Stop run"
        buttonLabel="Stop run"
        onOpenChange={setStopConfirmOpen}
      />
      {archiveDialog}
    </>
  );
}
