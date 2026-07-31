/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const MCPAnalyticsSubmissionKindEnumApi = zod
    .enum(['feedback', 'missing_capability'])
    .describe('\* `feedback` - Feedback\n\* `missing_capability` - Missing capability')

export type MCPAnalyticsSubmissionKindEnumApi = zod.input<typeof MCPAnalyticsSubmissionKindEnumApi>
export type MCPAnalyticsSubmissionKindEnumApiOutput = zod.output<typeof MCPAnalyticsSubmissionKindEnumApi>

export const MCPAnalyticsSubmissionApi = zod.object({
    id: zod.uuid().describe('Unique identifier for this submission.'),
    kind: MCPAnalyticsSubmissionKindEnumApi.describe(
        'Whether this submission is general feedback or a missing capability report.\n\n\* `feedback` - Feedback\n\* `missing_capability` - Missing capability'
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
    mcp_client_version: zod.string().describe('MCP client version captured alongside the submission when available.'),
    mcp_protocol_version: zod
        .string()
        .describe('MCP protocol version captured alongside the submission when available.'),
    mcp_transport: zod.string().describe('MCP transport captured alongside the submission when available.'),
    mcp_session_id: zod.string().describe('MCP session identifier captured alongside the submission when available.'),
    mcp_trace_id: zod.string().describe('MCP trace identifier captured alongside the submission when available.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When this submission was created.'),
    updated_at: zod.iso.datetime({ offset: true }).describe('When this submission was last updated.'),
})

export type MCPAnalyticsSubmissionApi = zod.input<typeof MCPAnalyticsSubmissionApi>
export type MCPAnalyticsSubmissionApiOutput = zod.output<typeof MCPAnalyticsSubmissionApi>

export const PaginatedMCPAnalyticsSubmissionListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(MCPAnalyticsSubmissionApi),
})

export type PaginatedMCPAnalyticsSubmissionListApi = zod.input<typeof PaginatedMCPAnalyticsSubmissionListApi>
export type PaginatedMCPAnalyticsSubmissionListApiOutput = zod.output<typeof PaginatedMCPAnalyticsSubmissionListApi>

export const MCPFeedbackCreateCategoryEnumApi = zod
    .enum(['results', 'usability', 'bug', 'docs', 'other'])
    .describe(
        '\* `results` - Results\n\* `usability` - Usability\n\* `bug` - Bug\n\* `docs` - Docs\n\* `other` - Other'
    )

export type MCPFeedbackCreateCategoryEnumApi = zod.input<typeof MCPFeedbackCreateCategoryEnumApi>
export type MCPFeedbackCreateCategoryEnumApiOutput = zod.output<typeof MCPFeedbackCreateCategoryEnumApi>

export const mCPFeedbackCreateApiAttemptedToolDefault = ``
export const mCPFeedbackCreateApiAttemptedToolMax = 200

export const mCPFeedbackCreateApiMcpClientNameDefault = ``
export const mCPFeedbackCreateApiMcpClientNameMax = 200

export const mCPFeedbackCreateApiMcpClientVersionDefault = ``
export const mCPFeedbackCreateApiMcpClientVersionMax = 100

export const mCPFeedbackCreateApiMcpProtocolVersionDefault = ``
export const mCPFeedbackCreateApiMcpProtocolVersionMax = 50

export const mCPFeedbackCreateApiMcpTransportDefault = ``
export const mCPFeedbackCreateApiMcpTransportMax = 50

export const mCPFeedbackCreateApiMcpSessionIdDefault = ``
export const mCPFeedbackCreateApiMcpSessionIdMax = 200

export const mCPFeedbackCreateApiMcpTraceIdDefault = ``
export const mCPFeedbackCreateApiMcpTraceIdMax = 200

export const mCPFeedbackCreateApiGoalMax = 500

export const mCPFeedbackCreateApiFeedbackMax = 5000

export const mCPFeedbackCreateApiCategoryDefault = `other`

