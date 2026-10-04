import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconHide, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { captureInboxSelectionModeEntered } from '../../inboxAnalytics'
import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import type { SignalReport } from '../../types'
import { hasOpenImplementationPr } from '../../utils/reportActions'
import { openDismissReportDialog } from './DismissReportDialog'
import { openResolveReportDialog } from './ResolveReportDialog'

/**
 * How many open reports the list must hold before the bar offers to select them all. Below this,
 * one-by-one cleanup is quick enough that the prompt is only noise.
 */
export const BULK_CLEANUP_PROMPT_MIN_REPORTS = 10

/**
 * Bulk action toolbar shown when one or more reports are multi-selected.
 * Mirrors desktop `InboxBulkSelectionBar` (the dismiss + clear slice) plus Resolve. Selection
 * and the bulk state calls live in `inboxBulkActionsLogic`; delete / reingest
 * remain on `inboxSceneLogic` per-report.
 *
 * With nothing selected and a long open queue, the bar offers to select every open report, because
 * the row gestures that start a selection are hard to find.
 */
export function InboxBulkSelectionBar({
    reports,
    openReportIds = [],
}: {
    reports: SignalReport[]
    /** Loaded reports that still need a decision, in list order. "Select all" picks these. */
    openReportIds?: string[]
}): JSX.Element | null {
    const { selectedCount, selectedReportIds, isDismissing, isResolving } = useValues(inboxBulkActionsLogic)
    const { clearSelection, bulkDismiss, bulkResolve, selectAll } = useActions(inboxBulkActionsLogic)

    if (selectedCount === 0) {
        if (openReportIds.length < BULK_CLEANUP_PROMPT_MIN_REPORTS) {
            return null
        }
        return (
            <div className="flex items-center justify-between gap-3 flex-wrap rounded border border-primary px-3 py-2">
                <span className="text-sm text-secondary min-w-0">
                    {openReportIds.length} reports need a decision. Select them to dismiss or resolve them together.
                </span>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => {
                        captureInboxSelectionModeEntered({ method: 'select_all' })
                        selectAll(openReportIds)
                    }}
                    data-attr="inbox-bulk-select-all"
                >
                    Select all {openReportIds.length}
                </LemonButton>
            </div>
        )
    }
    const busy = isDismissing || isResolving
    const selectedIds = new Set(selectedReportIds)
    const hasOpenPr = reports.some((report) => selectedIds.has(report.id) && hasOpenImplementationPr(report))

    return (
        <div className="flex items-center justify-between gap-3 flex-wrap rounded border border-accent bg-accent-highlight-secondary px-3 py-2">
            <div className="flex items-center gap-2 min-w-0">
                <span className="font-medium text-sm shrink-0">{selectedCount} selected</span>
                <span className="text-xs text-muted">Shift-click range · Click to toggle · Esc to clear</span>
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
                            hasOpenPr,
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
                            hasOpenPr,
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
