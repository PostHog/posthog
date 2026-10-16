import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { HogFunctionSubTemplateIdType } from '~/types'

export type ErrorTrackingRecommendationType =
    | 'alerts'
    | 'audience_slices'
    | 'fires_on_leave'
    | 'flow_drop'
    | 'funnel_step'
    | 'inflated_counts'
    | 'known_patterns'
    | 'long_running_issues'
    | 'lost_visitor'
    | 'many_accounts'
    | 'one_account'
    | 'quick_leave'
    | 'rate_limits'
    | 'related_issues'
    | 'source_maps'
    | 'suppressed_events'
    | 'support_tickets'

export type ImpactLensType =
    | 'flow_drop'
    | 'funnel_step'
    | 'quick_leave'
    | 'lost_visitor'
    | 'suppressed_events'
    | 'support_tickets'
    | 'many_accounts'
    | 'one_account'
    | 'audience_slices'
    | 'related_issues'
    | 'fires_on_leave'
    | 'inflated_counts'
    | 'known_patterns'

// Impact lenses are computed as recommendations but shown in the impact tab, not in the recommendations tab.
// The order is the priority order: lenses that point at harm come first, lenses that explain noise come last.
export const IMPACT_LENS_TYPES: readonly ImpactLensType[] = [
    'flow_drop',
    'funnel_step',
    'quick_leave',
    'lost_visitor',
    'suppressed_events',
    'support_tickets',
    'many_accounts',
    'one_account',
    'audience_slices',
    'related_issues',
    'fires_on_leave',
    'inflated_counts',
    'known_patterns',
]

// Lenses that explain noise rather than point at harm. The All view leaves them out, so it lists issues worth acting on.
export const IMPACT_NOISE_LENS_TYPES: readonly ImpactLensType[] = [
    'fires_on_leave',
    'inflated_counts',
    'known_patterns',
]

export const isNoiseLensType = (type: ImpactLensType): boolean => IMPACT_NOISE_LENS_TYPES.includes(type)

export const isImpactLensType = (type: ErrorTrackingRecommendationType): type is ImpactLensType =>
    (IMPACT_LENS_TYPES as readonly ErrorTrackingRecommendationType[]).includes(type)

export type ErrorTrackingRecommendationStatus = 'ready' | 'computing'

export interface ErrorTrackingRecommendation<TMeta extends Record<string, unknown> = Record<string, unknown>> {
    id: string
    type: ErrorTrackingRecommendationType
    meta: TMeta
    completed: boolean
    status: ErrorTrackingRecommendationStatus
    computed_at: string | null
    dismissed_at: string | null
    created_at: string
    updated_at: string
}

export interface AlertRecommendationItem {
    key: HogFunctionSubTemplateIdType
    enabled: boolean
}

export interface AlertsRecommendationMeta extends Record<string, unknown> {
    alerts: AlertRecommendationItem[]
}

export type AlertsRecommendation = ErrorTrackingRecommendation<AlertsRecommendationMeta>

export interface AlertRecommendationInfo {
    name: string
    reason: string
}

export const ALERT_RECOMMENDATION_INFO: Record<string, AlertRecommendationInfo> = {
    'error-tracking-issue-created': {
        name: 'Issue created',
        reason: 'Get notified when a new error issue is detected.',
    },
    'error-tracking-issue-reopened': {
        name: 'Issue reopened',
        reason: 'Get notified when a previously resolved issue comes back.',
    },
    'error-tracking-issue-spiking': {
        name: 'Issue spiking',
        reason: 'Get notified when an issue starts occurring more frequently than usual.',
    },
}

export type RateLimitRecommendationKey = 'project' | 'per_issue'

export interface RateLimitRecommendationItem {
    key: RateLimitRecommendationKey
    enabled: boolean
}

export interface RateLimitsRecommendationMeta extends Record<string, unknown> {
    rate_limits: RateLimitRecommendationItem[]
}

export type RateLimitsRecommendation = ErrorTrackingRecommendation<RateLimitsRecommendationMeta>

