import { useValues } from 'kea'

import { hasOpenImplementationPr } from '@posthog/agent-contracts/signal-report-state'

import { userLogic } from 'scenes/userLogic'

import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { canUnassignMe } from '../../utils/reportActions'
import { isReportClaimable } from '../../utils/reportClaim'

export interface InboxBulkSelection {
    selectedCount: number
    busy: boolean
    isMonitoring: boolean
    hasOpenPr: boolean
    unassignableIds: string[]
    claimableIds: string[]
}

/** What the bulk bar needs to know about the selected rows. The Lemon bar and the Quill bar share it. */
export function useInboxBulkSelection(reports: SignalReport[]): InboxBulkSelection {
    const { selectedCount, selectedReportIds, isClaiming, isDismissing, isResolving, isUnassigning } =
        useValues(inboxBulkActionsLogic)
    const { isScopedToMe } = useValues(inboxFiltersLogic)
    const { user } = useValues(userLogic)
    const selectedIds = new Set(selectedReportIds)
    const selectedReports = reports.filter((report) => selectedIds.has(report.id))
    return {
        selectedCount,
        busy: isClaiming || isDismissing || isResolving || isUnassigning,
        isMonitoring:
            selectedReports.length === selectedCount &&
            selectedReports.every((report) => report.status === SignalReportStatus.MONITORING),
        hasOpenPr: selectedReports.some((report) => hasOpenImplementationPr(report)),
        unassignableIds: selectedReports
            .filter((report) => canUnassignMe(report, isScopedToMe))
            .map((report) => report.id),
        claimableIds: selectedReports
            .filter((report) => isReportClaimable(report, user?.uuid ?? null))
            .map((report) => report.id),
    }
}
