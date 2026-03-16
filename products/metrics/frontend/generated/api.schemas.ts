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
export type DisplayEnumApi = (typeof DisplayEnumApi)[keyof typeof DisplayEnumApi]

export const DisplayEnumApi = {
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
    display?: DisplayEnumApi
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
    display?: DisplayEnumApi
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
