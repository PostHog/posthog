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
 * Optional conversion goal — either ActionConversionGoal ({actionId}) or CustomEventConversionGoal ({customEventName}).
 * @nullable
 */
export type AISummaryFilterSpecApiConversionGoal = {
    /** ID of the action used as conversion goal. */
    actionId?: number
    /** Custom event name used as conversion goal. */
    customEventName?: string
    [key: string]: unknown
} | null

/**
 * * `exact` - exact
 * `is_not` - is_not
 * `icontains` - icontains
 * `not_icontains` - not_icontains
 * `regex` - regex
 * `not_regex` - not_regex
 * `gt` - gt
 * `lt` - lt
 * `gte` - gte
 * `lte` - lte
 * `is_set` - is_set
 * `is_not_set` - is_not_set
 * `is_date_exact` - is_date_exact
 * `is_date_after` - is_date_after
 * `is_date_before` - is_date_before
 * `in` - in
 * `not_in` - not_in
 */
export type PropertyItemOperatorEnumApi = (typeof PropertyItemOperatorEnumApi)[keyof typeof PropertyItemOperatorEnumApi]

export const PropertyItemOperatorEnumApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
    Gt: 'gt',
    Lt: 'lt',
    Gte: 'gte',
    Lte: 'lte',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
    IsDateExact: 'is_date_exact',
    IsDateAfter: 'is_date_after',
    IsDateBefore: 'is_date_before',
    In: 'in',
    NotIn: 'not_in',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * * `event` - event
 * `event_metadata` - event_metadata
 * `feature` - feature
 * `person` - person
 * `cohort` - cohort
 * `element` - element
 * `static-cohort` - static-cohort
 * `dynamic-cohort` - dynamic-cohort
 * `precalculated-cohort` - precalculated-cohort
 * `group` - group
 * `recording` - recording
 * `log_entry` - log_entry
 * `behavioral` - behavioral
 * `session` - session
 * `hogql` - hogql
 * `data_warehouse` - data_warehouse
 * `data_warehouse_person_property` - data_warehouse_person_property
 * `error_tracking_issue` - error_tracking_issue
 * `log` - log
 * `log_attribute` - log_attribute
 * `log_resource_attribute` - log_resource_attribute
 * `span` - span
 * `span_attribute` - span_attribute
 * `span_resource_attribute` - span_resource_attribute
 * `revenue_analytics` - revenue_analytics
 * `flag` - flag
 * `workflow_variable` - workflow_variable
 */
export type PropertyFilterTypeEnumApi = (typeof PropertyFilterTypeEnumApi)[keyof typeof PropertyFilterTypeEnumApi]

export const PropertyFilterTypeEnumApi = {
    Event: 'event',
    EventMetadata: 'event_metadata',
    Feature: 'feature',
    Person: 'person',
    Cohort: 'cohort',
    Element: 'element',
    StaticCohort: 'static-cohort',
    DynamicCohort: 'dynamic-cohort',
    PrecalculatedCohort: 'precalculated-cohort',
    Group: 'group',
    Recording: 'recording',
    LogEntry: 'log_entry',
    Behavioral: 'behavioral',
    Session: 'session',
    Hogql: 'hogql',
    DataWarehouse: 'data_warehouse',
    DataWarehousePersonProperty: 'data_warehouse_person_property',
    ErrorTrackingIssue: 'error_tracking_issue',
    Log: 'log',
    LogAttribute: 'log_attribute',
    LogResourceAttribute: 'log_resource_attribute',
    Span: 'span',
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
    RevenueAnalytics: 'revenue_analytics',
    Flag: 'flag',
    WorkflowVariable: 'workflow_variable',
} as const

export const PropertyItemApiType = { ...PropertyFilterTypeEnumApi, ...BlankEnumApi } as const
export interface PropertyItemApi {
    /** Key of the property you're filtering on. For example `email` or `$current_url` */
    key: string
    /** Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]` */
    value: string | number | boolean | (string | number)[]
    operator?: PropertyItemOperatorEnumApi | BlankEnumApi | null
    type?: (typeof PropertyItemApiType)[keyof typeof PropertyItemApiType]
}

export interface AISummaryFilterSpecApi {
    /** Start of the analysis window. Accepts a relative spec like '-7d' or an ISO date like '2026-01-01'. */
    date_from: string
    /**
     * End of the analysis window. Accepts the same formats as date_from, or null for an open-ended range up to now.
     * @nullable
     */
    date_to?: string | null
    /** When true, include period-over-period change for each metric against the prior equal-length period. */
    compare?: boolean
    /** Property filters applied to all underlying queries. */
    properties?: PropertyItemApi[]
    /**
     * Optional conversion goal — either ActionConversionGoal ({actionId}) or CustomEventConversionGoal ({customEventName}).
     * @nullable
     */
    conversion_goal?: AISummaryFilterSpecApiConversionGoal
    /** Whether to exclude internal/test-account events from the analysis. */
    filter_test_accounts?: boolean
    /** When true, apply the team's path-cleaning rules before bucketing by page path. */
    do_path_cleaning?: boolean
}

export interface AISummaryResponseApi {
    /** LLM-generated plain-text summary, up to ~150 words. */
    summary_text: string
    /** When the summary was generated. */
    created_at: string
    /** LLM model identifier used to generate this summary. */
    model_id: string
    /** True when this summary was reused from the cache; false when freshly generated. */
    cached: boolean
}

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

export type WebAnalyticsAiSummaryParams = {
    /**
     * When true, only return a cached summary if one is fresh (HTTP 204 on a miss) and never invoke the LLM. Used by the dashboard to hydrate a cached summary without incurring cost.
     */
    check?: boolean
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
