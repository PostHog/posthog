/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create, read, update, and resolve toolbar annotations — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const ToolbarAnnotationsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ToolbarAnnotationsListQueryParams = /* @__PURE__ */ zod.object({
    annotation_status: zod
        .enum(['acknowledged', 'dismissed', 'pending', 'resolved'])
        .optional()
        .describe('Filter to annotations in this lifecycle state (e.g. `pending` for unaddressed feedback).'),
    host: zod.string().optional().describe('Filter to annotations made on this hostname (e.g. `app.example.com`).'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Create, read, update, and resolve toolbar annotations — UI feedback a user
 * points at on their own site, surfaced to coding agents over MCP.
 */
export const ToolbarAnnotationsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this toolbar annotation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
