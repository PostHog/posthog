import { canResolveReport } from '@posthog/agent-contracts/signal-report-state'

import type { _UserApi } from 'products/signals/frontend/generated/api.schemas'

import { ACTIONABLE_ACTIONABILITY_VALUES, SignalReport, SignalReportStatus } from '../types'
import { reportClaimant } from './reportClaim'
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

export type ImplementationClaimStep =
    | { kind: 'start' }
    | { kind: 'confirm_own_agent' }
    | { kind: 'take_over'; holder: _UserApi }
    | { kind: 'blocked'; reason: string }

/**
 * What Create PR must do about the claim before it starts a run. Mirrors the server: only a run in flight
 * blocks it, the user's own claim and a task's claim do not, and a teammate's claim has to be taken over.
 * The user's own agent can already be working, so that case asks before it starts a second run.
 */
export function implementationClaimStep(
    report: Pick<SignalReport, 'assignee' | 'implementation_in_flight'>,
    userUuid: string | null | undefined
): ImplementationClaimStep {
    if (report.implementation_in_flight) {
        return { kind: 'blocked', reason: 'A pull request run is already in progress for this report.' }
    }
    const assignee = report.assignee
    if (!assignee || assignee.kind === 'task') {
        return { kind: 'start' }
    }
    const holder = reportClaimant(report)
    if (!holder) {
        return { kind: 'blocked', reason: 'Someone else is working on this report.' }
    }
    if (holder.uuid !== userUuid) {
        return { kind: 'take_over', holder }
    }
    return assignee.kind === 'agent' ? { kind: 'confirm_own_agent' } : { kind: 'start' }
}

/** Why the claim keeps Create PR disabled for this user, or null when the user can go ahead, maybe after a dialog. */
export function implementationClaimDisabledReason(
    report: Pick<SignalReport, 'assignee' | 'implementation_in_flight'>,
    userUuid: string | null | undefined
): string | null {
    const step = implementationClaimStep(report, userUuid)
    return step.kind === 'blocked' ? step.reason : null
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
