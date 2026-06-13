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
 * Return the most recent intent cluster snapshot for the current project. Returns an empty IDLE snapshot when no clustering run has happened yet.
 */
export const McpAnalyticsIntentClustersRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Trigger an asynchronous recompute of the intent cluster snapshot. The task runs in the background; poll the GET endpoint for progress (status transitions to 'idle' or 'error').
 */
export const McpAnalyticsIntentClustersRecomputeParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * List MCP sessions for the current project, derived by grouping mcp_tool_call events by $mcp_session_id. Ordered by newest session start first by default.
 */
export const McpAnalyticsSessionsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const McpAnalyticsSessionsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod
        .string()
        .optional()
        .describe(
            "Sort column. Allowed: session_id, session_start, session_end, duration_seconds, tool_call_count, mcp_client_name, distinct_id. Prefix with '-' for descending. Defaults to '-session_start' (newest sessions first)."
        ),
    search: zod
        .string()
        .optional()
        .describe(
            'Case-insensitive substring filter matched against session_id, distinct_id, mcp_client_name, and tools_used.'
        ),
})

/**
 * Generate (or return the cached) LLM summary of the agent's goal for a session, derived from its recorded $mcp_intents. The first call summarises and persists the result; subsequent calls return the stored summary.
 */
export const McpAnalyticsSessionsGenerateIntentParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this mcp analytics submission.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * List all mcp_tool_call events that belong to a given $session_id, in chronological order.
 */
export const McpAnalyticsSessionsToolCallsParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this mcp analytics submission.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const McpAnalyticsSessionsToolCallsQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})
