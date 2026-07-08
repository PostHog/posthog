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
 * * `missing_capability` - Missing capability
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
     *
     * * `feedback` - Feedback
     * * `missing_capability` - Missing capability */
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
 * * `usability` - Usability
 * * `bug` - Bug
 * * `docs` - Docs
 * * `other` - Other
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
     *
     * * `results` - Results
     * * `usability` - Usability
     * * `bug` - Bug
     * * `docs` - Docs
     * * `other` - Other */
    category?: MCPFeedbackCreateCategoryEnumApi
}

/**
 * * `idle` - Idle
 * * `computing` - Computing
 * * `error` - Error
 */
export type MCPIntentClusterSnapshotStatusEnumApi =
    (typeof MCPIntentClusterSnapshotStatusEnumApi)[keyof typeof MCPIntentClusterSnapshotStatusEnumApi]

export const MCPIntentClusterSnapshotStatusEnumApi = {
    Idle: 'idle',
    Computing: 'computing',
    Error: 'error',
} as const

export interface MCPIntentClusterToolEntryApi {
    /** MCP tool name that received calls for this cluster. */
    readonly tool: string
    /** Number of tool calls routed to this tool across the cluster. */
    readonly count: number
    /** Percentage of the cluster's calls that went to this tool, 0–100. */
    readonly pct: number
    /** Number of error responses observed for this tool within the cluster. */
    readonly errors: number
    /** Error rate for this tool within the cluster, 0–100. */
    readonly error_rate_pct: number
}

/**
 * * `completed` - Completed
 * * `error` - Error
 */
export type OutcomeEnumApi = (typeof OutcomeEnumApi)[keyof typeof OutcomeEnumApi]

export const OutcomeEnumApi = {
    Completed: 'completed',
    Error: 'error',
} as const

export interface MCPIntentClusterJourneyPathApi {
    /** Ordered tool names called during the path. Length is fixed; null entries indicate the session ended before this step. */
    readonly steps: readonly (string | null)[]
    /** Terminal outcome of the sessions following this path.
     *
     * * `completed` - Completed
     * * `error` - Error */
    readonly outcome: OutcomeEnumApi
    /** Number of sessions in this cluster that followed this exact path. */
    readonly count: number
}

export interface MCPIntentClusterJourneyApi {
    /** Top paths by session count, capped at MAX_JOURNEY_PATHS_PER_CLUSTER. */
    readonly paths: readonly MCPIntentClusterJourneyPathApi[]
    /** Total session count represented across all paths in this cluster. */
    readonly total_sessions: number
    /** Highest-volume non-completed path. Null when every path completed successfully. */
    readonly leak: MCPIntentClusterJourneyPathApi | null
}

export interface MCPIntentClusterApi {
    /** Stable cluster identifier within this snapshot. */
    readonly id: number
    /** Representative intent text for the cluster (the medoid intent closest to the cluster centroid). */
    readonly label: string
    /** Number of distinct intent texts that belong to this cluster. */
    readonly intent_count: number
    /** Number of MCP sessions whose summarised intent belongs to this cluster. */
    readonly session_count: number
    /** Total number of $mcp_tool_call events represented by this cluster. */
    readonly call_count: number
    /** Total number of error responses observed across the cluster. */
    readonly error_count: number
    /** Aggregate error rate across all tool calls in the cluster, 0–100. */
    readonly error_rate_pct: number
    /** Normalised Shannon entropy of the tool distribution. 0 means perfectly consistent routing (one tool dominates); 1 means uniformly spread across all tools called for this intent cluster. */
    readonly routing_entropy: number
    /** Per-tool breakdown of calls and errors within the cluster. */
    readonly tool_distribution: readonly MCPIntentClusterToolEntryApi[]
    /** Up to three representative intent strings from the cluster, ordered by frequency desc. */
    readonly sample_intents: readonly string[]
    /** Top Sankey-shaped paths the agents took within this cluster. Each path is up to four ordered tool calls plus a completed/error outcome. Null when journey data is unavailable. */
    readonly journey: MCPIntentClusterJourneyApi | null
}

export interface MCPIntentClusterSnapshotMetaApi {
    /** Cosine distance threshold used by the clustering algorithm. */
    readonly distance_threshold: number
    /** Embedding model used to vectorise intents. */
    readonly embedding_model: string
    /** Number of distinct intents that fed into the clustering run. */
    readonly n_intents: number
    /** Number of clusters produced by the run. */
    readonly n_clusters: number
}