export const MCPFeedbackCreateApi = zod.object({
    attempted_tool: zod
        .string()
        .max(mCPFeedbackCreateApiAttemptedToolMax)
        .default(mCPFeedbackCreateApiAttemptedToolDefault)
        .describe('The tool the user tried before leaving feedback, if known.'),
    mcp_client_name: zod
        .string()
        .max(mCPFeedbackCreateApiMcpClientNameMax)
        .default(mCPFeedbackCreateApiMcpClientNameDefault)
        .describe('MCP client name, for example Claude Desktop or Cursor.'),
    mcp_client_version: zod
        .string()
        .max(mCPFeedbackCreateApiMcpClientVersionMax)
        .default(mCPFeedbackCreateApiMcpClientVersionDefault)
        .describe('Version string for the MCP client when available.'),
    mcp_protocol_version: zod
        .string()
        .max(mCPFeedbackCreateApiMcpProtocolVersionMax)
        .default(mCPFeedbackCreateApiMcpProtocolVersionDefault)
        .describe('MCP protocol version negotiated for the session when available.'),
    mcp_transport: zod
        .string()
        .max(mCPFeedbackCreateApiMcpTransportMax)
        .default(mCPFeedbackCreateApiMcpTransportDefault)
        .describe('Transport used for the MCP session, for example streamable_http or sse.'),
    mcp_session_id: zod
        .string()
        .max(mCPFeedbackCreateApiMcpSessionIdMax)
        .default(mCPFeedbackCreateApiMcpSessionIdDefault)
        .describe('Stable MCP session identifier when available.'),
    mcp_trace_id: zod
        .string()
        .max(mCPFeedbackCreateApiMcpTraceIdMax)
        .default(mCPFeedbackCreateApiMcpTraceIdDefault)
        .describe('Trace identifier for the surrounding MCP workflow when available.'),
    goal: zod.string().max(mCPFeedbackCreateApiGoalMax).describe("The user's intended outcome when using MCP."),
    feedback: zod
        .string()
        .max(mCPFeedbackCreateApiFeedbackMax)
        .describe('Concrete feedback about the MCP experience, tool result, or workflow friction.'),
    category: MCPFeedbackCreateCategoryEnumApi.default(mCPFeedbackCreateApiCategoryDefault).describe(
        'High-level category for the feedback.\n\n\* `results` - Results\n\* `usability` - Usability\n\* `bug` - Bug\n\* `docs` - Docs\n\* `other` - Other'
    ),
})

export type MCPFeedbackCreateApi = zod.input<typeof MCPFeedbackCreateApi>
export type MCPFeedbackCreateApiOutput = zod.output<typeof MCPFeedbackCreateApi>

export const MCPIntentClusterSnapshotStatusEnumApi = zod
    .enum(['idle', 'computing', 'error'])
    .describe('\* `idle` - Idle\n\* `computing` - Computing\n\* `error` - Error')

export type MCPIntentClusterSnapshotStatusEnumApi = zod.input<typeof MCPIntentClusterSnapshotStatusEnumApi>
export type MCPIntentClusterSnapshotStatusEnumApiOutput = zod.output<typeof MCPIntentClusterSnapshotStatusEnumApi>

export const MCPIntentClusterToolEntryApi = zod.object({
    tool: zod.string().describe('MCP tool name that received calls for this cluster.'),
    count: zod.number().describe('Number of tool calls routed to this tool across the cluster.'),
    pct: zod.number().describe("Percentage of the cluster's calls that went to this tool, 0–100."),
    errors: zod.number().describe('Number of error responses observed for this tool within the cluster.'),
    error_rate_pct: zod.number().describe('Error rate for this tool within the cluster, 0–100.'),
})

export type MCPIntentClusterToolEntryApi = zod.input<typeof MCPIntentClusterToolEntryApi>
export type MCPIntentClusterToolEntryApiOutput = zod.output<typeof MCPIntentClusterToolEntryApi>

export const OutcomeEnumApi = zod
    .enum(['completed', 'error'])
    .describe('\* `completed` - Completed\n\* `error` - Error')

export type OutcomeEnumApi = zod.input<typeof OutcomeEnumApi>
export type OutcomeEnumApiOutput = zod.output<typeof OutcomeEnumApi>

export const MCPIntentClusterJourneyPathApi = zod.object({
    steps: zod
        .array(zod.string().nullable())
        .describe(
            'Ordered tool names called during the path. Length is fixed; null entries indicate the session ended before this step.'
        ),
    outcome: OutcomeEnumApi.describe(
        'Terminal outcome of the sessions following this path.\n\n\* `completed` - Completed\n\* `error` - Error'
    ),
    count: zod.number().describe('Number of sessions in this cluster that followed this exact path.'),
})

