/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `Up` - Up
 * `Down` - Down
 */
export type DirectionEnumApi = (typeof DirectionEnumApi)[keyof typeof DirectionEnumApi]

export const DirectionEnumApi = {
    Up: 'Up',
    Down: 'Down',
} as const

export interface WoWChangeApi {
    /** Absolute percentage change, rounded to nearest integer. */
    percent: number
    /** Direction of the change relative to the prior period.

  * `Up` - Up
  * `Down` - Down */
    direction: DirectionEnumApi
    /** Hex color indicating whether the change is a positive or negative signal. */
    color: string
    /** Short label, e.g. 'Up 12%'. */
    text: string
    /** Verbose label, e.g. 'Up 12% from prior period'. */
    long_text: string
}

export interface NumericMetricApi {
    /** Value for the most recent period. */
    current: number
    /**
     * Value for the prior period, if available.
     * @nullable
     */
    previous: number | null
    /** Period-over-period change, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface DurationMetricApi {
    /** Human-readable duration, e.g. '2m 34s'. */
    current: string
    /**
     * Prior-period duration, e.g. '2m 10s'.
     * @nullable
     */
    previous: string | null
    /** Period-over-period change, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface TopPageApi {
    /** Host for the page, if recorded. */
    host: string
    /** URL path. */
    path: string
    /** Unique visitors in the period. */
    visitors: number
    /** Period-over-period change in visitors, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface TopSourceApi {
    /** Initial referring domain. */
    name: string
    /** Unique visitors from this source. */
    visitors: number
    /** Period-over-period change in visitors, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface GoalApi {
    /** Goal name (action name). */
    name: string
    /** Total conversions in the period. */
    conversions: number
    /** Period-over-period change in conversions, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface WeeklyDigestResponseApi {
    /** Unique visitors. */
    visitors: NumericMetricApi
    /** Total pageviews. */
    pageviews: NumericMetricApi
    /** Total sessions. */
    sessions: NumericMetricApi
    /** Bounce rate (0–100). */
    bounce_rate: NumericMetricApi
    /** Average session duration. */
    avg_session_duration: DurationMetricApi
    /** Top 5 pages by unique visitors. */
    top_pages: TopPageApi[]
    /** Top 5 traffic sources by unique visitors. */
    top_sources: TopSourceApi[]
    /** Goal conversions. */
    goals: GoalApi[]
    /** Link to the Web analytics dashboard for this project. */
    dashboard_url: string
}

/**
 * * `engineering` - Engineering
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
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

export interface WebAnalyticsFilterPresetApi {
    readonly id: string
    readonly short_id: string
    /** @maxLength 400 */
    name: string
    description?: string
    pinned?: boolean
    readonly created_at: string
    readonly created_by: UserBasicApi
    deleted?: boolean
    filters?: unknown
    readonly last_modified_at: string
    readonly last_modified_by: UserBasicApi
}

export interface PaginatedWebAnalyticsFilterPresetListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: WebAnalyticsFilterPresetApi[]
}

export interface PatchedWebAnalyticsFilterPresetApi {
    readonly id?: string
    readonly short_id?: string
    /** @maxLength 400 */
    name?: string
    description?: string
    pinned?: boolean
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    deleted?: boolean
    filters?: unknown
    readonly last_modified_at?: string
    readonly last_modified_by?: UserBasicApi
}

export interface HeatmapResponseItemApi {
    count: number
    pointer_y: number
    pointer_relative_x: number
    pointer_target_fixed: boolean
}

export interface HeatmapsResponseApi {
    results: HeatmapResponseItemApi[]
}

export interface PaginatedHeatmapsResponseListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: HeatmapsResponseApi[]
}

/**
 * * `screenshot` - Screenshot
 * `iframe` - Iframe
 * `recording` - Recording
 */
export type HeatmapScreenshotResponseTypeEnumApi =
    (typeof HeatmapScreenshotResponseTypeEnumApi)[keyof typeof HeatmapScreenshotResponseTypeEnumApi]

export const HeatmapScreenshotResponseTypeEnumApi = {
    Screenshot: 'screenshot',
    Iframe: 'iframe',
    Recording: 'recording',
} as const

/**
 * * `processing` - Processing
 * `completed` - Completed
 * `failed` - Failed
 */
export type HeatmapScreenshotResponseStatusEnumApi =
    (typeof HeatmapScreenshotResponseStatusEnumApi)[keyof typeof HeatmapScreenshotResponseStatusEnumApi]

export const HeatmapScreenshotResponseStatusEnumApi = {
    Processing: 'processing',
    Completed: 'completed',
    Failed: 'failed',
} as const

export type HeatmapScreenshotResponseApiSnapshotsItem = { [key: string]: unknown }

export interface HeatmapScreenshotResponseApi {
    readonly id: string
    readonly short_id: string
    /**
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** @maxLength 2000 */
    url: string
    /**
     * URL for fetching heatmap data
     * @maxLength 2000
     * @nullable
     */
    data_url?: string | null
    target_widths?: unknown
    type?: HeatmapScreenshotResponseTypeEnumApi
    readonly status: HeatmapScreenshotResponseStatusEnumApi
    readonly has_content: boolean
    readonly snapshots: readonly HeatmapScreenshotResponseApiSnapshotsItem[]
    deleted?: boolean
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    /** @nullable */
    readonly exception: string | null
}

export interface PaginatedHeatmapScreenshotResponseListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: HeatmapScreenshotResponseApi[]
}

export type PatchedHeatmapScreenshotResponseApiSnapshotsItem = { [key: string]: unknown }

export interface PatchedHeatmapScreenshotResponseApi {
    readonly id?: string
    readonly short_id?: string
    /**
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** @maxLength 2000 */
    url?: string
    /**
     * URL for fetching heatmap data
     * @maxLength 2000
     * @nullable
     */
    data_url?: string | null
    target_widths?: unknown
    type?: HeatmapScreenshotResponseTypeEnumApi
    readonly status?: HeatmapScreenshotResponseStatusEnumApi
    readonly has_content?: boolean
    readonly snapshots?: readonly PatchedHeatmapScreenshotResponseApiSnapshotsItem[]
    deleted?: boolean
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    readonly updated_at?: string
    /** @nullable */
    readonly exception?: string | null
}

export type WebAnalyticsWeeklyDigestParams = {
    /**
     * When true (default), include period-over-period change for each metric comparing against the prior equal-length period. Set to false to skip the comparison query (faster).
     */
    compare?: boolean
    /**
     * Lookback window in days (1–90). Defaults to 7.
     */
    days?: number
}

export type WebAnalyticsFilterPresetsListParams = {
    created_by?: number
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    short_id?: string
}

export type HeatmapsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type SavedListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
