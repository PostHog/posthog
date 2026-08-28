import { Archive } from "@phosphor-icons/react";
import {
  Kbd,
  Button as QuillButton,
  Spinner,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { useTaskArchive } from "@posthog/ui/features/archive/useTaskArchive";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";

/**
 * Archives the task in view from its header row, beside the run controls, with
 * the same icon a session's right-click menu files it under.
 */
export function ArchiveTaskButton({ task }: { task: Task }) {
  const { requestArchive, isArchiving, dialog } = useTaskArchive(task, {
    navigateUnscoped: !task.channel,
  });

  return (
    <>
      <div className="no-drag flex items-center">
        <Tooltip>
          <TooltipTrigger
            render={
              <QuillButton
                variant="outline"
                size="sm"
                aria-label="Archive task"
                disabled={isArchiving}
                onClick={requestArchive}
                className="px-1.5"
              />
            }
          >
            {isArchiving ? (
              <Spinner className="size-3.5" />
            ) : (
              <Archive size={14} weight="regular" className="shrink-0" />
            )}
          </TooltipTrigger>
          <TooltipContent side="bottom" className="flex items-center gap-1.5">
            Archive task
            <Kbd>{formatHotkey(SHORTCUTS.ARCHIVE_TASK)}</Kbd>
          </TooltipContent>
        </Tooltip>
      </div>
      {dialog}
    </>
  );
}
