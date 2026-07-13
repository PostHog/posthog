/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface BriefAnchorsApi {
    /** IDs of the dashboards this brief is anchored on. */
    dashboards?: number[]
    /** Short IDs of the insights this brief is anchored on. */
    insights?: string[]
}

export interface BriefGoalMetricApi {
    /** Short ID of the team-owned trends insight tracking progress toward the goal. */
    insight_short_id: string
}

export interface BriefSettingsApi {
    /**
     * Minimum absolute percent change for a movement to count as significant. Default 20.
     * @minimum 1
     * @maximum 1000
     */
    min_abs_change_pct?: number
    /**
     * Minimum per-sample baseline volume before a movement is considered. Default 10.
     * @minimum 0
     * @maximum 1000000
     */
    min_baseline_value?: number
    /**
     * Maximum anchor insights gathered per brief. Default 10.
     * @minimum 1
     * @maximum 100
     */
    max_anchor_insights?: number
    /**
     * How many recent dashboards to pull insights from when no anchors are set. Default 3.
     * @minimum 1
     * @maximum 20
     */
    fallback_dashboard_count?: number
    /**
     * Minimum confidence for a section or opportunity to survive the gate. Default 0.6.
     * @minimum 0
     * @maximum 1
     */
    confidence_threshold?: number
    /**
     * Maximum opportunities kept per brief. Default 3.
     * @minimum 1
     * @maximum 20
     */
    max_opportunities?: number
    /**
     * Maximum annotations gathered as context per brief. Default 20.
     * @minimum 1
     * @maximum 100
     */
    max_annotations?: number
}

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface BriefConfigApi {
    readonly id: string
    /**
     * Human-readable name for this brief focus.
     * @maxLength 400
     */
    name: string
    /**
     * Free-text focus steering gathering and tone, e.g. "we're the feature flags team". Max 2000 characters.
     * @maxLength 2000
     */
    focus_prompt?: string
    /** Anchor resources the brief gathers movements from. Empty anchors fall back to the team's most recently accessed dashboards. */
    anchors?: BriefAnchorsApi
    /** Free-text goal this focus drives toward, e.g. "increase subscription usage". Briefs open with progress toward it. */
    goal: string
    /** Insight whose trend measures progress toward the goal. Null when the goal is qualitative. */
    goal_metric?: BriefGoalMetricApi | null
    /** Per-config tunables overriding the system defaults. Omitted knobs keep their default. */
    settings?: BriefSettingsApi
    /** Whether this config generates briefs. */
    enabled?: boolean
    /** Soft-delete flag. Deleted configs are hidden from lists but recoverable by patching this back to false. */
    deleted?: boolean
    /**
     * How many days old a surfaced opportunity must be before the accountability section re-scores it. Defaults to 7.
     * @minimum 1
     * @maximum 2147483647
     */
    accountability_min_age_days?: number
    readonly created_at: string
    /** User who created the config. */
    readonly created_by: UserBasicApi | null
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedBriefConfigListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: BriefConfigApi[]
}

export interface PatchedBriefConfigApi {
    readonly id?: string
    /**
     * Human-readable name for this brief focus.
     * @maxLength 400
     */
    name?: string
    /**
     * Free-text focus steering gathering and tone, e.g. "we're the feature flags team". Max 2000 characters.
     * @maxLength 2000
     */
    focus_prompt?: string
    /** Anchor resources the brief gathers movements from. Empty anchors fall back to the team's most recently accessed dashboards. */
    anchors?: BriefAnchorsApi
    /** Free-text goal this focus drives toward, e.g. "increase subscription usage". Briefs open with progress toward it. */
    goal?: string
    /** Insight whose trend measures progress toward the goal. Null when the goal is qualitative. */
    goal_metric?: BriefGoalMetricApi | null
    /** Per-config tunables overriding the system defaults. Omitted knobs keep their default. */
    settings?: BriefSettingsApi
    /** Whether this config generates briefs. */
    enabled?: boolean
    /** Soft-delete flag. Deleted configs are hidden from lists but recoverable by patching this back to false. */
    deleted?: boolean
    /**
     * How many days old a surfaced opportunity must be before the accountability section re-scores it. Defaults to 7.
     * @minimum 1
     * @maximum 2147483647
     */
    accountability_min_age_days?: number
    readonly created_at?: string
    /** User who created the config. */
    readonly created_by?: UserBasicApi | null
    /** @nullable */
    readonly updated_at?: string | null
}

/**
 * * `generating` - Generating
 * * `ready` - Ready
 * * `quiet` - Quiet
 * * `failed` - Failed
 */
export type ProductBriefStatusEnumApi = (typeof ProductBriefStatusEnumApi)[keyof typeof ProductBriefStatusEnumApi]

export const ProductBriefStatusEnumApi = {
    Generating: 'generating',
    Ready: 'ready',
    Quiet: 'quiet',
    Failed: 'failed',
} as const

/**
 * * `on_demand` - On Demand
 * * `scheduled` - Scheduled
 */
export type ProductBriefTriggerEnumApi = (typeof ProductBriefTriggerEnumApi)[keyof typeof ProductBriefTriggerEnumApi]

