import {
    isAudienceSlicesRecommendation,
    isFiresOnLeaveRecommendation,
    isFlowDropRecommendation,
    isFunnelStepRecommendation,
    isInflatedCountsRecommendation,
    isKnownPatternsRecommendation,
    isLostVisitorRecommendation,
    isManyAccountsRecommendation,
    isOneAccountRecommendation,
    isQuickLeaveRecommendation,
    isRelatedIssuesRecommendation,
    isSupportTicketsRecommendation,
    isSuppressedEventsRecommendation,
} from '../recommendations/recommendationsTabLogic'
import {
    type AudienceSliceIssue,
    type ErrorTrackingRecommendation,
    type FiresOnLeaveIssue,
    type FlowDropIncident,
    type FlowDropIssue,
    type FunnelStepIncident,
    type FunnelStepIssue,
    type InflatedCountsIssue,
    type KnownPatternsIssue,
    type KnownPatternsRecommendationMeta,
    type LostVisitorIssue,
    type ManyAccountsIssue,
    type OneAccountIssue,
    type QuickLeaveIssue,
    type RelatedIssuesIssue,
    type SupportTicketsIssue,
    type SuppressedEventsIssue,
} from '../recommendations/types'
export type ImpactFinding =
    | { lens: 'flow_drop'; issue: FlowDropIssue; incident: FlowDropIncident | null }
    | { lens: 'funnel_step'; issue: FunnelStepIssue; incident: FunnelStepIncident | null }
    | { lens: 'quick_leave'; issue: QuickLeaveIssue; minPageSeconds: number; quickLeaveSeconds: number }
    | { lens: 'lost_visitor'; issue: LostVisitorIssue }
    | { lens: 'suppressed_events'; issue: SuppressedEventsIssue }
    | { lens: 'support_tickets'; issue: SupportTicketsIssue; baselinePer1k: number }
    | { lens: 'many_accounts'; issue: ManyAccountsIssue; groupLabel: string }
    | { lens: 'one_account'; issue: OneAccountIssue }
    | { lens: 'audience_slices'; issue: AudienceSliceIssue }
    | { lens: 'related_issues'; issue: RelatedIssuesIssue }
    | { lens: 'fires_on_leave'; issue: FiresOnLeaveIssue }
    | { lens: 'inflated_counts'; issue: InflatedCountsIssue }
    | {
          lens: 'known_patterns'
          issue: KnownPatternsIssue
          totalEvents: number
          classes: KnownPatternsRecommendationMeta['classes']
      }

export type ImpactFindingLens = ImpactFinding['lens']

// A stored meta can come from an older version of a lens, so a missing or malformed list reads as empty rather than
// crashing every view that reads findings.
function list<T>(items: T[] | undefined): T[] {
    return Array.isArray(items) ? items : []
}

function samePages(a: string[], b: string[]): boolean {
    return a.length === b.length && a.every((page, index) => page === b[index])
}

function lensFindings(lens: ErrorTrackingRecommendation): ImpactFinding[] {
    if (lens.computed_at === null) {
        return []
    }
    if (isFlowDropRecommendation(lens)) {
        const incidents = list(lens.meta.incidents)
        return list(lens.meta.issues).map((issue) => ({
            lens: 'flow_drop',
            issue,
            incident:
                incidents.find(
                    (incident) =>
                        incident.from_path === issue.from_path &&
                        incident.to_path === issue.to_path &&
                        incident.hour === issue.hour
                ) ?? null,
        }))
    }
    if (isFunnelStepRecommendation(lens)) {
        const incidents = list(lens.meta.incidents)
        return list(lens.meta.issues).map((issue) => ({
            lens: 'funnel_step',
            issue,
            incident:
                incidents.find(
                    (incident) => incident.hour === issue.hour && samePages(list(incident.pages), list(issue.pages))
                ) ?? null,
        }))
    }
    if (isQuickLeaveRecommendation(lens)) {
        const { min_page_seconds: minPageSeconds, quick_leave_seconds: quickLeaveSeconds } = lens.meta
        return list(lens.meta.issues).map((issue) => ({
            lens: 'quick_leave',
            issue,
            minPageSeconds,
            quickLeaveSeconds,
        }))
    }
    if (isLostVisitorRecommendation(lens)) {
        return list(lens.meta.issues).map((issue) => ({ lens: 'lost_visitor', issue }))
    }
    if (isSuppressedEventsRecommendation(lens)) {
        return list(lens.meta.issues).map((issue) => ({ lens: 'suppressed_events', issue }))
    }
    if (isSupportTicketsRecommendation(lens)) {
        const baselinePer1k = lens.meta.baseline_per_1k ?? 0
        return list(lens.meta.issues).map((issue) => ({ lens: 'support_tickets', issue, baselinePer1k }))
    }
    if (isManyAccountsRecommendation(lens)) {
        const groupLabel = lens.meta.group_label
        return list(lens.meta.issues).map((issue) => ({ lens: 'many_accounts', issue, groupLabel }))
    }
    if (isOneAccountRecommendation(lens)) {
        return list(lens.meta.issues).map((issue) => ({ lens: 'one_account', issue }))
    }
    if (isRelatedIssuesRecommendation(lens)) {
        return list(lens.meta.issues).map((issue) => ({ lens: 'related_issues', issue }))
    }
    if (isAudienceSlicesRecommendation(lens)) {
        return list(lens.meta.issues).map((issue) => ({ lens: 'audience_slices', issue }))
    }
    if (isFiresOnLeaveRecommendation(lens)) {
        return list(lens.meta.issues).map((issue) => ({ lens: 'fires_on_leave', issue }))
    }
    if (isInflatedCountsRecommendation(lens)) {
        return list(lens.meta.issues).map((issue) => ({ lens: 'inflated_counts', issue }))
    }
    if (isKnownPatternsRecommendation(lens)) {
        const totalEvents = lens.meta.total_events ?? 0
        const classes = list(lens.meta.classes)
        return list(lens.meta.issues).map((issue) => ({ lens: 'known_patterns', issue, totalEvents, classes }))
    }
    return []
}

// The findings of every computed lens, keyed by lens, in each lens's own order. A related issue finding is a pair.
// The backend leaves issues that fire as people leave out of the lenses that point at harm.
export function findingsByLens(
    lenses: ErrorTrackingRecommendation[]
): Partial<Record<ImpactFindingLens, ImpactFinding[]>> {
    const byLens: Partial<Record<ImpactFindingLens, ImpactFinding[]>> = {}
    for (const finding of lenses.flatMap(lensFindings)) {
        byLens[finding.lens] = [...(byLens[finding.lens] ?? []), finding]
    }
    return byLens
}
