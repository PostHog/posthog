// Pure eligibility predicates for report actions, shared by the detail pane, the triage flow, and
// the list row context menu, so the surfaces cannot drift apart. Mirrors desktop `reportActions.ts`.

import { ACTIONABLE_ACTIONABILITY_VALUES, SignalReport, SignalReportStatus } from '../types'

/**
 * Should the Create PR action be offered? Mirrors desktop `canCreateImplementationPr` /
 * the server-side autostart rules: only when ready & actionable, or blocked on user input.
 */
export function canCreateImplementationPr(report: SignalReport): boolean {
    if (report.implementation_pr_url) {
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

/**
 * Offer Resolve only where the backend accepts a direct transition to RESOLVED — a researched
 * report (ready or pending_input). Other live statuses (potential, candidate, in_progress,
 * failed) return 409, so don't show a dead-end affordance. Mirrors `canCreateImplementationPr`
 * and the server transition guard.
 */
export function canResolveReport(report: SignalReport): boolean {
    return report.status === SignalReportStatus.READY || report.status === SignalReportStatus.PENDING_INPUT
}

/** The backend closes an open implementation PR on resolve; surfaces use this to say so. */
export function hasOpenImplementationPr(report: SignalReport): boolean {
    return !!report.implementation_pr_url && report.implementation_pr_merged !== true
}
