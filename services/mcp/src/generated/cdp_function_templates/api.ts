/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const HogFunctionTemplatesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFunctionTemplatesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    template_id: zod
        .string()
        .optional()
        .describe(
            'Filter to a specific template by its template_id. Deprecated templates are excluded from list results; use the retrieve endpoint to look up a template by ID regardless of status.'
        ),
    type: zod
        .string()
        .optional()
        .describe(
            'Filter by template type (e.g. destination, email, sms_provider, broadcast). Defaults to destination if neither type nor types is provided.'
        ),
    types: zod
        .string()
        .optional()
        .describe('Comma-separated list of template types to include (e.g. destination,email,sms_provider).'),
})

export const HogFunctionTemplatesRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    template_id: zod.string(),
})
