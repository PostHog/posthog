/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface MCPRegistryServerListApi {
    /** Registry server id. */
    id: string
    /** Reverse-DNS name in the official MCP registry; empty for measured-only servers. */
    registry_name: string
    /** Human-readable server name. */
    display_name: string
    /** Server description. */
    description: string
    /** Primary hosted remote URL; empty for package-only servers. */
    canonical_url: string
    /** Probed liveness state (alive_open, alive_auth, dead, ...). */
    liveness: string
    /** Detected auth method (none, oauth, api_key, unknown). */
    auth_method: string
    /** Whether the server appears in the official MCP registry. */
    listed_in_registry: boolean
    /** Whether real usage signal exists via MCP Analytics. */
    is_measured: boolean
    /** Static score under the requested ranking version; null when the version has no completed run. */
    readonly rank_score: number
}

export interface PaginatedMCPRegistryServerListListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MCPRegistryServerListApi[]
}

export type MCPRegistryServerDetailApiRemotesItem = { [key: string]: unknown }

export type MCPRegistryServerDetailApiPackagesItem = { [key: string]: unknown }

/**
 * Connection instructions: methods ordered most-automated first, steps typed by actor (agent executes; human steps are narrated to the user).
 */
export type MCPRegistryServerDetailApiConnect = { [key: string]: unknown }

/**
 * * `tools_list` - Probed tools/list
 * * `analytics` - MCP Analytics usage
 */
export type MCPRegistryToolSourceEnumApi =
    (typeof MCPRegistryToolSourceEnumApi)[keyof typeof MCPRegistryToolSourceEnumApi]

export const MCPRegistryToolSourceEnumApi = {
    ToolsList: 'tools_list',
    Analytics: 'analytics',
} as const

/**
 * JSON Schema for the tool's input. Only populated for probed (tools_list) tools.
 */
export type MCPRegistryToolApiInputSchema = { [key: string]: unknown }

export interface MCPRegistryToolApi {
    /** Tool name as advertised by the server (exec-resolved for measured servers). */
    name: string
    /** Tool description, from tools/list or from observed calls. */
    description: string
    /** JSON Schema for the tool's input. Only populated for probed (tools_list) tools. */
    input_schema: MCPRegistryToolApiInputSchema
    /** Where we learned about this tool: a probed tools/list (authoritative schema) or MCP Analytics usage (proof of real calls, no schema).
     *
     * * `tools_list` - Probed tools/list
     * * `analytics` - MCP Analytics usage */
    source: MCPRegistryToolSourceEnumApi
    /** Last time this tool was observed by either source. */
    last_seen_at: string
}

export type MCPMeasuredStatsApiToolStatsItem = { [key: string]: unknown }

export type MCPMeasuredStatsApiLinkCandidatesItem = { [key: string]: unknown }

export interface MCPMeasuredStatsApi {
    /** Aggregation window in days. */
    window_days: number
    /** Tool calls observed in the window. */
    calls: number
    /** Distinct MCP sessions observed in the window. */
    sessions: number
    /**
     * Errored tool calls in the window.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    errors?: number
    /** Errors as a percentage of calls. */
    error_rate_pct: number
    /** Percentage of calls carrying an agent-written intent ($mcp_intent). */
    intent_coverage_pct: number
    /** Distinct effective tools called in the window. */
    distinct_tools: number
    /** Distinct MCP client names observed in the window. */
    harness_count: number
    /** Per-tool usage, ordered by call volume: [{name, calls, errors, error_rate_pct}]. */
    tool_stats: MCPMeasuredStatsApiToolStatsItem[]
    /** How this measured source was attached to its registry entry (override | url | exact_name | standalone). */
    link_method: string
    /** Registry names that also matched when linking was ambiguous (kept for review). */
    link_candidates: MCPMeasuredStatsApiLinkCandidatesItem[]
    /** When this aggregate was computed. */
    computed_at: string
}

/**
 * Score inputs (liveness, trust, measured signals) for explainability.
 */
export type MCPRankingScoreInfoApiComponents = { [key: string]: unknown }

/**
 * One ranking version's latest score for a server.
 */
export interface MCPRankingScoreInfoApi {
    /** Ranking version key (see the versions endpoint). */
    version: string
    /** Static score in [0, 1]; higher ranks first. */
    score: number
    /** Score inputs (liveness, trust, measured signals) for explainability. */
    components: MCPRankingScoreInfoApiComponents
    /**
     * When the run producing this score completed.
     * @nullable
     */
    computed_at: string | null
}

