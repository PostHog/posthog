import type { InboxSortDirection, InboxSortField } from '../logics/inboxFiltersLogic'
import { SignalReport, SignalReportStatus } from '../types'

/**
 * Client-side mirror of the server list ordering (`buildSignalReportListOrdering`): the selected
 * field leads, then the pipeline status rank, then recency. The flat Reports list merges several
 * per-state responses, so rows from different requests must be comparable with the same keys the
 * server sorted each response by.
 */

// Mirrors `_annotate_signal_report_status_rank` in products/signals/backend/views.py. `ready`
// splits into two virtual stages there: 0 for actionable (or unjudged), 1 for not actionable.
const STATUS_RANK: Record<SignalReportStatus, number> = {
    [SignalReportStatus.READY]: 0,
    [SignalReportStatus.PENDING_INPUT]: 2,
    [SignalReportStatus.IN_PROGRESS]: 3,
    [SignalReportStatus.CANDIDATE]: 4,
    [SignalReportStatus.POTENTIAL]: 5,
    [SignalReportStatus.FAILED]: 6,
    [SignalReportStatus.RESOLVED]: 7,
    [SignalReportStatus.SUPPRESSED]: 8,
    [SignalReportStatus.DELETED]: 9,
}

function statusRank(report: SignalReport): number {
    if (report.status === SignalReportStatus.READY && report.actionability === 'not_actionable') {
        return 1
    }
    return STATUS_RANK[report.status] ?? 50
}

// The server coalesces a missing priority to "~", which sorts after "P4" in ASCII.
function priorityKey(report: SignalReport): string {
    return report.priority ?? '~'
}

// Plain code-point comparison, matching how Postgres sorts the ISO timestamps and P0–P4 strings.
function compareStrings(a: string, b: string): number {
    return a < b ? -1 : a > b ? 1 : 0
}

// DRF omits the fractional part when the microseconds are zero, and a plain string comparison then
// puts "...:00Z" after "...:00.100000Z". Pad the missing fraction so the comparison matches the
// database order.
function timestampKey(value: string): string {
    return value.includes('.') ? value : value.replace(/(Z|[+-]\d\d:?\d\d)$/, '.000000$1')
}

/** Comparator over reports for the given sort selection. Stable input order breaks remaining ties. */
export function compareSignalReports(
    field: InboxSortField,
    direction: InboxSortDirection
): (a: SignalReport, b: SignalReport) => number {
    const dir = direction === 'desc' ? -1 : 1
    return (a, b) => {
        const primary =
            field === 'priority'
                ? compareStrings(priorityKey(a), priorityKey(b))
                : compareStrings(timestampKey(a[field]), timestampKey(b[field]))
        if (primary !== 0) {
            return dir * primary
        }
        const rank = statusRank(a) - statusRank(b)
        if (rank !== 0) {
            return rank
        }
        // Recency tiebreak, skipped when the selected field already is updated_at.
        return field === 'updated_at' ? 0 : compareStrings(timestampKey(b.updated_at), timestampKey(a.updated_at))
    }
}
