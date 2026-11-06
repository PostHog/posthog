import { BulkArchiveConfirmDialog } from "@posthog/ui/features/sidebar/components/BulkArchiveConfirmDialog";
import type { SidebarBulkActions } from "@posthog/ui/features/sidebar/useSidebarBulkActions";
import { type ReactElement, useCallback, useState } from "react";

export interface BulkArchiveConfirm {
  /** Opens the confirm. Nothing is archived until it is accepted. */
  requestArchive: () => void;
  /** Render once, wherever the surface that asked for it lives. */
  dialog: ReactElement;
}

/**
 * The confirm a bulk archive goes through, owned by whoever owns the selection
 * rather than by each surface that can start one. Both the action bar and a
 * row's right-click menu ask for the same dialog, and mounting one per row
 * would put a dialog behind every session in the list.
 *
 * Always confirms. Bulk archive has no undo toast, and the running count it
 * would otherwise gate on covers only the sessions the sidebar currently
 * renders.
 */
export function useBulkArchiveConfirm(
  actions: SidebarBulkActions,
): BulkArchiveConfirm {
  // Snapshotted rather than read live: archiving clears the selection, which
  // would otherwise retitle the still-open dialog "Archive 0 sessions?".
  const [confirm, setConfirm] = useState<{
    sessionCount: number;
    runningCount: number;
    stopsCloudSandbox: boolean;
  } | null>(null);

  const { selectedCount, runningCount, stopsCloudSandbox } = actions;
  const requestArchive = useCallback(() => {
    setConfirm({
      sessionCount: selectedCount,
      runningCount,
      stopsCloudSandbox,
    });
  }, [runningCount, selectedCount, stopsCloudSandbox]);

  return {
    requestArchive,
    dialog: (
      <BulkArchiveConfirmDialog
        open={confirm !== null}
        sessionCount={confirm?.sessionCount ?? 0}
        runningCount={confirm?.runningCount ?? 0}
        stopsCloudSandbox={Boolean(confirm?.stopsCloudSandbox)}
        isArchiving={actions.isArchiving}
        onConfirm={() => {
          setConfirm(null);
          void actions.archiveSelected();
        }}
        onCancel={() => setConfirm(null)}
      />
    ),
  };
}
