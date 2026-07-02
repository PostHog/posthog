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
    /** Number of days the brief covers. */
    readonly period_days: number
    /** Generated brief sections: kind, title, markdown, citations, confidence. */
    readonly sections: readonly ProductBriefApiSectionsItem[]
    /** Names of the brief sources that contributed items. */
    readonly sources_used: readonly string[]
    /**
     * Error detail when status is failed.
     * @nullable
     */
    readonly error: string | null
    /**
     * LLM tokens spent generating this brief, when recorded.
     * @nullable
     */
    readonly tokens_used: number | null
    readonly created_at: string
    /** User who requested the brief. */
    readonly created_by: UserBasicApi | null
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedProductBriefListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ProductBriefApi[]
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
