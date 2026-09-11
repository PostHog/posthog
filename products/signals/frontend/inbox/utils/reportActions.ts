// Pure eligibility predicates for report actions, shared by the detail pane, the triage flow, and
// the list row context menu, so the surfaces cannot drift apart. The desktop app has its own
// `reportActions.ts`; it still offers Create PR only on a report the pipeline approved, because the
// override below needs a confirmation surface the desktop does not have yet.

import { ACTIONABLE_ACTIONABILITY_VALUES, SignalReport, SignalReportStatus } from '../types'

/**
 * Statuses a report sits in when PostHog declined to implement it on its own: the safety judge
 * rejected it (born suppressed, or failed carrying the judge's error), or the pipeline has not
 * researched it yet. Create PR is offered on these, behind a confirmation that states the reason —
 * a person who has read the verdict and disagrees with it is the one the escape hatch is for.
 */
export const SAFETY_OVERRIDE_STATUSES: readonly SignalReportStatus[] = [
    SignalReportStatus.POTENTIAL,
    SignalReportStatus.CANDIDATE,
    SignalReportStatus.FAILED,
    SignalReportStatus.SUPPRESSED,
]

/**
 * Should the Create PR action be offered? A report the pipeline approved (ready & actionable, or
 * blocked on user input the person can supply) offers it directly; a report PostHog declined to
 * implement offers it behind {@link requiresSafetyOverride}'s confirmation.
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
    return requiresSafetyOverride(report)
}

/**
 * Does pressing Create PR on this report overrule a decision PostHog already made? Such a report
 * needs the confirmation and the recorded override before the run starts (see
 * `openSafetyOverrideDialog` and the `safety_override` endpoint).
 *
 * A report the actionability judge called `not_actionable` is excluded even here: the product's own
 * reading is that it holds no work to do, which is a different claim from "we would not risk it",
 * and resolving it has its own button.
 */
export function requiresSafetyOverride(report: SignalReport): boolean {
    return SAFETY_OVERRIDE_STATUSES.includes(report.status) && report.actionability !== 'not_actionable'
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
