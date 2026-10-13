import { ACTIONABLE_ACTIONABILITY_VALUES, SignalReport, SignalReportStatus } from '../types'
// Pure eligibility predicates for report actions, shared by the detail pane, the triage flow, and
// the list row context menu, so the surfaces cannot drift apart. Mirrors desktop `reportActions.ts`.
import { primaryReportPullRequest, hasActiveReportPullRequest } from './reportPullRequests'

/**
 * Can the signed-in user take themselves off this report's suggested reviewers? A list scoped to them
 * holds only reports that name them, even where `is_suggested_reviewer` is false: the server clears
 * that flag on failed and not-actionable reports, which still list the user as a reviewer.
 */
export function canUnassignMe(report: SignalReport, isScopedToMe: boolean): boolean {
    return isScopedToMe || report.is_suggested_reviewer
}

/**
 * Should the Create PR action be offered? Mirrors desktop `canCreateImplementationPr` /
 * the server-side autostart rules: only when ready & actionable, or blocked on user input.
 */
export function canCreateImplementationPr(report: SignalReport): boolean {
    if (primaryReportPullRequest(report).url) {
        return false
    }
    if (report.already_addressed === true) {
        return false
    }
    if (report.status === 'pending_input') {
        return true
    }
    if (report.status === 'ready') {
        return report.actionability != null && ACTIONABLE_ACTIONABILITY_VALUES.includes(report.actionability)
    }
    return false
}

export function canResolveReport(report: SignalReport): boolean {
    return (
        report.status === SignalReportStatus.READY ||
        report.status === SignalReportStatus.PENDING_INPUT ||
        report.status === SignalReportStatus.FAILED
    )
}

/** The backend closes an open implementation PR on resolve; surfaces use this to say so. */
export function hasOpenImplementationPr(report: SignalReport): boolean {
    return hasActiveReportPullRequest(report)
}
