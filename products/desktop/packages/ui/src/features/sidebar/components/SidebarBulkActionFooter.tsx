import { BulkArchiveConfirmDialog } from "@posthog/ui/features/sidebar/components/BulkArchiveConfirmDialog";
import { SidebarBulkActionBar } from "@posthog/ui/features/sidebar/components/SidebarBulkActionBar";
import type { SidebarBulkActions } from "@posthog/ui/features/sidebar/useSidebarBulkActions";
import { type ReactElement, useState } from "react";

/**
 * The bar and the archive confirm behind it, for whichever sidebar is showing
 * the session list. Both render this rather than their own copy, the same way
 * both share `useSidebarBulkActions`: a change to the confirm flow lands once.
 */
export function SidebarBulkActionFooter({
  actions,
  onClearSelection,
}: {
  actions: SidebarBulkActions;
  onClearSelection: () => void;
}): ReactElement {
  // Snapshotted rather than read live: archiving clears the selection, which
  // would otherwise retitle the still-open dialog "Archive 0 sessions?".
  const [confirm, setConfirm] = useState<{
    sessionCount: number;
    runningCount: number;
    stopsCloudSandbox: boolean;
  } | null>(null);

  return (
    <>
      <SidebarBulkActionBar
        actions={actions}
        onClearSelection={onClearSelection}
        // Always confirms. Bulk archive has no undo toast, and the running
        // count it would otherwise gate on covers only the sessions the sidebar
        // currently renders — the routed one folded into the batch may not be.
        onArchive={() =>
          setConfirm({
            sessionCount: actions.selectedCount,
            runningCount: actions.runningCount,
            stopsCloudSandbox: actions.stopsCloudSandbox,
          })
        }
      />

      <BulkArchiveConfirmDialog
        open={confirm !== null}
        sessionCount={confirm?.sessionCount ?? 0}
        runningCount={confirm?.runningCount ?? 0}
        stopsCloudSandbox={Boolean(confirm?.stopsCloudSandbox)}
        isArchiving={actions.isArchiving}
        onConfirm={async () => {
          await actions.archiveSelected();
          setConfirm(null);
        }}
        onCancel={() => setConfirm(null)}
      />
    </>
  );
}