export type MCPIntentClusterJourneyPathApi = zod.input<typeof MCPIntentClusterJourneyPathApi>
export type MCPIntentClusterJourneyPathApiOutput = zod.output<typeof MCPIntentClusterJourneyPathApi>

export const MCPIntentClusterJourneyApi = zod.object({
    paths: zod
        .array(MCPIntentClusterJourneyPathApi)
        .describe('Top paths by session count, capped at MAX_JOURNEY_PATHS_PER_CLUSTER.'),
    total_sessions: zod.number().describe('Total session count represented across all paths in this cluster.'),
    leak: zod
        .union([MCPIntentClusterJourneyPathApi, zod.null()])
        .describe('Highest-volume non-completed path. Null when every path completed successfully.'),
})

export type MCPIntentClusterJourneyApi = zod.input<typeof MCPIntentClusterJourneyApi>
export type MCPIntentClusterJourneyApiOutput = zod.output<typeof MCPIntentClusterJourneyApi>

export const MCPIntentClusterApi = zod.object({
    id: zod.number().describe('Stable cluster identifier within this snapshot.'),
    label: zod
        .string()
        .describe('Representative intent text for the cluster (the medoid intent closest to the cluster centroid).'),
    intent_count: zod.number().describe('Number of distinct intent texts that belong to this cluster.'),
    session_count: zod.number().describe('Number of MCP sessions whose summarised intent belongs to this cluster.'),
    call_count: zod.number().describe('Total number of $mcp_tool_call events represented by this cluster.'),
    error_count: zod.number().describe('Total number of error responses observed across the cluster.'),
    error_rate_pct: zod.number().describe('Aggregate error rate across all tool calls in the cluster, 0–100.'),
    routing_entropy: zod
        .number()
        .describe(
            'Normalised Shannon entropy of the tool distribution. 0 means perfectly consistent routing (one tool dominates); 1 means uniformly spread across all tools called for this intent cluster.'
        ),
    tool_distribution: zod
        .array(MCPIntentClusterToolEntryApi)
        .describe('Per-tool breakdown of calls and errors within the cluster.'),
    sample_intents: zod
        .array(zod.string())
        .describe('Up to three representative intent strings from the cluster, ordered by frequency desc.'),
    journey: zod
        .union([MCPIntentClusterJourneyApi, zod.null()])
        .describe(
            'Top Sankey-shaped paths the agents took within this cluster. Each path is up to four ordered tool calls plus a completed\/error outcome. Null when journey data is unavailable.'
        ),
})

export type MCPIntentClusterApi = zod.input<typeof MCPIntentClusterApi>
export type MCPIntentClusterApiOutput = zod.output<typeof MCPIntentClusterApi>

export const MCPIntentClusterSnapshotMetaApi = zod.object({
    distance_threshold: zod.number().describe('Cosine distance threshold used by the clustering algorithm.'),
    embedding_model: zod.string().describe('Embedding model used to vectorise intents.'),
    n_intents: zod.number().describe('Number of distinct intents that fed into the clustering run.'),
    n_clusters: zod.number().describe('Number of clusters produced by the run.'),
})

export type MCPIntentClusterSnapshotMetaApi = zod.input<typeof MCPIntentClusterSnapshotMetaApi>
export type MCPIntentClusterSnapshotMetaApiOutput = zod.output<typeof MCPIntentClusterSnapshotMetaApi>

export const MCPIntentClusterSnapshotApi = zod.object({
    status: MCPIntentClusterSnapshotStatusEnumApi.describe(
        'Whether a snapshot is current (idle), being recomputed (computing), or failed (error).\n\n\* `idle` - Idle\n\* `computing` - Computing\n\* `error` - Error'
    ),
    error_message: zod.string().describe('Error message from the most recent failed run, otherwise empty.'),
    last_computed_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the latest snapshot finished computing.'),
    last_computed_by_email: zod
        .string()
        .describe('Email of the user who triggered the latest recompute, empty for system-triggered runs.'),
    clusters: zod.array(MCPIntentClusterApi).describe('All clusters in the snapshot.'),
    computed_with: zod
        .union([MCPIntentClusterSnapshotMetaApi, zod.null()])
        .describe('Settings used to produce the snapshot. Null when no snapshot has been computed yet.'),
})

export type MCPIntentClusterSnapshotApi = zod.input<typeof MCPIntentClusterSnapshotApi>
export type MCPIntentClusterSnapshotApiOutput = zod.output<typeof MCPIntentClusterSnapshotApi>

