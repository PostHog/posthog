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
 * * `session_analysis` - Session analysis
 */
export type SignalSourceConfigSourceTypeEnumApi =
    (typeof SignalSourceConfigSourceTypeEnumApi)[keyof typeof SignalSourceConfigSourceTypeEnumApi]

export const SignalSourceConfigSourceTypeEnumApi = {
    SessionAnalysis: 'session_analysis',
} as const

export interface SignalSourceConfigApi {
    readonly id: string
    source_type: SignalSourceConfigSourceTypeEnumApi
    enabled?: boolean
    config?: unknown
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedSignalSourceConfigListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SignalSourceConfigApi[]
}

export type SignalSourceConfigsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
