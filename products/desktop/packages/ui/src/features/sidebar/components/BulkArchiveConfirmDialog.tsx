import {
  formatBulkArchiveWarning,
  sessionsLabel,
} from "@posthog/core/sidebar/selection";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import type { ReactElement } from "react";

interface BulkArchiveConfirmDialogProps {
  open: boolean;
  sessionCount: number;
  /** How many of the selection are still running, so archiving stops them. */
  runningCount: number;
  stopsCloudSandbox: boolean;
  isArchiving: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * One confirm for a whole batch. The single-row `ArchiveRunningTaskDialog`
 * covers one session at a time; prompting per session would mean N dialogs.
 */
export function BulkArchiveConfirmDialog({
  open,
  sessionCount,
  runningCount,
  stopsCloudSandbox,
  isArchiving,
  onConfirm,
  onCancel,
}: BulkArchiveConfirmDialogProps): ReactElement {
  return (
    <AlertDialog
      open={open}
      // Escape is guarded the way the Cancel button is. Dismissing mid-archive
      // would take the progress away while the batch is still finishing.
      onOpenChange={(next) => {
        if (!next && !isArchiving) onCancel();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            Archive {sessionsLabel(sessionCount)}?
          </AlertDialogTitle>
          <AlertDialogDescription>
            {formatBulkArchiveWarning({
              running: runningCount,
              stopsCloudSandbox,
            })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={isArchiving}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={onConfirm}
            loading={isArchiving}
            disabled={isArchiving}
          >
            Archive
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
