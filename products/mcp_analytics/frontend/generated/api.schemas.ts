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

export interface MCPIntentClusterSampleIntentApi {
    /** The natural-language intent string captured on the mcp_tool_call. */
    intent: string
    /** How many mcp_tool_call events had this intent in the window. */
    total_calls: number
    /** Fraction (0-1) of those calls that errored. */
    error_rate: number
    /** Fraction (0-1) of those calls where the tool returned an empty response. */
    empty_rate: number
}

export interface MCPIntentClusterApi {
    /** Stable cluster identifier within the clustering run. */
    cluster_id: number
    /** LLM-generated short title for this cluster. */
    title: string
    /** LLM-generated description of what this cluster of intents covers. */
    description: string
    /** LLM-estimated likelihood (0-1) that this cluster represents a missing tool capability. */
    gap_score: number
    /** Number of distinct intents in this cluster. */
    size: number
    /** Aggregated error rate across all mcp_tool_call events for intents in this cluster. */
    aggregate_error_rate: number
    /** Aggregated empty-response rate across all mcp_tool_call events for intents in this cluster. */
    aggregate_empty_rate: number
    /** Average number of distinct MCP tools attempted per intent in this cluster. */
    avg_distinct_tools_attempted: number
    /** A handful of representative intents from the cluster, closest to the centroid first. */
    sample_intents: MCPIntentClusterSampleIntentApi[]
}

export interface MCPLLMStatedGapApi {
    /** The probe phrase whose semantic neighborhood produced this match. */
    probe_phrase: string
    /** The $ai_span reasoning text fragment that matched the probe. */
    matched_text: string
    /** Cosine distance between the probe and the matched text (lower = closer). */
    distance: number
    /** UUID of the $ai_span event for linking back to its trace. */
    document_id: string
    /**
     * Timestamp of the $ai_span event, if available.
     * @nullable
     */
    timestamp: string | null
}

export interface MCPMissingToolsCandidatesApi {
    /** Identifier of the clustering run these results came from. */
    clustering_run_id: string
    /** ISO-8601 start of the window the clusters cover. */
    window_start: string
    /** ISO-8601 end of the window the clusters cover. */
    window_end: string
    /** Intent clusters ranked by gap_score (highest first). */
    intent_clusters: MCPIntentClusterApi[]
    /** LLM-stated gaps from $ai_span reasoning text, ranked by cosine distance (closest first). */
    llm_stated_gaps: MCPLLMStatedGapApi[]
}

export interface PaginatedMCPMissingToolsCandidatesListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MCPMissingToolsCandidatesApi[]
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

export type McpAnalyticsMissingToolsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