export const mCPMissingCapabilityCreateApiAttemptedToolDefault = ``
export const mCPMissingCapabilityCreateApiAttemptedToolMax = 200

export const mCPMissingCapabilityCreateApiMcpClientNameDefault = ``
export const mCPMissingCapabilityCreateApiMcpClientNameMax = 200

export const mCPMissingCapabilityCreateApiMcpClientVersionDefault = ``
export const mCPMissingCapabilityCreateApiMcpClientVersionMax = 100

export const mCPMissingCapabilityCreateApiMcpProtocolVersionDefault = ``
export const mCPMissingCapabilityCreateApiMcpProtocolVersionMax = 50

export const mCPMissingCapabilityCreateApiMcpTransportDefault = ``
export const mCPMissingCapabilityCreateApiMcpTransportMax = 50

export const mCPMissingCapabilityCreateApiMcpSessionIdDefault = ``
export const mCPMissingCapabilityCreateApiMcpSessionIdMax = 200

export const mCPMissingCapabilityCreateApiMcpTraceIdDefault = ``
export const mCPMissingCapabilityCreateApiMcpTraceIdMax = 200

export const mCPMissingCapabilityCreateApiGoalMax = 500

export const mCPMissingCapabilityCreateApiMissingCapabilityMax = 5000

export const mCPMissingCapabilityCreateApiBlockedDefault = true

export const MCPMissingCapabilityCreateApi = zod.object({
    attempted_tool: zod
        .string()
        .max(mCPMissingCapabilityCreateApiAttemptedToolMax)
        .default(mCPMissingCapabilityCreateApiAttemptedToolDefault)
        .describe('The tool the user tried before leaving feedback, if known.'),
    mcp_client_name: zod
        .string()
        .max(mCPMissingCapabilityCreateApiMcpClientNameMax)
        .default(mCPMissingCapabilityCreateApiMcpClientNameDefault)
        .describe('MCP client name, for example Claude Desktop or Cursor.'),
    mcp_client_version: zod
        .string()
        .max(mCPMissingCapabilityCreateApiMcpClientVersionMax)
        .default(mCPMissingCapabilityCreateApiMcpClientVersionDefault)
        .describe('Version string for the MCP client when available.'),
    mcp_protocol_version: zod
        .string()
        .max(mCPMissingCapabilityCreateApiMcpProtocolVersionMax)
        .default(mCPMissingCapabilityCreateApiMcpProtocolVersionDefault)
        .describe('MCP protocol version negotiated for the session when available.'),
    mcp_transport: zod
        .string()
        .max(mCPMissingCapabilityCreateApiMcpTransportMax)
        .default(mCPMissingCapabilityCreateApiMcpTransportDefault)
        .describe('Transport used for the MCP session, for example streamable_http or sse.'),
    mcp_session_id: zod
        .string()
        .max(mCPMissingCapabilityCreateApiMcpSessionIdMax)
        .default(mCPMissingCapabilityCreateApiMcpSessionIdDefault)
        .describe('Stable MCP session identifier when available.'),
    mcp_trace_id: zod
        .string()
        .max(mCPMissingCapabilityCreateApiMcpTraceIdMax)
        .default(mCPMissingCapabilityCreateApiMcpTraceIdDefault)
        .describe('Trace identifier for the surrounding MCP workflow when available.'),
    goal: zod
        .string()
        .max(mCPMissingCapabilityCreateApiGoalMax)
        .describe("The user's intended outcome when using MCP."),
    missing_capability: zod
        .string()
        .max(mCPMissingCapabilityCreateApiMissingCapabilityMax)
        .describe('Capability, tool, or workflow support that is currently missing.'),
    blocked: zod
        .boolean()
        .default(mCPMissingCapabilityCreateApiBlockedDefault)
        .describe("Whether the missing capability blocked the user's progress."),
})

export type MCPMissingCapabilityCreateApi = zod.input<typeof MCPMissingCapabilityCreateApi>
export type MCPMissingCapabilityCreateApiOutput = zod.output<typeof MCPMissingCapabilityCreateApi>

