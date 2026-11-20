import { hasOpenImplementationPr } from '@posthog/agent-contracts/signal-report-state'

import { reportStatusLabel } from '../components/badges/SignalReportStatusBadge'
import { EnrichedReviewer, SignalReport, SignalReportStatus } from '../types'

type FactReport = Pick<
    SignalReport,
    | 'status'
    | 'suppression_source'
    | 'implementation_in_flight'
    | 'pull_requests'
    | 'implementation_pr_url'
    | 'implementation_pr_state'
    | 'implementation_pr_merged'
>

const OPEN_STATUS_LABELS: Partial<Record<SignalReportStatus, string>> = {
    [SignalReportStatus.READY]: 'Open',
    [SignalReportStatus.IN_PROGRESS]: 'Research in progress',
    [SignalReportStatus.CANDIDATE]: 'Research queued',
    [SignalReportStatus.POTENTIAL]: 'Gathering signals',
}

/**
 * The status a person reads in a fact line. It names the step the report is at, so a running implementation
 * and an open pull request win over the pipeline status, which stays "ready" through both.
 */
export function reportFactStatus(report: FactReport): string {
    if (report.status === SignalReportStatus.READY || report.status === SignalReportStatus.PENDING_INPUT) {
        if (hasOpenImplementationPr(report)) {
            return 'Pull request ready'
        }
        if (report.implementation_in_flight) {
            return 'Run in progress'
        }
    }
    return OPEN_STATUS_LABELS[report.status] ?? reportStatusLabel(report.status, report.suppression_source)
}

export type ReportOwnerKind = 'none' | 'me' | 'my-agent' | 'teammate' | 'teammate-agent'

export function reportOwnerKind(
    report: Pick<SignalReport, 'assignee'>,
    currentUserUuid: string | null
): ReportOwnerKind {
    const assignee = report.assignee
    const holder = assignee?.kind === 'agent' ? (assignee.responsible_user ?? assignee.user) : assignee?.user
    if (!assignee || !holder) {
        return 'none'
    }
    const mine = holder.uuid === currentUserUuid
    if (assignee.kind === 'agent') {
        return mine ? 'my-agent' : 'teammate-agent'
    }
    return mine ? 'me' : 'teammate'
}

type ClaimKeyEvent = Pick<KeyboardEvent, 'metaKey' | 'ctrlKey' | 'shiftKey' | 'altKey'>

/** What the U key does: U alone claims, and U with the platform's command key releases the user's own claim. */
export function claimKeyIntent(
    event: ClaimKeyEvent,
    isMac: boolean,
    { canClaim, canUnclaim }: { canClaim: boolean; canUnclaim: boolean }
): 'claim' | 'unclaim' | null {
    if (event.shiftKey || event.altKey) {
        return null
    }
    const command = isMac ? event.metaKey : event.ctrlKey
    if (command) {
        return canUnclaim ? 'unclaim' : null
    }
    return canClaim && !event.metaKey && !event.ctrlKey ? 'claim' : null
}

/** The person a report with no owner is suggested for: the first suggested reviewer. */
export function suggestedOwnerName(reviewers: EnrichedReviewer[] | null): string | null {
    const reviewer = reviewers?.[0]
    if (!reviewer) {
        return null
    }
    const fullName = reviewer.user ? `${reviewer.user.first_name} ${reviewer.user.last_name}`.trim() : ''
    return fullName || reviewer.user?.email || reviewer.github_name || reviewer.github_login
}

/** A suggestion shows only while the report has no owner. A claim replaces it. */
export function reportOwnerLabel(
    kind: ReportOwnerKind,
    holderName: string | null,
    suggestedName: string | null = null
): string {
    switch (kind) {
        case 'none':
            return suggestedName ? `Suggested for ${suggestedName}` : 'No owner'
        case 'me':
            return 'Assigned to you'
        case 'my-agent':
            return 'Assigned to your agent'
        case 'teammate':
            return `Assigned to ${holderName}`
        case 'teammate-agent':
            return `Assigned to ${holderName}'s agent`
    }
}

/** Splits list rows into the "For you" group and the others. Each group keeps the order of the list. */
export function groupForYou<Row extends { report: Parameters<typeof isForYouReport>[0] }>(
    rows: Row[],
    currentUserUuid: string | null
): { forYou: Row[]; others: Row[] } {
    return {
        forYou: rows.filter(({ report }) => isForYouReport(report, currentUserUuid)),
        others: rows.filter(({ report }) => !isForYouReport(report, currentUserUuid)),
    }
}

const FOR_YOU_STATUSES: SignalReportStatus[] = [SignalReportStatus.READY, SignalReportStatus.PENDING_INPUT]

/**
 * Whether a report belongs in the list's "For you" group. Mirrors `reports_for_person` on the server, which
 * picks the Home "For you" reports, so the two pages agree on what is for the person.
 */
export function isForYouReport(
    report: Pick<SignalReport, 'status' | 'actionability' | 'already_addressed' | 'is_suggested_reviewer' | 'assignee'>,
    currentUserUuid: string | null
): boolean {
    if (
        !FOR_YOU_STATUSES.includes(report.status) ||
        report.actionability === 'not_actionable' ||
        report.already_addressed === true
    ) {
        return false
    }
    const owner = reportOwnerKind(report, currentUserUuid)
    return report.is_suggested_reviewer === true || owner === 'me' || owner === 'my-agent'
}
