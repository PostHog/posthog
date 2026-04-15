/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List MCP feedback submissions for the current project, newest first.
 */
export const McpAnalyticsFeedbackListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid().describe('Unique identifier for this submission.'),
            kind: zod
                .enum(['feedback', 'missing_capability'])
                .describe('* `feedback` - Feedback\n* `missing_capability` - Missing capability')
                .describe(
                    'Whether this submission is general feedback or a missing capability report.\n\n* `feedback` - Feedback\n* `missing_capability` - Missing capability'
                ),
            goal: zod.string().describe("The user's goal in plain language."),
            summary: zod.string().describe('The core feedback or missing capability request.'),
            category: zod
                .string()
                .describe('Feedback category when present. Empty for submissions that do not use categories.'),
            blocked: zod
                .boolean()
                .nullable()
                .describe('Whether the missing capability blocked progress. Null when not provided.'),
            attempted_tool: zod.string().describe('The tool the user tried before submitting this feedback, if known.'),
            mcp_client_name: zod.string().describe('MCP client name captured alongside the submission when available.'),
            mcp_client_version: zod
                .string()
                .describe('MCP client version captured alongside the submission when available.'),
            mcp_protocol_version: zod
                .string()
                .describe('MCP protocol version captured alongside the submission when available.'),
            mcp_transport: zod.string().describe('MCP transport captured alongside the submission when available.'),
            mcp_session_id: zod
                .string()
                .describe('MCP session identifier captured alongside the submission when available.'),
            mcp_trace_id: zod
                .string()
                .describe('MCP trace identifier captured alongside the submission when available.'),
            created_at: zod.iso.datetime({}).describe('When this submission was created.'),
            updated_at: zod.iso.datetime({}).describe('When this submission was last updated.'),
        })
    ),
})

/**
 * Create a new MCP feedback submission for the current project.
 */
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
 * List missing capability reports for the current project, newest first.
 */
export const McpAnalyticsMissingCapabilitiesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid().describe('Unique identifier for this submission.'),
            kind: zod
                .enum(['feedback', 'missing_capability'])
                .describe('* `feedback` - Feedback\n* `missing_capability` - Missing capability')
                .describe(
                    'Whether this submission is general feedback or a missing capability report.\n\n* `feedback` - Feedback\n* `missing_capability` - Missing capability'
                ),
            goal: zod.string().describe("The user's goal in plain language."),
            summary: zod.string().describe('The core feedback or missing capability request.'),
            category: zod
                .string()
                .describe('Feedback category when present. Empty for submissions that do not use categories.'),
            blocked: zod
                .boolean()
                .nullable()
                .describe('Whether the missing capability blocked progress. Null when not provided.'),
            attempted_tool: zod.string().describe('The tool the user tried before submitting this feedback, if known.'),
            mcp_client_name: zod.string().describe('MCP client name captured alongside the submission when available.'),
            mcp_client_version: zod
                .string()
                .describe('MCP client version captured alongside the submission when available.'),
            mcp_protocol_version: zod
                .string()
                .describe('MCP protocol version captured alongside the submission when available.'),
            mcp_transport: zod.string().describe('MCP transport captured alongside the submission when available.'),
            mcp_session_id: zod
                .string()
                .describe('MCP session identifier captured alongside the submission when available.'),
            mcp_trace_id: zod
                .string()
                .describe('MCP trace identifier captured alongside the submission when available.'),
            created_at: zod.iso.datetime({}).describe('When this submission was created.'),
            updated_at: zod.iso.datetime({}).describe('When this submission was last updated.'),
        })
    ),
})

/**
 * Create a new missing capability report for the current project.
 */
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
