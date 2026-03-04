import { z } from 'zod'

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

export interface PostHogInsight {
    id: number
    short_id: string
    name?: string | null
    description?: string | null
    filters: Record<string, unknown>
    query?: unknown
    result?: unknown
    created_at: string
    updated_at: string
    created_by?: {
        id: number
        uuid: string
        distinct_id: string
        first_name: string
        email: string
    } | null
    favorited?: boolean | null
    deleted: boolean
    dashboard?: number | null
    layouts?: Record<string, unknown> | null
    color?: string | null
    last_refresh?: string | null
    refreshing?: boolean | null
    tags?: string[] | null
}

export interface SimpleInsight {
    id: number
    name?: string | null
    short_id: string
    description?: string | null
    filters: Record<string, unknown>
    query?: unknown
    created_at: string
    updated_at: string
    favorited?: boolean | null
}

export type SQLInsightResponse = Array<{
    type: string
    data: Record<string, unknown>
}>
