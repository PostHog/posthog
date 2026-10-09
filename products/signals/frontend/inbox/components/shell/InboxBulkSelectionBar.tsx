import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconHide, IconLeave, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import type { SignalReport } from '../../types'
import { canUnassignMe, hasOpenImplementationPr } from '../../utils/reportActions'
import { openDismissReportDialog } from './DismissReportDialog'
import { openResolveReportDialog } from './ResolveReportDialog'

/**
 * Bulk action toolbar shown when one or more reports are multi-selected.
 * Mirrors desktop `InboxBulkSelectionBar` (the dismiss + clear slice) plus Resolve and Unassign me.
 * Selection and the bulk state calls live in `inboxBulkActionsLogic`; delete / reingest
 * remain on `inboxSceneLogic` per-report.
 */
export function InboxBulkSelectionBar({ reports }: { reports: SignalReport[] }): JSX.Element | null {
    const { selectedCount, selectedReportIds, isDismissing, isResolving, isUnassigning } =
        useValues(inboxBulkActionsLogic)
    const { clearSelection, bulkDismiss, bulkResolve, bulkUnassignMe } = useActions(inboxBulkActionsLogic)
    const { isScopedToMe } = useValues(inboxFiltersLogic)

    if (selectedCount === 0) {
        return null
    }
    const busy = isDismissing || isResolving || isUnassigning
    const selectedIds = new Set(selectedReportIds)
    const hasOpenPr = reports.some((report) => selectedIds.has(report.id) && hasOpenImplementationPr(report))
    const unassignableIds = reports
        .filter((report) => selectedIds.has(report.id) && canUnassignMe(report, isScopedToMe))
        .map((report) => report.id)

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
                    type="secondary"
                    size="small"
                    icon={<IconLeave />}
                    loading={isUnassigning}
                    disabledReason={
                        busy
                            ? 'Working…'
                            : unassignableIds.length === 0
                              ? "You're not a reviewer on any selected report"
                              : undefined
                    }
                    onClick={() => bulkUnassignMe(unassignableIds)}
                    data-attr="inbox-bulk-unassign-me"
                >
                    Unassign me
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
