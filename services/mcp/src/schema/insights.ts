import type { Schemas } from '@/api/generated'

/**
 * The generated Schemas.Insight has many fields incorrectly typed as `string`
 * due to missing @extend_schema_field decorators on the Django serializer's
 * SerializerMethodFields. This type corrects those fields and adds fields
 * that are excluded from the OpenAPI schema but returned at runtime.
 */
export type Insight = Omit<
    Schemas.Insight,
    | 'result'
    | 'hasMore'
    | 'columns'
    | 'is_cached'
    | 'query_status'
    | 'hogql'
    | 'types'
    | 'resolved_date_range'
    | 'alerts'
    | 'last_viewed_at'
    | 'last_refresh'
    | 'cache_target_age'
    | 'next_allowed_client_refresh'
> & {
    result: unknown
    hasMore: boolean | null
    columns: unknown[] | null
    is_cached: boolean
    query_status: Record<string, unknown> | null
    hogql: string | null
    types: unknown[] | null
    resolved_date_range: { date_from: string; date_to: string } | null
    alerts: unknown[]
    last_viewed_at: string | null
    last_refresh: string | null
    cache_target_age: string | null
    next_allowed_client_refresh: string | null
    filters: Record<string, unknown>
    refreshing: boolean | null
    saved: boolean
}
