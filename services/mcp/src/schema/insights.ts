import { z } from 'zod'

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

export const CreateInsightInputSchema = z.object({
    name: z.string(),
    query: z.object({
        kind: z.union([z.literal('InsightVizNode'), z.literal('DataVisualizationNode')]),
        source: z
            .any()
            .describe(
                'For new insights, use the query from your successful query-run tool call. For updates, the existing query can optionally be reused.'
            ), // NOTE: This is intentionally z.any() to avoid populating the context with the complicated query schema, but we prompt the LLM to use 'query-run' to check queries, before creating insights.
    }),
    description: z.string().optional(),
    favorited: z.boolean(),
    tags: z.array(z.string()).optional(),
})

export const UpdateInsightInputSchema = z.object({
    name: z.string().optional(),
    description: z.string().optional(),
    filters: z.record(z.string(), z.any()).optional(),
    query: z.object({
        kind: z.union([z.literal('InsightVizNode'), z.literal('DataVisualizationNode')]),
        source: z
            .any()
            .describe(
                'For new insights, use the query from your successful query-run tool call. For updates, the existing query can optionally be reused'
            ), // NOTE: This is intentionally z.any() to avoid populating the context with the complicated query schema, and to allow the LLM to make a change to an existing insight whose schema we do not support in our simplified subset of the full insight schema.
    }),
    favorited: z.boolean().optional(),
    dashboard: z.number().optional(),
    tags: z.array(z.string()).optional(),
})

export const ListInsightsSchema = z.object({
    limit: z.number().optional(),
    offset: z.number().optional(),
    favorited: z.boolean().optional(),
    search: z.string().optional(),
})

export type CreateInsightInput = z.infer<typeof CreateInsightInputSchema>
export type UpdateInsightInput = z.infer<typeof UpdateInsightInputSchema>
export type ListInsightsData = z.infer<typeof ListInsightsSchema>

export type SQLInsightResponse = Array<{
    type: string
    data: Record<string, unknown>
}>