export const ProductBriefTriggerEnumApi = {
    OnDemand: 'on_demand',
    Scheduled: 'scheduled',
} as const

/**
 * * `last_n_days` - last_n_days
 * * `since_last_run` - since_last_run
 */
export type PeriodTypeEnumApi = (typeof PeriodTypeEnumApi)[keyof typeof PeriodTypeEnumApi]

export const PeriodTypeEnumApi = {
    LastNDays: 'last_n_days',
    SinceLastRun: 'since_last_run',
} as const

export interface PeriodApi {
    /** How the brief window is chosen: a fixed lookback (last_n_days) or since the last ready brief.
     *
     * * `last_n_days` - last_n_days
     * * `since_last_run` - since_last_run */
    period_type: PeriodTypeEnumApi
    /**
     * Lookback length in days. Required and used only when period_type is last_n_days.
     * @minimum 1
     * @maximum 90
     */
    days?: number
}

/**
 * * `none` - none
 * * `ok` - ok
 * * `unavailable` - unavailable
 */
export type MetricStateEnumApi = (typeof MetricStateEnumApi)[keyof typeof MetricStateEnumApi]

export const MetricStateEnumApi = {
    None: 'none',
    Ok: 'ok',
    Unavailable: 'unavailable',
} as const

/**
 * Frozen goal-metric snapshot from generation: where the goal metric stood when the brief ran.
 * Read-only projection of the stored GoalStatus (generation/goal.py).
 */
export interface BriefGoalStatusApi {
    /** 'none' (qualitative goal, no metric), 'ok' (rates below are populated), or 'unavailable' (a metric is configured but could not be read this period).
     *
     * * `none` - none
     * * `ok` - ok
     * * `unavailable` - unavailable */
    metric_state: MetricStateEnumApi
    /**
     * Name of the insight tracking the goal, when one is configured.
     * @nullable
     */
    metric_label?: string | null
    /**
     * Short ID of the goal-metric insight, for linking through to it.
     * @nullable
     */
    insight_short_id?: string | null
    /**
     * Per-day rate over the brief's period, e.g. '4.2/day avg'.
     * @nullable
     */
    current_rate?: string | null
    /**
     * Per-day rate over the preceding period, for comparison.
     * @nullable
     */
    previous_rate?: string | null
    /**
     * Percentage change of current vs previous rate; null off a zero baseline.
     * @nullable
     */
    delta_pct?: number | null
}

export interface ProductBriefListApi {
    readonly id: string
    /**
     * The brief config this brief was generated for, if any.
     * @nullable
     */
    readonly config: string | null
    /** Lifecycle status: generating, ready, quiet (nothing confident to say), or failed.
     *
     * * `generating` - Generating
     * * `ready` - Ready
     * * `quiet` - Quiet
     * * `failed` - Failed */
    readonly status: ProductBriefStatusEnumApi
    /** What started the generation: on_demand or scheduled.
     *
     * * `on_demand` - On Demand
     * * `scheduled` - Scheduled */
    readonly trigger: ProductBriefTriggerEnumApi
    /** The resolved-at-gather period spec the brief covers. */
    readonly period: PeriodApi
    /** Names of the brief sources that contributed items. */
    readonly sources_used: readonly string[]
    /** Frozen goal-metric progress snapshot from when the brief was generated. Null for config-less briefs and briefs generated from an empty gather. */
    readonly goal_status: BriefGoalStatusApi | null
    /**
     * Error detail when status is failed.
     * @nullable
     */
    readonly error: string | null
    readonly created_at: string
    /** User who requested the brief. */
    readonly created_by: UserBasicApi | null
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedProductBriefListListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ProductBriefListApi[]
}

export interface BriefSectionCitationApi {
    /** Cited resource type, e.g. insight or dashboard. */
    type: string
    /** Stable id of the cited resource within its type. */
    ref: string
    /** Human-readable name of the cited resource, for display. */
    label: string
    /** Deep link into the app, or empty when the resource has no navigable target. */
    url: string
}

export interface BriefSectionApi {
    /** Section kind, e.g. what_happened or what_to_build_next. */
    kind: string
    /** Short section heading. */
    title: string
    /** Section body rendered as markdown. */
    markdown: string
    /** PostHog resources this section cites as evidence. */
    citations: BriefSectionCitationApi[]
    /** Model confidence in this section, 0.0-1.0. */
    confidence: number
}

export interface AccountabilityStatusLineApi {
    /** ID of the opportunity this status line re-scores. */
    opportunity_id: string
    /** Opportunity kind at the time the brief was generated. */
    kind: string
    /** Opportunity lifecycle status at the time the brief was generated. */
    status: string
    /** Opportunity title. */
    title: string
    /** How many days ago the opportunity was first suggested. */
    age_days: number
    /** Human-readable metric rate at suggestion time. */
    baseline_summary: string
    /** Human-readable metric rate now, or "metric no longer available" when it can't be re-read. */
    current_summary: string
    /**
     * Percentage change from the baseline rate to the current rate; null when it can't be computed.
     * @nullable
     */
    delta_pct: number | null
}

