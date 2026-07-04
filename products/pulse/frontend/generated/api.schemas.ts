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
    /** Free-text focus steering gathering and tone, e.g. "we're the feature flags team". */
    focus_prompt?: string
    /** Anchor resources the brief gathers movements from. Empty anchors fall back to the team's most recently accessed dashboards. */
    anchors?: BriefAnchorsApi
    /** Free-text goal this focus drives toward, e.g. "increase subscription usage". Briefs open with progress toward it. */
    goal?: string
    /** Insight whose trend measures progress toward the goal. Null when the goal is qualitative. */
    goal_metric?: BriefGoalMetricApi | null
    /** Whether this config generates briefs. */
    enabled?: boolean
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
    /** Free-text focus steering gathering and tone, e.g. "we're the feature flags team". */
    focus_prompt?: string
    /** Anchor resources the brief gathers movements from. Empty anchors fall back to the team's most recently accessed dashboards. */
    anchors?: BriefAnchorsApi
    /** Free-text goal this focus drives toward, e.g. "increase subscription usage". Briefs open with progress toward it. */
    goal?: string
    /** Insight whose trend measures progress toward the goal. Null when the goal is qualitative. */
    goal_metric?: BriefGoalMetricApi | null
    /** Whether this config generates briefs. */
    enabled?: boolean
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
    /** Number of days the brief covers. */
    readonly period_days: number
    /** Names of the brief sources that contributed items. */
    readonly sources_used: readonly string[]
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

export type ProductBriefApiSectionsItem = { [key: string]: unknown }

export type ProductBriefApiInvestigationItem = { [key: string]: unknown }

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
    /** Number of days the brief covers. */
    readonly period_days: number
    /** Generated brief sections: kind, title, markdown, citations, confidence. */
    readonly sections: readonly ProductBriefApiSectionsItem[]
    /** Goal-investigation findings in citation order (a `query:<n>` citation is a 1-based index into this list): question, hogql, result_summary, succeeded, error_type, elapsed_seconds. Empty for goal-less briefs. */
    readonly investigation: readonly ProductBriefApiInvestigationItem[]
    /** Names of the brief sources that contributed items. */
    readonly sources_used: readonly string[]
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
    /**
     * Number of days the brief should cover. Defaults to 7.
     * @minimum 1
     * @maximum 90
     */
    period_days?: number
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

export type OpportunityApiEvidenceItem = { [key: string]: unknown }

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
    /** Evidence refs backing the opportunity: type, ref, and label per entry. */
    readonly evidence: readonly OpportunityApiEvidenceItem[]
    /** Whether this opportunity plausibly advances the focus goal of the brief it surfaced in. */
    readonly goal_relevant: boolean
    /**
     * The brief this opportunity first surfaced in, if any.
     * @nullable
     */
    readonly first_seen_brief: string | null
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