export interface RateLimitRecommendationInfo {
    name: string
    reason: string
}

export const RATE_LIMIT_RECOMMENDATION_INFO: Record<RateLimitRecommendationKey, RateLimitRecommendationInfo> = {
    project: {
        name: 'Project-wide rate limit',
        reason: 'Cap exception volume across the whole project to control ingestion.',
    },
    per_issue: {
        name: 'Per-issue rate limit',
        reason: 'Stop a single noisy issue from dominating your ingestion.',
    },
}

export interface LongRunningIssueItem {
    id: string
    name: string
    description: string | null
    created_at: string
    occurrences: number
    status: ErrorTrackingIssue['status']
}

export interface LongRunningIssuesRecommendationMeta extends Record<string, unknown> {
    issues: LongRunningIssueItem[]
}

export type LongRunningIssuesRecommendation = ErrorTrackingRecommendation<LongRunningIssuesRecommendationMeta>

export interface SourceMapsRecommendationMeta extends Record<string, unknown> {
    total_frames: number
    unresolved_frames: number
    unresolved_pct: number
    threshold_pct: number
    min_sample_frames: number
    lookback_hours: number
}

export type SourceMapsRecommendation = ErrorTrackingRecommendation<SourceMapsRecommendationMeta>

export type AudienceSliceDimension = 'browser' | 'browser_version' | 'os' | 'device_type' | 'user_agent'

export interface AudienceSlice {
    dimension: AudienceSliceDimension
    value: string
    sessions: number
    issue_share: number
    baseline_share: number
    lift: number
}

export interface ImpactLensIssue {
    id: string
    name: string
    description: string | null
    status: ErrorTrackingIssue['status']
}

export interface AudienceSliceIssue extends ImpactLensIssue {
    sessions: number
    slices: AudienceSlice[]
}

export interface AudienceSlicesRecommendationMeta extends Record<string, unknown> {
    window_hours: number
    // Missing on results stored before the lens reported it.
    evaluable?: boolean
    issues: AudienceSliceIssue[]
}

export type AudienceSlicesRecommendation = ErrorTrackingRecommendation<AudienceSlicesRecommendationMeta>

export interface QuickLeaveIssue extends ImpactLensIssue {
    pageviews: number
    quick_leaves: number
    rate: number
    expected_rate: number
    // Of the visitors who left quickly, the share that came back within a day, and the share expected from quick
    // leavers of the same pages without an error. Null without enough of those to compare with.
    returned_rate: number | null
    expected_returned_rate: number | null
}

export interface QuickLeaveRecommendationMeta extends Record<string, unknown> {
    // The two days compared, the most recent first, as the start of each.
    days: string[]
    min_page_seconds: number
    quick_leave_seconds: number
    return_hours: number
    evaluable: boolean
    issues: QuickLeaveIssue[]
}

export type QuickLeaveRecommendation = ErrorTrackingRecommendation<QuickLeaveRecommendationMeta>

export interface LostVisitorIssue extends ImpactLensIssue {
    pageviews: number
    lost: number
    rate: number
    expected_rate: number
}

export interface LostVisitorRecommendationMeta extends Record<string, unknown> {
    days: string[]
    return_hours: number
    evaluable: boolean
    issues: LostVisitorIssue[]
}

export type LostVisitorRecommendation = ErrorTrackingRecommendation<LostVisitorRecommendationMeta>

export type InflatedCountsReason = 'top_session' | 'heavy_sessions' | 'timer'

export interface InflatedCountsIssue extends ImpactLensIssue {
    occurrences: number
    sessions: number
    top_session_share: number
    heavy_session_share: number
    repeating_sessions: number
    timer_sessions: number
    timer_interval_seconds: number | null
    reasons: InflatedCountsReason[]
}

export interface InflatedCountsRecommendationMeta extends Record<string, unknown> {
    window_hours: number
    // Missing on results stored before the lens reported it.
    evaluable?: boolean
    issues: InflatedCountsIssue[]
}

