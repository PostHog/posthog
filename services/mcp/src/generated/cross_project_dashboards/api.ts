/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Dashboards the organization owns, holding insights from one or more projects.
 */
export const CrossProjectDashboardsListParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const CrossProjectDashboardsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Tiles on one cross-project dashboard, edited one at a time.
 *
 * Writes are per tile rather than a whole-set replace, so two people editing the same
 * dashboard cannot overwrite each other's tiles.
 */
export const CrossProjectDashboardsTilesListParams = () => zod.object({
    dashboard_id: zod.string(),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const CrossProjectDashboardsTilesListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Dashboards the organization owns, holding insights from one or more projects.
 */
export const CrossProjectDashboardsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this cross project dashboard.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})
