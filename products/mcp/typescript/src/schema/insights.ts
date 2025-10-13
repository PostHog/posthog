import { z } from 'zod'

export const InsightSchema = z.object({
    id: z.number(),
    short_id: z.string(),
    name: z.string().nullish(),
    description: z.string().nullish(),
    filters: z.record(z.any()),
    query: z.any(),
    result: z.any().optional(),
    created_at: z.string(),
    updated_at: z.string(),
    created_by: z
        .object({
            id: z.number(),
            uuid: z.string().uuid(),
            distinct_id: z.string(),
            first_name: z.string(),
            email: z.string(),
        })
        .optional()
        .nullable(),
    favorited: z.boolean().nullish(),
    deleted: z.boolean(),
    dashboard: z.number().nullish(),
    layouts: z.record(z.any()).nullish(),
    color: z.string().nullish(),
    last_refresh: z.string().nullish(),
    refreshing: z.boolean().nullish(),
    tags: z.array(z.string()).nullish(),
})

export const SimpleInsightSchema = InsightSchema.pick({
    id: true,
    name: true,
    short_id: true,
    description: true,
    filters: true,
    query: true,
    created_at: true,
    updated_at: true,
    favorited: true,
})

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
    filters: z.record(z.any()).optional(),
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

export type PostHogInsight = z.infer<typeof InsightSchema>
export type CreateInsightInput = z.infer<typeof CreateInsightInputSchema>
export type UpdateInsightInput = z.infer<typeof UpdateInsightInputSchema>
export type ListInsightsData = z.infer<typeof ListInsightsSchema>
export type SimpleInsight = z.infer<typeof SimpleInsightSchema>

export const SQLInsightResponseSchema = z.array(
    z.object({
        type: z.string(),
        data: z.record(z.any()),
    })
)

export type SQLInsightResponse = z.infer<typeof SQLInsightResponseSchema>