export type InflatedCountsRecommendation = ErrorTrackingRecommendation<InflatedCountsRecommendationMeta>

export interface FlowDropHour {
    hour: string
    starts: number
    rate: number | null
    usual_rate: number | null
}

// An issue in the visits that failed: in the incident's worst hour, the visits that got it on the first page in their
// first seconds finished far less often than the other visits.
export interface FlowDropAttachedIssue extends ImpactLensIssue {
    visits: number
    exposed: number
    exposed_finished: number
    exposed_finish_rate: number
    unexposed_finish_rate: number
}

export interface FlowDropIncident {
    from_path: string
    to_path: string
    hour: string
    hours: number
    // The numbers below are the incident's worst hour against the same hour on the previous days.
    worst_hour: string
    starts: number
    finishes: number
    rate: number
    usual_starts: number
    usual_finishes: number
    usual_rate: number
    hourly: FlowDropHour[]
    issues: FlowDropAttachedIssue[]
}

export interface FlowDropIssue extends FlowDropAttachedIssue {
    from_path: string
    to_path: string
    hour: string
    rate: number
    usual_rate: number
}

export interface FlowDropRecommendationMeta extends Record<string, unknown> {
    window_hours: number
    evaluable: boolean
    flows: { from_path: string; to_path: string }[]
    incidents: FlowDropIncident[]
    // Drops explained by extra traffic with the usual number of finishes, so not shown as broken.
    surges: Omit<FlowDropIncident, 'issues'>[]
    issues: FlowDropIssue[]
}

export type FlowDropRecommendation = ErrorTrackingRecommendation<FlowDropRecommendationMeta>

// One step of a chain in the incident's worst hour, against the same hour on the previous days. A null usual rate or
// ratio means too few visits entered the step to judge it.
export interface FunnelStep {
    from_path: string
    to_path: string
    entered: number
    continued: number
    rate: number | null
    usual_rate: number | null
    ratio: number | null
    // The share of the chain's visits that got as far as this step's second page.
    reached_rate: number
    usual_reached_rate: number
}

export interface FunnelStepIncident {
    pages: string[]
    hour: string
    hours: number
    // The numbers below are the incident's worst hour against the same hour on the previous days.
    worst_hour: string
    starts: number
    finishes: number
    rate: number
    usual_starts: number
    usual_finishes: number
    usual_rate: number
    steps: FunnelStep[]
    // The index in steps of the step furthest below its usual rate, or null when no step can be judged.
    broken_step: number | null
    // The broken step fell far below its usual rate and every other step held.
    clear: boolean
    hourly: FlowDropHour[]
    issues: FlowDropAttachedIssue[]
}

// An issue in the visits that failed the broken step, tested on that step's first page like a Broken flow issue.
export interface FunnelStepIssue extends FlowDropAttachedIssue {
    pages: string[]
    hour: string
    broken_step: number
    from_path: string
    to_path: string
    rate: number
    usual_rate: number
}

export interface FunnelStepRecommendationMeta extends Record<string, unknown> {
    window_hours: number
    evaluable: boolean
    chains: string[][]
    incidents: FunnelStepIncident[]
    // Drops explained by extra traffic with the usual number of finishes, so not shown as broken.
    surges: Omit<FunnelStepIncident, 'issues'>[]
    // Chains that dropped too often in the last 3 weeks to trust a drop, with how many times.
    muted: { pages: string[]; incidents: number }[]
    issues: FunnelStepIssue[]
}

export type FunnelStepRecommendation = ErrorTrackingRecommendation<FunnelStepRecommendationMeta>

export interface SuppressedEvent {
    event: string
    issue_share: number
    comparison_share: number
}

export interface SuppressedEventsIssue extends ImpactLensIssue {
    path: string
    sessions: number
    comparison_sessions: number
    events: SuppressedEvent[]
}

export interface SuppressedEventsRecommendationMeta extends Record<string, unknown> {
    window_hours: number
    evaluable: boolean
    issues: SuppressedEventsIssue[]
}

