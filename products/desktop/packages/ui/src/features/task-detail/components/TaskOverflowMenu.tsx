import { DotsThree } from "@phosphor-icons/react";
import { isTerminalStatus } from "@posthog/core/cloud-task/schemas";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
  Button as QuillButton,
} from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { useTaskArchive } from "@posthog/ui/features/archive/useTaskArchive";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { StopCloudRunDialog } from "@posthog/ui/features/sessions/components/StopCloudRunDialog";
import { useSessionSelector } from "@posthog/ui/features/sessions/useSession";
import { useState } from "react";
import { shallow } from "zustand/shallow";

/**
 * The task header's overflow menu: everything that acts on the task itself
 * rather than on its branch or its diff.
 */
export function TaskOverflowMenu({ task }: { task: Task }) {
  const { isCloud, cloudStatus, stopRequested } = useSessionSelector(
    task.id,
    (session) => ({
      isCloud: session?.isCloud ?? false,
      cloudStatus: session?.cloudStatus ?? null,
      stopRequested: session?.stopRequested ?? false,
    }),
    shallow,
  );
  const [stopConfirmOpen, setStopConfirmOpen] = useState(false);
  const { requestArchive, dialog: archiveDialog } = useTaskArchive(task, {
    navigateUnscoped: !task.channel,
  });

  const canStop = isCloud && !isTerminalStatus(cloudStatus);

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
