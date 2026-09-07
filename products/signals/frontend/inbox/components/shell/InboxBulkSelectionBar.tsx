import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconHide, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { openDismissReportDialog } from './DismissReportDialog'
import { openResolveReportDialog } from './ResolveReportDialog'

/**
 * Bulk action toolbar shown when one or more reports are multi-selected.
 * Mirrors desktop `InboxBulkSelectionBar` (the dismiss + clear slice) plus Resolve. Selection
 * and the bulk state calls live in `inboxBulkActionsLogic`; delete / reingest
 * remain on `inboxSceneLogic` per-report.
 */
export function InboxBulkSelectionBar(): JSX.Element | null {
    const { selectedCount, isDismissing, isResolving } = useValues(inboxBulkActionsLogic)
    const { clearSelection, bulkDismiss, bulkResolve } = useActions(inboxBulkActionsLogic)

    if (selectedCount === 0) {
        return null
    }
    const busy = isDismissing || isResolving

    return (
        <div className="flex items-center justify-between gap-3 flex-wrap rounded border border-accent bg-accent-highlight-secondary px-3 py-2">
            <div className="flex items-center gap-2 min-w-0">
                <span className="font-medium text-sm shrink-0">{selectedCount} selected</span>
                <span className="text-xs text-muted">Shift-click range · ⌘-click toggle · Esc to clear</span>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconCheckCircle />}
                    loading={isResolving}
                    disabledReason={busy ? 'Working…' : undefined}
                    onClick={() =>
                        openResolveReportDialog({
                            selectedCount,
                            onConfirm: ({ reason, note }) => bulkResolve(reason, note),
                        })
                    }
                    data-attr="inbox-bulk-resolve"
                >
                    Resolve
                </LemonButton>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconHide />}
                    loading={isDismissing}
                    disabledReason={busy ? 'Working…' : undefined}
                    onClick={() =>
                        openDismissReportDialog({
                            selectedCount,
                            onConfirm: (dismissal) => bulkDismiss(dismissal),
                        })
                    }
                    data-attr="inbox-bulk-dismiss"
                >
                    Dismiss
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconX />}
                    tooltip="Clear selection"
                    aria-label="Clear selection"
                    onClick={clearSelection}
                />
            </div>
        </div>
    )
}