export const MCPSessionApi = zod.object({
    session_id: zod.string().describe('$mcp_session_id grouping all $mcp_tool_call events in the session.'),
    tool_calls: zod.number().describe('Total number of $mcp_tool_call events in the session.'),
    session_start: zod.iso
        .datetime({ offset: true })
        .describe('Timestamp of the first $mcp_tool_call event in the session.'),
    session_end: zod.iso
        .datetime({ offset: true })
        .describe('Timestamp of the most recent $mcp_tool_call event in the session.'),
    distinct_id_count: zod
        .number()
        .describe('Number of distinct PostHog distinct_ids that produced events in the session.'),
    tools_used: zod.array(zod.string()).describe('Distinct $mcp_tool_name values seen in the session.'),
    mcp_client_name: zod.string().describe('Most recent $mcp_client_name observed in the session.'),
    distinct_id: zod
        .string()
        .describe(
            'Most recent distinct_id observed for the session. Stable identifier the SDK tagged the events with.'
        ),
    person_email: zod
        .string()
        .describe('email property of the Person resolved from distinct_id; empty when no Person is mapped.'),
    person_name: zod
        .string()
        .describe('name property of the Person resolved from distinct_id; empty when no Person is mapped.'),
    intent: zod
        .string()
        .describe(
            "LLM-generated summary (at most two sentences) of the agent's overall goal for the session. Empty until generated on demand via the generate_intent endpoint."
        ),
})

export type MCPSessionApi = zod.input<typeof MCPSessionApi>
export type MCPSessionApiOutput = zod.output<typeof MCPSessionApi>

export const PaginatedMCPSessionListApi = zod.object({
    results: zod.array(MCPSessionApi),
    has_next: zod
        .boolean()
        .describe(
            'Whether more results exist beyond this page; the client fetches the next page with a larger offset.'
        ),
})

export type PaginatedMCPSessionListApi = zod.input<typeof PaginatedMCPSessionListApi>
export type PaginatedMCPSessionListApiOutput = zod.output<typeof PaginatedMCPSessionListApi>

export const MCPSessionIntentApi = zod.object({
    session_id: zod.string().describe('$mcp_session_id the intent summary was generated for.'),
    intent: zod
        .string()
        .describe("LLM-generated summary (at most two sentences) of the agent's overall goal for the session."),
})

export type MCPSessionIntentApi = zod.input<typeof MCPSessionIntentApi>
export type MCPSessionIntentApiOutput = zod.output<typeof MCPSessionIntentApi>

export const MCPToolCallApi = zod.object({
    event_id: zod.string().describe('ClickHouse uuid of the $mcp_tool_call event.'),
    timestamp: zod.iso.datetime({ offset: true }).describe('When the tool call was captured.'),
    tool_name: zod.string().describe('Tool that was invoked ($mcp_tool_name).'),
    intent: zod
        .string()
        .describe('Agent intent for this tool call ($mcp_intent). Empty when the SDK did not capture context.'),
    is_error: zod.boolean().describe('Whether the tool call resulted in an error.'),
    error_message: zod.string().describe('Error message when is_error is true, otherwise empty.'),
    duration_ms: zod.number().nullable().describe('Duration of the tool call in milliseconds when captured.'),
})

export type MCPToolCallApi = zod.input<typeof MCPToolCallApi>
export type MCPToolCallApiOutput = zod.output<typeof MCPToolCallApi>

export const PaginatedMCPToolCallListApi = zod.object({
    results: zod.array(MCPToolCallApi),
    has_next: zod
        .boolean()
        .describe(
            'Whether more results exist beyond this page; the client fetches the next page with a larger offset.'
        ),
})

export type PaginatedMCPToolCallListApi = zod.input<typeof PaginatedMCPToolCallListApi>
export type PaginatedMCPToolCallListApiOutput = zod.output<typeof PaginatedMCPToolCallListApi>

export const MCPActivityStatsApi = zod.object({
    total_calls: zod.number().describe('$mcp_tool_call events captured in the last 30 days.'),
    distinct_tools: zod.number().describe('Distinct tools ($mcp_tool_name) called in the window.'),
    distinct_sessions: zod.number().describe('Distinct $session_ids seen on tool calls in the window.'),
    distinct_clients: zod.number().describe('Distinct agent clients ($mcp_client_name) seen in the window.'),
    calls_with_intent: zod.number().describe('Tool calls that carried an $mcp_intent, for intent-coverage checks.'),
    error_calls: zod.number().describe('Tool calls flagged as errors ($mcp_is_error) in the window.'),
    missing_capability_reports: zod.number().describe('$mcp_missing_capability events captured in the window.'),
})

export type MCPActivityStatsApi = zod.input<typeof MCPActivityStatsApi>
export type MCPActivityStatsApiOutput = zod.output<typeof MCPActivityStatsApi>