export interface MCPRegistryServerDetailApi {
    /** Registry server id. */
    id: string
    /** Reverse-DNS name in the official MCP registry; empty for measured-only servers. */
    registry_name: string
    /** Human-readable server name. */
    display_name: string
    /** Server description. */
    description: string
    /** Primary hosted remote URL; empty for package-only servers. */
    canonical_url: string
    /** Probed liveness state (alive_open, alive_auth, dead, ...). */
    liveness: string
    /** Detected auth method (none, oauth, api_key, unknown). */
    auth_method: string
    /** Whether the server appears in the official MCP registry. */
    listed_in_registry: boolean
    /** Whether real usage signal exists via MCP Analytics. */
    is_measured: boolean
    /** Static score under the requested ranking version; null when the version has no completed run. */
    readonly rank_score: number
    /** All hosted remotes: [{type, url}]. */
    remotes: MCPRegistryServerDetailApiRemotesItem[]
    /** Published packages: [{registry_type, identifier}]. */
    packages: MCPRegistryServerDetailApiPackagesItem[]
    /** Source repository URL, when published. */
    repository_url: string
    /** Vendor website URL, when published. */
    website_url: string
    /**
     * When the shallow probe last ran.
     * @nullable
     */
    last_probed_at: string | null
    /** Known tools, fused from probes and analytics. A tool known only from another project's traffic is limited to callers who may see that project's measurements. */
    readonly tools: readonly MCPRegistryToolApi[]
    /** Behavioral aggregates, one per measured MCP Analytics project. Limited to this project's own measurements unless the server is marked measured_public. */
    readonly measured_stats: readonly MCPMeasuredStatsApi[]
    /** Latest score under every ranking version with a completed run. */
    readonly scores: readonly MCPRankingScoreInfoApi[]
    /** Connection instructions: methods ordered most-automated first, steps typed by actor (agent executes; human steps are narrated to the user). */
    readonly connect: MCPRegistryServerDetailApiConnect
}

/**
 * Score breakdown so an agent can explain its choice: fit, liveness, trust, and whether real usage signal contributed.
 */
export type MCPDiscoverCandidateApiWhy = { [key: string]: unknown }

/**
 * Real MCP Analytics aggregates when the server is measured, otherwise null: calls, sessions, error_rate_pct, intent_coverage_pct, harness_count.
 * @nullable
 */
export type MCPDiscoverCandidateApiMeasured = { [key: string]: unknown } | null

export type MCPDiscoverCandidateApiMatchedToolsItem = { [key: string]: unknown }

/**
 * Connection instructions, most-automated method first, steps typed by actor so the agent runs its own steps and narrates the human ones.
 */
export type MCPDiscoverCandidateApiConnect = { [key: string]: unknown }

/**
 * One ranked candidate in a discover response, with everything an agent needs to act.
 */
export interface MCPDiscoverCandidateApi {
    /** 1-based position under the ranking version used. */
    rank: number
    /** Registry server id, for the detail endpoint. */
    id: string
    /** Official registry name, empty for measured-only servers. */
    registry_name: string
    /** Human-readable server name. */
    title: string
    /** What the server does. */
    description: string
    /** Rank score in [0, 1] under the ranking version used. */
    score: number
    /** Score breakdown so an agent can explain its choice: fit, liveness, trust, and whether real usage signal contributed. */
    why: MCPDiscoverCandidateApiWhy
    /** Probed liveness state (alive_open, alive_auth, dead, ...). */
    liveness: string
    /** Detected auth method (none, oauth, api_key, unknown). */
    auth_method: string
    /**
     * Real MCP Analytics aggregates when the server is measured, otherwise null: calls, sessions, error_rate_pct, intent_coverage_pct, harness_count.
     * @nullable
     */
    measured: MCPDiscoverCandidateApiMeasured
    /** Tools that matched the intent: [{name, description, source}]. Empty when only the server description matched. */
    matched_tools: MCPDiscoverCandidateApiMatchedToolsItem[]
    /** Connection instructions, most-automated method first, steps typed by actor so the agent runs its own steps and narrates the human ones. */
    connect: MCPDiscoverCandidateApiConnect
}

/**
 * Everything an agent gets back from one discover call.
 */
export interface MCPDiscoverResponseApi {
    /** The intent the candidates were ranked against, echoed back. */
    intent: string
    /** Ranking version the candidates were ordered by. */
    ranking_version: string
    /** Servers most likely to do the thing, best first. */
    candidates: MCPDiscoverCandidateApi[]
}

/**
 * One project's contribution to the measured layer, for the staff fleet view.
 */
export interface MCPMeasuredProjectApi {
    /** Project supplying the MCP Analytics signal. */
    team_id: number
    /** Distinct servers this project has measured. */
    servers: number
    /** Tool calls this project contributes across those servers. */
    calls: number
}

/**
 * Latest completed run: {id, server_count, computed_at}; null when the version never ran.
 * @nullable
 */
export type MCPRankingVersionApiLatestRun = { [key: string]: unknown } | null

/**
 * A registered ranking version and its latest completed run.
 */
export interface MCPRankingVersionApi {
    /** Ranking version key, passed as ?version= to the list endpoint. */
    version: string
    /** What this version scores on. */
    description: string
    /** Whether this is the version used when ?version= is omitted. */
    is_default: boolean
    /**
     * Latest completed run: {id, server_count, computed_at}; null when the version never ran.
     * @nullable
     */
    latest_run: MCPRankingVersionApiLatestRun
}

export type McpRegistryServersListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * Only servers with real MCP Analytics signal.
     */
    measured_only?: boolean
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Free-text query matched against server names, descriptions, and tool names.
     */
    search?: string
    /**
     * Ranking version ordering the results; defaults to the current default version.
     */
    version?: string
}

export type McpRegistryServersCompareRetrieveParams = {
    /**
     * Rows per arm (default 20, max 100).
     */
    limit?: number
    /**
     * Optional text filter applied to every arm.
     */
    search?: string
    /**
     * Comma-separated ranking versions to compare (2+).
     */
    versions: string
}

export type McpRegistryServersCompareRetrieve200 = { [key: string]: unknown }

export type McpRegistryServersDiscoverRetrieveParams = {
    /**
     * What the agent is trying to do, in natural language.
     */
    intent: string
    /**
     * Candidates to return (default 5, max 20).
     */
    limit?: number
    /**
     * Ranking version to rank candidates by.
     */
    version?: string
}
