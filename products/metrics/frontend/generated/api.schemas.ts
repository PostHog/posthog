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
 * * `disabled` - Disabled
 * `dry_run` - Dry Run
 * `live` - Live
 */
export type EventFilterConfigModeEnumApi =
    (typeof EventFilterConfigModeEnumApi)[keyof typeof EventFilterConfigModeEnumApi]

export const EventFilterConfigModeEnumApi = {
    Disabled: 'disabled',
    DryRun: 'dry_run',
    Live: 'live',
} as const

export interface EventFilterConfigApi {
    readonly id: string
    mode?: EventFilterConfigModeEnumApi
    /** Boolean expression tree. Nodes: {"type": "and"|"or", "children": [...]}, {"type": "not", "child": {...}}, {"type": "condition", "field": "event_name"|"distinct_id", "operator": "exact"|"contains", "value": "<string>"} */
    filter_tree?: unknown | null
    /** Test events to validate the filter. Each: {"event_name": "...", "distinct_id": "...", "expected_result": "drop"|"ingest"} */
    test_cases?: unknown
    readonly created_at: string
    readonly updated_at: string
}

/**
 * * `numeric` - numeric
 * `currency` - currency
 */
export type GroupUsageMetricFormatEnumApi =
    (typeof GroupUsageMetricFormatEnumApi)[keyof typeof GroupUsageMetricFormatEnumApi]

export const GroupUsageMetricFormatEnumApi = {
    Numeric: 'numeric',
    Currency: 'currency',
} as const

/**
 * * `number` - number
 * `sparkline` - sparkline
 */
export type GroupUsageMetricDisplayEnumApi =
    (typeof GroupUsageMetricDisplayEnumApi)[keyof typeof GroupUsageMetricDisplayEnumApi]

export const GroupUsageMetricDisplayEnumApi = {
    Number: 'number',
    Sparkline: 'sparkline',
} as const

export interface GroupUsageMetricApi {
    readonly id: string
    /** @maxLength 255 */
    name: string
    format?: GroupUsageMetricFormatEnumApi
    /**
     * In days
     * @minimum -2147483648
     * @maximum 2147483647
     */
    interval?: number
    display?: GroupUsageMetricDisplayEnumApi
    filters: unknown
}

export interface PaginatedGroupUsageMetricListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: GroupUsageMetricApi[]
}

export interface PatchedGroupUsageMetricApi {
    readonly id?: string
    /** @maxLength 255 */
    name?: string
    format?: GroupUsageMetricFormatEnumApi
    /**
     * In days
     * @minimum -2147483648
     * @maximum 2147483647
     */
    interval?: number
    display?: GroupUsageMetricDisplayEnumApi
    filters?: unknown
}

export type GroupsTypesMetricsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
