/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 1 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Read-only access to parsed knowledge documents. Currently exposes only the
 * `window` drill-down so an agent (PHAI or MCP) can pull a wider context span
 * around a chunk it found via search.
 */
export const BusinessKnowledgeDocumentsWindowListParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this knowledge document.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const BusinessKnowledgeDocumentsWindowListQueryParams = /* @__PURE__ */ zod.object({
    around_ordinal: zod.number().describe('Zero-based chunk ordinal to center the window on (from a search result).'),
    radius: zod
        .number()
        .optional()
        .describe('Number of chunks before and after the center to include. Defaults to 5, clamped to [0, 15].'),
})