export type SuppressedEventsRecommendation = ErrorTrackingRecommendation<SuppressedEventsRecommendationMeta>

export interface SupportTicketsIssue extends ImpactLensIssue {
    tickets: number
    sessions: number
    per_1k: number
    ticket_refs: { id: string; number: number }[]
}

export interface SupportTicketsRecommendationMeta extends Record<string, unknown> {
    window_days: number
    evaluable: boolean
    tickets: number
    tickets_with_errors: number
    baseline_per_1k: number
    issues: SupportTicketsIssue[]
}

export type SupportTicketsRecommendation = ErrorTrackingRecommendation<SupportTicketsRecommendationMeta>

interface AccountLensMeta extends Record<string, unknown> {
    window_days: number
    evaluable: boolean
    group_label: string
    active_accounts: number
}

export interface ManyAccountsIssue extends ImpactLensIssue {
    people: number
    sessions: number
    accounts: number
    account_share: number
}

export interface ManyAccountsRecommendationMeta extends AccountLensMeta {
    issues: ManyAccountsIssue[]
}

export type ManyAccountsRecommendation = ErrorTrackingRecommendation<ManyAccountsRecommendationMeta>

export interface OneAccountIssue extends ImpactLensIssue {
    people: number
    sessions: number
    accounts: number
    top_account: { key: string; name: string | null; session_share: number }
}

export interface OneAccountRecommendationMeta extends AccountLensMeta {
    issues: OneAccountIssue[]
}

export type OneAccountRecommendation = ErrorTrackingRecommendation<OneAccountRecommendationMeta>

export type IssueRelation = 'same' | 'causes' | 'together'

export interface RelatedIssuesIssue extends ImpactLensIssue {
    sessions: number
    related: ImpactLensIssue
    related_sessions: number
    // Sessions with both issues at any time.
    both_sessions: number
    // Sessions where both fire within 5 seconds of each other.
    shared_sessions: number
    leads_share: number
    relation: IssueRelation
}

export interface RelatedIssuesRecommendationMeta extends Record<string, unknown> {
    window_hours: number
    // Missing on results stored before the lens reported it.
    evaluable?: boolean
    issues: RelatedIssuesIssue[]
}

export type RelatedIssuesRecommendation = ErrorTrackingRecommendation<RelatedIssuesRecommendationMeta>

export interface FiresOnLeaveIssue extends ImpactLensIssue {
    sessions: number
    leave_share: number
    baseline_leave_share: number
    after_navigation_share: number
    after_action_share: number
    background_share: number
}

export interface FiresOnLeaveRecommendationMeta extends Record<string, unknown> {
    window_hours: number
    evaluable: boolean
    baseline_leave_share: number
    issues: FiresOnLeaveIssue[]
}

export type FiresOnLeaveRecommendation = ErrorTrackingRecommendation<FiresOnLeaveRecommendationMeta>

export type KnownPattern =
    | 'extension'
    | 'resize_observer'
    | 'script_error'
    | 'chunk_load'
    | 'hydration'
    | 'abort'
    | 'network'
    | 'non_error_rejection'
    | 'environment'
    | 'http_status'
    | 'code_bug'
    | 'other'

export interface KnownPatternsIssue extends ImpactLensIssue {
    events: number
    sessions: number
    pattern: KnownPattern
    reasons: ('known_pattern' | 'third_party' | 'no_own_code' | 'app_reported')[]
    no_stack_share: number
    third_party_share: number
    resolved_share: number | null
    // Missing on results stored before the lens reported them.
    own_code_share?: number
    handled_share?: number
}

export interface KnownPatternsRecommendationMeta extends Record<string, unknown> {
    window_hours: number
    // Missing on results stored before the lens reported it.
    evaluable?: boolean
    total_events: number
    pattern_events: number
    classes: { pattern: KnownPattern; events: number }[]
    issues: KnownPatternsIssue[]
}

export type KnownPatternsRecommendation = ErrorTrackingRecommendation<KnownPatternsRecommendationMeta>
