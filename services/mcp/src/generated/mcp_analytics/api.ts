/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 7 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create a new MCP feedback submission for the current project.
 */
export const McpAnalyticsFeedbackCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const mcpAnalyticsFeedbackCreateBodyAttemptedToolDefault = ``
export const mcpAnalyticsFeedbackCreateBodyAttemptedToolMax = 200

export const mcpAnalyticsFeedbackCreateBodyMcpClientNameDefault = ``
export const mcpAnalyticsFeedbackCreateBodyMcpClientNameMax = 200

export const mcpAnalyticsFeedbackCreateBodyMcpClientVersionDefault = ``
export const mcpAnalyticsFeedbackCreateBodyMcpClientVersionMax = 100

export const mcpAnalyticsFeedbackCreateBodyMcpProtocolVersionDefault = ``
export const mcpAnalyticsFeedbackCreateBodyMcpProtocolVersionMax = 50

export const mcpAnalyticsFeedbackCreateBodyMcpTransportDefault = ``
export const mcpAnalyticsFeedbackCreateBodyMcpTransportMax = 50

export const mcpAnalyticsFeedbackCreateBodyMcpSessionIdDefault = ``
export const mcpAnalyticsFeedbackCreateBodyMcpSessionIdMax = 200

export const mcpAnalyticsFeedbackCreateBodyMcpTraceIdDefault = ``
export const mcpAnalyticsFeedbackCreateBodyMcpTraceIdMax = 200

export const mcpAnalyticsFeedbackCreateBodyGoalMax = 500

export const mcpAnalyticsFeedbackCreateBodyFeedbackMax = 5000

export const mcpAnalyticsFeedbackCreateBodyCategoryDefault = `other`

export const McpAnalyticsFeedbackCreateBody = /* @__PURE__ */ zod.object({
    attempted_tool: zod
        .string()
        .max(mcpAnalyticsFeedbackCreateBodyAttemptedToolMax)
        .default(mcpAnalyticsFeedbackCreateBodyAttemptedToolDefault)
        .describe('The tool the user tried before leaving feedback, if known.'),
    mcp_client_name: zod
        .string()
        .max(mcpAnalyticsFeedbackCreateBodyMcpClientNameMax)
        .default(mcpAnalyticsFeedbackCreateBodyMcpClientNameDefault)
        .describe('MCP client name, for example Claude Desktop or Cursor.'),
    mcp_client_version: zod
        .string()
        .max(mcpAnalyticsFeedbackCreateBodyMcpClientVersionMax)
        .default(mcpAnalyticsFeedbackCreateBodyMcpClientVersionDefault)
        .describe('Version string for the MCP client when available.'),
    mcp_protocol_version: zod
        .string()
        .max(mcpAnalyticsFeedbackCreateBodyMcpProtocolVersionMax)
        .default(mcpAnalyticsFeedbackCreateBodyMcpProtocolVersionDefault)
        .describe('MCP protocol version negotiated for the session when available.'),
    mcp_transport: zod
        .string()
        .max(mcpAnalyticsFeedbackCreateBodyMcpTransportMax)
        .default(mcpAnalyticsFeedbackCreateBodyMcpTransportDefault)
        .describe('Transport used for the MCP session, for example streamable_http or sse.'),
    mcp_session_id: zod
        .string()
        .max(mcpAnalyticsFeedbackCreateBodyMcpSessionIdMax)
        .default(mcpAnalyticsFeedbackCreateBodyMcpSessionIdDefault)
        .describe('Stable MCP session identifier when available.'),
    mcp_trace_id: zod
        .string()
        .max(mcpAnalyticsFeedbackCreateBodyMcpTraceIdMax)
        .default(mcpAnalyticsFeedbackCreateBodyMcpTraceIdDefault)
        .describe('Trace identifier for the surrounding MCP workflow when available.'),
    goal: zod
        .string()
        .max(mcpAnalyticsFeedbackCreateBodyGoalMax)
        .describe("The user's intended outcome when using MCP."),
    feedback: zod
        .string()
        .max(mcpAnalyticsFeedbackCreateBodyFeedbackMax)
        .describe('Concrete feedback about the MCP experience, tool result, or workflow friction.'),
    category: zod
        .enum(['results', 'usability', 'bug', 'docs', 'other'])
        .describe('* `results` - Results\n* `usability` - Usability\n* `bug` - Bug\n* `docs` - Docs\n* `other` - Other')
        .default(mcpAnalyticsFeedbackCreateBodyCategoryDefault)
        .describe(
            'High-level category for the feedback.\n\n* `results` - Results\n* `usability` - Usability\n* `bug` - Bug\n* `docs` - Docs\n* `other` - Other'
        ),
})

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
 * Create a new missing capability report for the current project.
 */
export const McpAnalyticsMissingCapabilitiesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const mcpAnalyticsMissingCapabilitiesCreateBodyAttemptedToolDefault = ``
export const mcpAnalyticsMissingCapabilitiesCreateBodyAttemptedToolMax = 200

export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpClientNameDefault = ``
export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpClientNameMax = 200

export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpClientVersionDefault = ``
export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpClientVersionMax = 100

export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpProtocolVersionDefault = ``
export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpProtocolVersionMax = 50

export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpTransportDefault = ``
export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpTransportMax = 50

export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpSessionIdDefault = ``
export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpSessionIdMax = 200

export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpTraceIdDefault = ``
export const mcpAnalyticsMissingCapabilitiesCreateBodyMcpTraceIdMax = 200

export const mcpAnalyticsMissingCapabilitiesCreateBodyGoalMax = 500

export const mcpAnalyticsMissingCapabilitiesCreateBodyMissingCapabilityMax = 5000

export const mcpAnalyticsMissingCapabilitiesCreateBodyBlockedDefault = true

export const McpAnalyticsMissingCapabilitiesCreateBody = /* @__PURE__ */ zod.object({
    attempted_tool: zod
        .string()
        .max(mcpAnalyticsMissingCapabilitiesCreateBodyAttemptedToolMax)
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyAttemptedToolDefault)
        .describe('The tool the user tried before leaving feedback, if known.'),
    mcp_client_name: zod
        .string()
        .max(mcpAnalyticsMissingCapabilitiesCreateBodyMcpClientNameMax)
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyMcpClientNameDefault)
        .describe('MCP client name, for example Claude Desktop or Cursor.'),
    mcp_client_version: zod
        .string()
        .max(mcpAnalyticsMissingCapabilitiesCreateBodyMcpClientVersionMax)
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyMcpClientVersionDefault)
        .describe('Version string for the MCP client when available.'),
    mcp_protocol_version: zod
        .string()
        .max(mcpAnalyticsMissingCapabilitiesCreateBodyMcpProtocolVersionMax)
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyMcpProtocolVersionDefault)
        .describe('MCP protocol version negotiated for the session when available.'),
    mcp_transport: zod
        .string()
        .max(mcpAnalyticsMissingCapabilitiesCreateBodyMcpTransportMax)
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyMcpTransportDefault)
        .describe('Transport used for the MCP session, for example streamable_http or sse.'),
    mcp_session_id: zod
        .string()
        .max(mcpAnalyticsMissingCapabilitiesCreateBodyMcpSessionIdMax)
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyMcpSessionIdDefault)
        .describe('Stable MCP session identifier when available.'),
    mcp_trace_id: zod
        .string()
        .max(mcpAnalyticsMissingCapabilitiesCreateBodyMcpTraceIdMax)
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyMcpTraceIdDefault)
        .describe('Trace identifier for the surrounding MCP workflow when available.'),
    goal: zod
        .string()
        .max(mcpAnalyticsMissingCapabilitiesCreateBodyGoalMax)
        .describe("The user's intended outcome when using MCP."),
    missing_capability: zod
        .string()
        .max(mcpAnalyticsMissingCapabilitiesCreateBodyMissingCapabilityMax)
        .describe('Capability, tool, or workflow support that is currently missing.'),
    blocked: zod
        .boolean()
        .default(mcpAnalyticsMissingCapabilitiesCreateBodyBlockedDefault)
        .describe("Whether the missing capability blocked the user's progress."),
})

