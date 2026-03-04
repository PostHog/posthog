import { z } from 'zod'

export interface DashboardTile {
    insight: {
        short_id: string
        name: string
        derived_name: string | null
        description: string | null
        query: {
            kind: 'InsightVizNode' | 'DataVisualizationNode'
            source: unknown
        }
        created_at?: string | null
        updated_at?: string | null
        favorited?: boolean | null
        tags?: string[] | null
    }
    order: number
    color?: string | null
    layouts?: Record<string, unknown> | null
    last_refresh?: string | null
    is_cached?: boolean | null
}

export interface PostHogDashboard {
    id: number
    name: string
    description?: string | null
    pinned?: boolean | null
    created_at: string
    created_by?: {
        email: string
    } | null
    is_shared?: boolean | null
    deleted?: boolean | null
    filters?: Record<string, unknown> | null
    variables?: Record<string, unknown> | null
    tags?: string[] | null
    tiles?: Array<DashboardTile | null> | null
}

export interface SimpleDashboard {
    id: number
    name: string
    description?: string | null
    tiles?: Array<DashboardTile | null> | null
}

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

// Input schema for reordering dashboard tiles
export const ReorderDashboardTilesSchema = z.object({
    dashboardId: z.number().int().positive().describe('The ID of the dashboard to reorder tiles on'),
    tileOrder: z
        .array(z.number().int().positive())
        .min(1)
        .describe('Array of tile IDs in the desired order from top to bottom'),
})

// Type exports
export type CreateDashboardInput = z.infer<typeof CreateDashboardInputSchema>
export type UpdateDashboardInput = z.infer<typeof UpdateDashboardInputSchema>
export type ListDashboardsData = z.infer<typeof ListDashboardsSchema>
export type AddInsightToDashboardInput = z.infer<typeof AddInsightToDashboardSchema>
export type ReorderDashboardTilesInput = z.infer<typeof ReorderDashboardTilesSchema>
