// Port of desktop `@posthog/core/inbox/reportMembership`. Pure functions that
// decide which tab a report belongs to and how the scope filter applies.
// Keep behaviour identical to desktop – this is the source of truth for tab IA.

import { InboxScope, SignalReport, SignalReportStatus } from './types'

/**
 * Statuses out of the inbox entirely (user-suppressed or removed). `failed` is
 * NOT here: failed runs surface in the Runs tab's recently-finished section.
 */
const INBOX_EXCLUDED_STATUSES = new Set<SignalReportStatus>([SignalReportStatus.SUPPRESSED, SignalReportStatus.DELETED])

export function isExcludedFromInbox(report: SignalReport): boolean {
    return INBOX_EXCLUDED_STATUSES.has(report.status)
}

export function teammateInboxScope(uuid: string): InboxScope {
    return `teammate:${uuid}`
}

export function parseTeammateInboxScope(scope: InboxScope): string | null {
    if (!scope.startsWith('teammate:')) {
        return null
    }
    const uuid = scope.slice('teammate:'.length).trim()
    return uuid || null
}

export function isTeammateInboxScope(scope: InboxScope): scope is `teammate:${string}` {
    return parseTeammateInboxScope(scope) != null
}

const QUEUED_RUN_STATUSES = new Set<SignalReportStatus>([SignalReportStatus.POTENTIAL, SignalReportStatus.CANDIDATE])
const LIVE_RUN_STATUSES = new Set<SignalReportStatus>([
    SignalReportStatus.IN_PROGRESS,
    SignalReportStatus.PENDING_INPUT,
])
const FINISHED_RUN_STATUSES = new Set<SignalReportStatus>([SignalReportStatus.READY, SignalReportStatus.FAILED])

export function isQueuedRunReport(report: SignalReport): boolean {
    return QUEUED_RUN_STATUSES.has(report.status)
}

export function isLiveRunReport(report: SignalReport): boolean {
    return LIVE_RUN_STATUSES.has(report.status)
}

export function isFinishedRunReport(report: SignalReport): boolean {
    return FINISHED_RUN_STATUSES.has(report.status)
}

/** Runs-tab count chip + cross-tab exclusion: only "in motion" runs (queued or live). */
export function isAgentRunReport(report: SignalReport): boolean {
    return isQueuedRunReport(report) || isLiveRunReport(report)
}