/**
 * List MCP sessions for the current project, derived by grouping $mcp_tool_call events by $mcp_session_id. Ordered by newest session start first by default.
 */
export const McpAnalyticsSessionsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const mcpAnalyticsSessionsListQueryLimitDefault = 100
export const mcpAnalyticsSessionsListQueryLimitMax = 500

export const mcpAnalyticsSessionsListQueryOffsetDefault = 0
export const mcpAnalyticsSessionsListQueryOffsetMin = 0

export const mcpAnalyticsSessionsListQueryOrderByDefault = ``
export const mcpAnalyticsSessionsListQuerySearchDefault = ``

export const McpAnalyticsSessionsListQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod
        .string()
        .optional()
        .describe(
            "Start of the window to aggregate sessions over. PostHog date string — relative (e.g. '-7d', '-24h') or an absolute ISO timestamp. Defaults to '-7d'."
        ),
    date_to: zod
        .string()
        .optional()
        .describe('End of the window. PostHog date string or absolute ISO timestamp. Defaults to now.'),
    limit: zod
        .number()
        .min(1)
        .max(mcpAnalyticsSessionsListQueryLimitMax)
        .default(mcpAnalyticsSessionsListQueryLimitDefault)
        .describe('Maximum number of sessions to return per page. Defaults to 100; values above 500 are rejected.'),
    offset: zod
        .number()
        .min(mcpAnalyticsSessionsListQueryOffsetMin)
        .default(mcpAnalyticsSessionsListQueryOffsetDefault)
        .describe(
            "Number of sessions to skip before returning results. Combine with limit to page through sessions; the response's has_next flag indicates whether more remain."
        ),
    order_by: zod
        .string()
        .default(mcpAnalyticsSessionsListQueryOrderByDefault)
        .describe(
            "Sort column. Allowed: session_id, session_start, session_end, duration_seconds, tool_call_count, mcp_client_name, distinct_id. Prefix with '-' for descending. Defaults to '-session_start' (newest sessions first)."
        ),
    search: zod
        .string()
        .default(mcpAnalyticsSessionsListQuerySearchDefault)
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

export const McpAnalyticsSessionsGenerateIntentQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe(
            "Absolute ISO timestamp lower bound for the intent scan — pass the session's start so older sessions resolve. Defaults to a 7-day lookback when omitted."
        ),
})

/**
 * List a page of the $mcp_tool_call events that belong to a given $session_id, in chronological order.
 */
export const McpAnalyticsSessionsToolCallsParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this mcp analytics submission.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const mcpAnalyticsSessionsToolCallsQueryLimitDefault = 500
export const mcpAnalyticsSessionsToolCallsQueryLimitMax = 500

export const mcpAnalyticsSessionsToolCallsQueryOffsetDefault = 0
export const mcpAnalyticsSessionsToolCallsQueryOffsetMin = 0

export const McpAnalyticsSessionsToolCallsQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe(
            "Absolute ISO timestamp lower bound for the event scan — pass the session's start so older sessions resolve. Defaults to a 7-day lookback when omitted or unparseable."
        ),
    limit: zod
        .number()
        .min(1)
        .max(mcpAnalyticsSessionsToolCallsQueryLimitMax)
        .default(mcpAnalyticsSessionsToolCallsQueryLimitDefault)
        .describe(
            "Maximum tool calls to return per page (1–500). Defaults to 500 — the whole page — so a session's calls come back in one request; pass a smaller value for a lighter response. Values above the cap are rejected."
        ),
    offset: zod
        .number()
        .min(mcpAnalyticsSessionsToolCallsQueryOffsetMin)
        .default(mcpAnalyticsSessionsToolCallsQueryOffsetDefault)
        .describe(
            "Number of tool calls to skip before returning results. Combine with limit to page through a session's calls; the response's has_next flag indicates whether more remain."
        ),
})
