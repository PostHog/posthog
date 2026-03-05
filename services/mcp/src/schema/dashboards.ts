import { z } from 'zod'

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
