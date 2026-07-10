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
    /** Per-config tunables overriding the system defaults. Omitted knobs keep their default. */
    settings?: BriefSettingsApi
    /** Whether this config generates briefs. */
    enabled?: boolean
    /** Soft-delete flag. Deleted configs are hidden from lists but recoverable by patching this back to false. */
    deleted?: boolean
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
    /** Per-config tunables overriding the system defaults. Omitted knobs keep their default. */
    settings?: BriefSettingsApi
    /** Whether this config generates briefs. */
    enabled?: boolean
    /** Soft-delete flag. Deleted configs are hidden from lists but recoverable by patching this back to false. */
    deleted?: boolean
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
    /** Generated brief sections: kind, title, markdown, citations, confidence. */
    readonly sections: readonly ProductBriefApiSectionsItem[]
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
    /** Period the brief should cover. Defaults to the last 7 days. */
    period?: PeriodApi
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