export interface ProductBriefApi {
    readonly id: string
    /**
     * The brief config this brief was generated for, if any.
     * @nullable
     */
    readonly config: string | null
    /** Lifecycle status: generating, ready, quiet (nothing confident to say), or failed.
     *
     * * `generating` - Generating
     * * `ready` - Ready
     * * `quiet` - Quiet
     * * `failed` - Failed */
    readonly status: ProductBriefStatusEnumApi
    /** What started the generation: on_demand or scheduled.
     *
     * * `on_demand` - On Demand
     * * `scheduled` - Scheduled */
    readonly trigger: ProductBriefTriggerEnumApi
    /** The resolved-at-gather period spec the brief covers. */
    readonly period: PeriodApi
    /** Generated brief sections, most important first. */
    readonly sections: readonly BriefSectionApi[]
    /** Then-vs-now re-scores of past opportunities surfaced with this brief. */
    readonly accountability: readonly AccountabilityStatusLineApi[]
    /** Names of the brief sources that contributed items. */
    readonly sources_used: readonly string[]
    /** Frozen goal-metric progress snapshot from when the brief was generated. Null for config-less briefs and briefs generated from an empty gather. */
    readonly goal_status: BriefGoalStatusApi | null
    /**
     * Error detail when status is failed.
     * @nullable
     */
    readonly error: string | null
    readonly created_at: string
    /** User who requested the brief. */
    readonly created_by: UserBasicApi | null
    /** @nullable */
    readonly updated_at: string | null
}

export interface GenerateBriefRequestApi {
    /**
     * Optional brief config to generate for. Omit for the zero-config default brief.
     * @nullable
     */
    config_id?: string | null
    /** Period the brief should cover. Defaults to the last 7 days. */
    period?: PeriodApi
}

/**
 * * `build` - Build
 * * `fix` - Fix
 * * `instrument` - Instrument
 */
export type OpportunityKindEnumApi = (typeof OpportunityKindEnumApi)[keyof typeof OpportunityKindEnumApi]

export const OpportunityKindEnumApi = {
    Build: 'build',
    Fix: 'fix',
    Instrument: 'instrument',
} as const

/**
 * * `open` - Open
 * * `dismissed` - Dismissed
 * * `acted` - Acted
 * * `resolved` - Resolved
 */
export type OpportunityStatusEnumApi = (typeof OpportunityStatusEnumApi)[keyof typeof OpportunityStatusEnumApi]

export const OpportunityStatusEnumApi = {
    Open: 'open',
    Dismissed: 'dismissed',
    Acted: 'acted',
    Resolved: 'resolved',
} as const

export interface ResourceLinkApi {
    /** The kind of PostHog resource this link points at. */
    type: string
    /** Stable identifier of the referenced resource (e.g. an insight short id). */
    ref: string
    /** Human-readable label for the resource. */
    label: string
    /** Deep link into the app, or empty when there is none. */
    url: string
}

export interface OpportunityApi {
    readonly id: string
    /** What the opportunity asks for: build (product opportunity), fix (broken PostHog resource), or instrument (missing tracking).
     *
     * * `build` - Build
     * * `fix` - Fix
     * * `instrument` - Instrument */
    readonly kind: OpportunityKindEnumApi
    /** Lifecycle status: open, dismissed, acted, or resolved.
     *
     * * `open` - Open
     * * `dismissed` - Dismissed
     * * `acted` - Acted
     * * `resolved` - Resolved */
    readonly status: OpportunityStatusEnumApi
    /** Short, actionable opportunity title. */
    readonly title: string
    /** What was observed and why it matters. */
    readonly summary: string
    /** The concrete next step suggested for the team. */
    readonly suggested_action: string
    /** Evidence links backing the opportunity: type, ref, label, and url per entry. */
    readonly evidence: readonly ResourceLinkApi[]
    /** Whether this opportunity plausibly advances the focus goal of the brief it surfaced in. */
    readonly goal_relevant: boolean
    /** The brief this opportunity first surfaced in. */
    readonly first_seen_brief: string
    readonly created_at: string
    /** User who created the opportunity. */
    readonly created_by: UserBasicApi | null
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedOpportunityListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: OpportunityApi[]
}

export type PulseBriefConfigsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type PulseBriefsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type PulseOpportunitiesListParams = {
    /**
     * Filter by opportunity kind.
     */
    kind?: PulseOpportunitiesListKind
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter by lifecycle status.
     */
    status?: PulseOpportunitiesListStatus
}

export type PulseOpportunitiesListKind = (typeof PulseOpportunitiesListKind)[keyof typeof PulseOpportunitiesListKind]

export const PulseOpportunitiesListKind = {
    Build: 'build',
    Fix: 'fix',
    Instrument: 'instrument',
} as const

export type PulseOpportunitiesListStatus =
    (typeof PulseOpportunitiesListStatus)[keyof typeof PulseOpportunitiesListStatus]

export const PulseOpportunitiesListStatus = {
    Acted: 'acted',
    Dismissed: 'dismissed',
    Open: 'open',
    Resolved: 'resolved',
} as const