export const MCPActivityToolRowApi = zod.object({
    tool: zod.string().describe('MCP tool name ($mcp_tool_name).'),
    calls: zod.number().describe('Tool calls in the window.'),
    errors: zod.number().describe('Of those calls, how many errored.'),
})

export type MCPActivityToolRowApi = zod.input<typeof MCPActivityToolRowApi>
export type MCPActivityToolRowApiOutput = zod.output<typeof MCPActivityToolRowApi>

export const MCPActivityClientRowApi = zod.object({
    client: zod.string().describe('Agent client name ($mcp_client_name). Empty when the SDK did not capture it.'),
    calls: zod.number().describe('Tool calls from this client in the window.'),
})

export type MCPActivityClientRowApi = zod.input<typeof MCPActivityClientRowApi>
export type MCPActivityClientRowApiOutput = zod.output<typeof MCPActivityClientRowApi>

export const MCPActivityRecentCallApi = zod.object({
    timestamp: zod.iso.datetime({ offset: true }).describe('When the tool call was captured.'),
    tool: zod.string().describe('Tool that was invoked ($mcp_tool_name).'),
    intent: zod
        .string()
        .nullable()
        .describe('Agent intent for this tool call ($mcp_intent). Null when the SDK did not capture context.'),
    is_error: zod.boolean().describe('Whether the tool call resulted in an error.'),
    error_message: zod
        .string()
        .nullable()
        .describe("Human-readable error extracted from the tool's response when is_error is true, otherwise null."),
    duration_ms: zod.number().nullable().describe('Duration of the tool call in milliseconds when captured.'),
    client_name: zod.string().nullable().describe('Agent client name ($mcp_client_name) when captured.'),
})

export type MCPActivityRecentCallApi = zod.input<typeof MCPActivityRecentCallApi>
export type MCPActivityRecentCallApiOutput = zod.output<typeof MCPActivityRecentCallApi>

export const MCPActivityOverviewApi = zod.object({
    stats: MCPActivityStatsApi.describe('Aggregate counters over the last 30 days.'),
    top_tools: zod.array(MCPActivityToolRowApi).describe('Most-called tools in the window, top 5 by call count.'),
    clients: zod.array(MCPActivityClientRowApi).describe('Agent clients in the window, top 6 by call count.'),
    recent_calls: zod.array(MCPActivityRecentCallApi).describe('The 20 most recent tool calls, newest first.'),
})

export type MCPActivityOverviewApi = zod.input<typeof MCPActivityOverviewApi>
export type MCPActivityOverviewApiOutput = zod.output<typeof MCPActivityOverviewApi>

export const MCPIntentThemeApi = zod.object({
    name: zod.string().describe('Short sentence-case name for this group of intents.'),
    description: zod.string().describe('One concrete sentence describing what agents in this theme are doing.'),
    intent_count: zod
        .number()
        .describe(
            "How many of the analysed intents the LLM assigned to this theme, counted from the corpus rather than reported by the LLM. Each intent belongs to at most one theme, so these never sum to more than the digest's intent_count."
        ),
    example_intent: zod.string().describe("One of this theme's intents, verbatim from the corpus."),
    tools: zod
        .array(zod.string())
        .describe("The MCP tool names recorded alongside this theme's intents, sorted, taken from the corpus."),
})

export type MCPIntentThemeApi = zod.input<typeof MCPIntentThemeApi>
export type MCPIntentThemeApiOutput = zod.output<typeof MCPIntentThemeApi>

export const MCPIntentDigestApi = zod.object({
    digest: zod
        .string()
        .nullable()
        .describe(
            'LLM-generated one-sentence summary of what agents are trying to do with this MCP server, derived from the most recent recorded $mcp_intents across all sessions. Null when the project has no recorded intents yet.'
        ),
    intent_count: zod
        .number()
        .describe('How many recorded intents (the most recent, capped at 100) the digest was derived from.'),
    themes: zod
        .array(MCPIntentThemeApi)
        .describe(
            "Up to 5 semantic groupings of the analysed intents, largest first. May be empty when the digest is null, or when none of the LLM's groupings resolved to recorded intents."
        ),
})

export type MCPIntentDigestApi = zod.input<typeof MCPIntentDigestApi>
export type MCPIntentDigestApiOutput = zod.output<typeof MCPIntentDigestApi>
