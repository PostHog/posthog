/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `feedback` - Feedback
 * `missing_capability` - Missing capability
 */
export type MCPAnalyticsSubmissionKindEnumApi =
    (typeof MCPAnalyticsSubmissionKindEnumApi)[keyof typeof MCPAnalyticsSubmissionKindEnumApi]

export const MCPAnalyticsSubmissionKindEnumApi = {
    Feedback: 'feedback',
    MissingCapability: 'missing_capability',
} as const

export interface MCPAnalyticsSubmissionApi {
    /** Unique identifier for this submission. */
    readonly id: string
    /** Whether this submission is general feedback or a missing capability report.

  * `feedback` - Feedback
  * `missing_capability` - Missing capability */
    readonly kind: MCPAnalyticsSubmissionKindEnumApi
    /** The user's goal in plain language. */
    goal: string
    /** The core feedback or missing capability request. */
    summary: string
    /** Feedback category when present. Empty for submissions that do not use categories. */
    readonly category: string
    /**
     * Whether the missing capability blocked progress. Null when not provided.
     * @nullable
     */
    readonly blocked: boolean | null
    /** The tool the user tried before submitting this feedback, if known. */
    readonly attempted_tool: string
    /** MCP client name captured alongside the submission when available. */
    readonly mcp_client_name: string
    /** MCP client version captured alongside the submission when available. */
    readonly mcp_client_version: string
    /** MCP protocol version captured alongside the submission when available. */
    readonly mcp_protocol_version: string
    /** MCP transport captured alongside the submission when available. */
    readonly mcp_transport: string
    /** MCP session identifier captured alongside the submission when available. */
    readonly mcp_session_id: string
    /** MCP trace identifier captured alongside the submission when available. */
    readonly mcp_trace_id: string
    /** When this submission was created. */
    readonly created_at: string
    /** When this submission was last updated. */
    readonly updated_at: string
}

export interface PaginatedMCPAnalyticsSubmissionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MCPAnalyticsSubmissionApi[]
}

/**
 * * `results` - Results
 * `usability` - Usability
 * `bug` - Bug
 * `docs` - Docs
 * `other` - Other
 */
export type MCPFeedbackCreateCategoryEnumApi =
    (typeof MCPFeedbackCreateCategoryEnumApi)[keyof typeof MCPFeedbackCreateCategoryEnumApi]

export const MCPFeedbackCreateCategoryEnumApi = {
    Results: 'results',
    Usability: 'usability',
    Bug: 'bug',
    Docs: 'docs',
    Other: 'other',
} as const

export interface MCPFeedbackCreateApi {
    /**
     * The tool the user tried before leaving feedback, if known.
     * @maxLength 200
     */
    attempted_tool?: string
    /**
     * MCP client name, for example Claude Desktop or Cursor.
     * @maxLength 200
     */
    mcp_client_name?: string
    /**
     * Version string for the MCP client when available.
     * @maxLength 100
     */
    mcp_client_version?: string
    /**
     * MCP protocol version negotiated for the session when available.
     * @maxLength 50
     */
    mcp_protocol_version?: string
    /**
     * Transport used for the MCP session, for example streamable_http or sse.
     * @maxLength 50
     */
    mcp_transport?: string
    /**
     * Stable MCP session identifier when available.
     * @maxLength 200
     */
    mcp_session_id?: string
    /**
     * Trace identifier for the surrounding MCP workflow when available.
     * @maxLength 200
     */
    mcp_trace_id?: string
    /**
     * The user's intended outcome when using MCP.
     * @maxLength 500
     */
    goal: string
    /**
     * Concrete feedback about the MCP experience, tool result, or workflow friction.
     * @maxLength 5000
     */
    feedback: string
    /** High-level category for the feedback.

  * `results` - Results
  * `usability` - Usability
  * `bug` - Bug
  * `docs` - Docs
  * `other` - Other */
    category?: MCPFeedbackCreateCategoryEnumApi
}

export interface MCPMissingCapabilityCreateApi {
    /**
     * The tool the user tried before leaving feedback, if known.
     * @maxLength 200
     */
    attempted_tool?: string
    /**
     * MCP client name, for example Claude Desktop or Cursor.
     * @maxLength 200
     */
    mcp_client_name?: string
    /**
     * Version string for the MCP client when available.
     * @maxLength 100
     */
    mcp_client_version?: string
    /**
     * MCP protocol version negotiated for the session when available.
     * @maxLength 50
     */
    mcp_protocol_version?: string
    /**
     * Transport used for the MCP session, for example streamable_http or sse.
     * @maxLength 50
     */
    mcp_transport?: string
    /**
     * Stable MCP session identifier when available.
     * @maxLength 200
     */
    mcp_session_id?: string
    /**
     * Trace identifier for the surrounding MCP workflow when available.
     * @maxLength 200
     */
    mcp_trace_id?: string
    /**
     * The user's intended outcome when using MCP.
     * @maxLength 500
     */
    goal: string
    /**
     * Capability, tool, or workflow support that is currently missing.
     * @maxLength 5000
     */
    missing_capability: string
    /** Whether the missing capability blocked the user's progress. */
    blocked?: boolean
}

export interface MCPSessionApi {
    /** PostHog $session_id grouping all mcp_tool_call events. */
    readonly session_id: string
    /** Number of mcp_tool_call events in the session. */
    readonly event_count: number
    /** Timestamp of the first mcp_tool_call event in the session. */
    readonly first_seen: string
    /** Timestamp of the most recent mcp_tool_call event in the session. */
    readonly last_seen: string
    /** Number of distinct PostHog distinct_ids that produced events in the session. */
    readonly distinct_id_count: number
    /** Distinct $mcp_tool_name values seen in the session. */
    readonly tools_used: readonly string[]
    /** Most recent $mcp_client_name observed in the session. */
    readonly mcp_client_name: string
    /** Most recent distinct_id observed for the session. Stable identifier the SDK tagged the events with. */
    readonly distinct_id: string
    /** email property of the Person resolved from distinct_id; empty when no Person is mapped. */
    readonly person_email: string
    /** name property of the Person resolved from distinct_id; empty when no Person is mapped. */
    readonly person_name: string
    /** LLM-generated 2-3 sentence summary of the agent's overall goal for the session. Empty until the summary workflow runs. */
    readonly intent: string
}

export interface PaginatedMCPSessionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MCPSessionApi[]
}

export interface MCPToolCallApi {
    /** ClickHouse uuid of the mcp_tool_call event. */
    readonly event_id: string
    /** When the tool call was captured. */
    readonly timestamp: string
    /** Tool that was invoked ($mcp_tool_name). */
    readonly tool_name: string
    /** Agent intent for this tool call ($mcp_intent). Empty when the SDK did not capture context. */
    readonly intent: string
    /** Whether the tool call resulted in an error. */
    readonly is_error: boolean
    /** Error message when is_error is true, otherwise empty. */
    readonly error_message: string
    /**
     * Duration of the tool call in milliseconds when captured.
     * @nullable
     */
    readonly duration_ms: number | null
}

export interface PaginatedMCPToolCallListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MCPToolCallApi[]
}

export type McpAnalyticsFeedbackListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type McpAnalyticsMissingCapabilitiesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type McpAnalyticsSessionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type McpAnalyticsSessionsToolCallsParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
