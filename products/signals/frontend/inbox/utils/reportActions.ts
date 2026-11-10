import { canResolveReport } from '@posthog/agent-contracts/signal-report-state'

import { ACTIONABLE_ACTIONABILITY_VALUES, SignalReport, SignalReportStatus } from '../types'
import { primaryReportPullRequest } from './reportPullRequests'

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
    if (report.is_self_improvement_report && !report.repo_slug) {
        return false
    }
    if (primaryReportPullRequest(report).url) {
        return false
    }
    if (report.already_addressed === true) {
        return false
    }
    // A plan's steps do its work, so a run on the plan itself would repeat theirs. Auto-start skips a
    // plan for the same reason. List rows carry no `plan`, so only a loaded report can tell.
    if (report.plan?.id === report.id) {
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

export function canMonitorReport(report: SignalReport, hasFollowUpChecks: boolean): boolean {
    return (
        hasFollowUpChecks &&
        'monitoring_started_at' in report &&
        canResolveReport(report) &&
        report.status !== SignalReportStatus.CLOSED &&
        report.status !== SignalReportStatus.MONITORING
    )
}
