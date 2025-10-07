import { z } from 'zod'

export const DashboardTileSchema = z.object({
    insight: z.object({
        short_id: z.string(),
        name: z.string(),
        derived_name: z.string().nullable(),
        description: z.string().nullable(),
        query: z.object({
            kind: z.union([z.literal('InsightVizNode'), z.literal('DataVisualizationNode')]),
            source: z
                .any()
                .describe(
                    'For new insights, use the query from your successful query-run tool call. For updates, the existing query can optionally be reused.'
                ), // NOTE: This is intentionally z.any() to avoid populating the context with the complicated query schema, but we prompt the LLM to use 'query-run' to check queries, before creating insights.
        }),
        created_at: z.string().nullish(),
        updated_at: z.string().nullish(),
        favorited: z.boolean().nullish(),
        tags: z.array(z.string()).nullish(),
    }),
    order: z.number(),
    color: z.string().nullish(),
    layouts: z.record(z.any()).nullish(),
    last_refresh: z.string().nullish(),
    is_cached: z.boolean().nullish(),
})

// Base dashboard schema from PostHog API
export const DashboardSchema = z.object({
    id: z.number().int().positive(),
    name: z.string(),
    description: z.string().nullish(),
    pinned: z.boolean().nullish(),
    created_at: z.string(),
    created_by: z
        .object({
            email: z.string().email(),
        })
        .optional()
        .nullable(),
    is_shared: z.boolean().nullish(),
    deleted: z.boolean().nullish(),
    filters: z.record(z.any()).nullish(),
    variables: z.record(z.any()).nullish(),
    tags: z.array(z.string()).nullish(),
    tiles: z.array(DashboardTileSchema.nullish()).nullish(),
})

export const SimpleDashboardSchema = DashboardSchema.pick({
    id: true,
    name: true,
    description: true,
    tiles: true,
})

// Input schema for creating dashboards
export const CreateDashboardInputSchema = z.object({
    name: z.string().min(1, 'Dashboard name is required'),
    description: z.string().optional(),
    pinned: z.boolean().optional(),
    tags: z.array(z.string()).optional(),
})

// Input schema for updating dashboards
export const UpdateDashboardInputSchema = z.object({
    name: z.string().optional(),
    description: z.string().optional(),
    pinned: z.boolean().optional(),
    tags: z.array(z.string()).optional(),
})

// Input schema for listing dashboards
export const ListDashboardsSchema = z.object({
    limit: z.number().int().positive().optional(),
    offset: z.number().int().nonnegative().optional(),
    search: z.string().optional(),
    pinned: z.boolean().optional(),
})

// Input schema for adding insight to dashboard
export const AddInsightToDashboardSchema = z.object({
    insightId: z.string(),
    dashboardId: z.number().int().positive(),
})

// Type exports
export type PostHogDashboard = z.infer<typeof DashboardSchema>
export type CreateDashboardInput = z.infer<typeof CreateDashboardInputSchema>
export type UpdateDashboardInput = z.infer<typeof UpdateDashboardInputSchema>
export type ListDashboardsData = z.infer<typeof ListDashboardsSchema>
export type AddInsightToDashboardInput = z.infer<typeof AddInsightToDashboardSchema>
export type SimpleDashboard = z.infer<typeof SimpleDashboardSchema>
