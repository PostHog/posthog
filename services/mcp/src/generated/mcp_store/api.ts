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
 * Add the primary key as a final ordering term to each queryset that the viewset pages.
 *
 * TeamAndOrgViewSetMixin inherits this. A viewset without that mixin inherits it directly.
 */
export const McpServerInstallationsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const McpServerInstallationsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Add the primary key as a final ordering term to each queryset that the viewset pages.
 *
 * TeamAndOrgViewSetMixin inherits this. A viewset without that mixin inherits it directly.
 */
export const McpServerInstallationsToolsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this mcp server installation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
