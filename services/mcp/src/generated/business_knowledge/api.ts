/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Read-only access to parsed knowledge documents. Exposes hybrid search
 * (``search``) and a drill-down window (``window``) so an agent (PHAI or
 * MCP) can find and explore business knowledge chunks.
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

/**
 * Read-only access to parsed knowledge documents. Exposes hybrid search
 * (``search``) and a drill-down window (``window``) so an agent (PHAI or
 * MCP) can find and explore business knowledge chunks.
 */
export const BusinessKnowledgeDocumentsSearchListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const BusinessKnowledgeDocumentsSearchListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Maximum number of ranked chunks to return. Defaults to 10, capped at 20.'),
    query: zod
        .string()
        .describe(
            'Natural-language search query. Runs hybrid (semantic + full-text) retrieval over all SAFE, READY knowledge chunks in this project.'
        ),
    rerank: zod
        .boolean()
        .optional()
        .describe(
            'When true, rerank search results with a listwise LLM pass for better relevance. Defaults to false (RRF order only). Falls back to RRF order on rerank failure.'
        ),
})

export const BusinessKnowledgeSourcesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const BusinessKnowledgeSourcesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const BusinessKnowledgeSourcesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const businessKnowledgeSourcesCreateBodyNameMax = 255

export const BusinessKnowledgeSourcesCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(businessKnowledgeSourcesCreateBodyNameMax)
        .describe('Short human label for the source. Shown in the settings list and in agent citations.'),
    text: zod
        .string()
        .describe(
            'Raw text to index. Capped at 1 MB; larger payloads should be split into multiple sources or wait for URL/file support in Stage 2/3.'
        ),
})

export const BusinessKnowledgeSourcesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this knowledge source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