export interface MCPIntentClusterSnapshotApi {
    /** Whether a snapshot is current (idle), being recomputed (computing), or failed (error).
     *
     * * `idle` - Idle
     * * `computing` - Computing
     * * `error` - Error */
    readonly status: MCPIntentClusterSnapshotStatusEnumApi
    /** Error message from the most recent failed run, otherwise empty. */
    readonly error_message: string
    /**
     * When the latest snapshot finished computing.
     * @nullable
     */
    readonly last_computed_at: string | null
    /** Email of the user who triggered the latest recompute, empty for system-triggered runs. */
    readonly last_computed_by_email: string
    /** All clusters in the snapshot. */
    readonly clusters: readonly MCPIntentClusterApi[]
    /** Settings used to produce the snapshot. Null when no snapshot has been computed yet. */
    readonly computed_with: MCPIntentClusterSnapshotMetaApi | null
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
    /** $mcp_session_id grouping all $mcp_tool_call events in the session. */
    readonly session_id: string
    /** Total number of $mcp_tool_call events in the session. */
    readonly tool_calls: number
    /** Timestamp of the first $mcp_tool_call event in the session. */
    readonly session_start: string
    /** Timestamp of the most recent $mcp_tool_call event in the session. */
    readonly session_end: string
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
    /** LLM-generated summary (at most two sentences) of the agent's overall goal for the session. Empty until generated on demand via the generate_intent endpoint. */
    readonly intent: string
}

export interface PaginatedMCPSessionListApi {
    results: MCPSessionApi[]
    /** Whether more results exist beyond this page; the client fetches the next page with a larger offset. */
    has_next: boolean
}

export interface MCPSessionIntentApi {
    /** $mcp_session_id the intent summary was generated for. */
    readonly session_id: string
    /** LLM-generated summary (at most two sentences) of the agent's overall goal for the session. */
    readonly intent: string
}

export interface MCPToolCallApi {
    /** ClickHouse uuid of the $mcp_tool_call event. */
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
    results: MCPToolCallApi[]
    /** Whether more results exist beyond this page; the client fetches the next page with a larger offset. */
    has_next: boolean
}

export interface MCPIntentThemeApi {
    /** Short sentence-case name for this group of intents. */
    readonly name: string
    /** One concrete sentence describing what agents in this theme are doing. */
    readonly description: string
    /** How many of the analysed intents belong to this theme. */
    readonly intent_count: number
    /** One of the recorded intents, verbatim, representative of the theme. */
    readonly example_intent: string
    /** MCP tool names that appear alongside this theme's intents. */
    readonly tools: readonly string[]
}

export interface MCPIntentDigestApi {
    /**
     * LLM-generated one-sentence summary of what agents are trying to do with this MCP server, derived from the most recent recorded $mcp_intents across all sessions. Null when the project has no recorded intents yet.
     * @nullable
     */
    readonly digest: string | null
    /** How many recorded intents (the most recent, capped at 100) the digest was derived from. */
    readonly intent_count: number
    /** 2-5 semantic groupings of the analysed intents, largest first. Empty when digest is null. */
    readonly themes: readonly MCPIntentThemeApi[]
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
     * Start of the window to aggregate sessions over. PostHog date string — relative (e.g. '-7d', '-24h') or an absolute ISO timestamp. Defaults to '-7d'.
     */
    date_from?: string
    /**
     * End of the window. PostHog date string or absolute ISO timestamp. Defaults to now.
     */
    date_to?: string
    /**
     * Maximum number of sessions to return per page. Defaults to 100; values above 500 are rejected.
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Number of sessions to skip before returning results. Combine with limit to page through sessions; the response's has_next flag indicates whether more remain.
     * @minimum 0
     */
    offset?: number
    /**
     * Sort column. Allowed: session_id, session_start, session_end, duration_seconds, tool_call_count, mcp_client_name, distinct_id. Prefix with '-' for descending. Defaults to '-session_start' (newest sessions first).
     */
    order_by?: string
    /**
     * Case-insensitive substring filter matched against session_id, distinct_id, mcp_client_name, and tools_used.
     */
    search?: string
}

export type McpAnalyticsSessionsGenerateIntentParams = {
    /**
     * Absolute ISO timestamp lower bound for the intent scan — pass the session's start so older sessions resolve. Defaults to a 7-day lookback when omitted.
     */
    date_from?: string
}

export type McpAnalyticsSessionsToolCallsParams = {
    /**
     * Absolute ISO timestamp lower bound for the event scan — pass the session's start so older sessions resolve. Defaults to a 7-day lookback when omitted or unparseable.
     */
    date_from?: string
    /**
     * Maximum tool calls to return per page (1–500). Defaults to 500 — the whole page — so a session's calls come back in one request; pass a smaller value for a lighter response. Values above the cap are rejected.
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Number of tool calls to skip before returning results. Combine with limit to page through a session's calls; the response's has_next flag indicates whether more remain.
     * @minimum 0
     */
    offset?: number
}
