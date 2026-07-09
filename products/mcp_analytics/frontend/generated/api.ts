import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    MCPActivityOverviewApi,
    MCPAnalyticsSubmissionApi,
    MCPFeedbackCreateApi,
    MCPIntentClusterSnapshotApi,
    MCPIntentDigestApi,
    MCPMissingCapabilityCreateApi,
    MCPSessionIntentApi,
    McpAnalyticsFeedbackListParams,
    McpAnalyticsMissingCapabilitiesListParams,
    McpAnalyticsSessionsGenerateIntentParams,
    McpAnalyticsSessionsListParams,
    McpAnalyticsSessionsToolCallsParams,
    PaginatedMCPAnalyticsSubmissionListApi,
    PaginatedMCPSessionListApi,
    PaginatedMCPToolCallListApi,
} from './api.schemas'

export const getMcpAnalyticsFeedbackListUrl = (projectId: string, params?: McpAnalyticsFeedbackListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_analytics/feedback/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_analytics/feedback/`
}

/**
 * List MCP feedback submissions for the current project, newest first.
 */
export const mcpAnalyticsFeedbackList = async (
    projectId: string,
    params?: McpAnalyticsFeedbackListParams,
    options?: RequestInit
): Promise<PaginatedMCPAnalyticsSubmissionListApi> => {
    return apiMutator<PaginatedMCPAnalyticsSubmissionListApi>(getMcpAnalyticsFeedbackListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMcpAnalyticsFeedbackCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_analytics/feedback/`
}

/**
 * Create a new MCP feedback submission for the current project.
 */
export const mcpAnalyticsFeedbackCreate = async (
    projectId: string,
    mCPFeedbackCreateApi: MCPFeedbackCreateApi,
    options?: RequestInit
): Promise<MCPAnalyticsSubmissionApi> => {
    return apiMutator<MCPAnalyticsSubmissionApi>(getMcpAnalyticsFeedbackCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mCPFeedbackCreateApi),
    })
}

export const getMcpAnalyticsIntentClustersRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_analytics/intent_clusters/`
}

/**
 * Return the most recent intent cluster snapshot for the current project. Returns an empty IDLE snapshot when no clustering run has happened yet.
 */
export const mcpAnalyticsIntentClustersRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<MCPIntentClusterSnapshotApi[]> => {
    return apiMutator<MCPIntentClusterSnapshotApi[]>(getMcpAnalyticsIntentClustersRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMcpAnalyticsIntentClustersRecomputeUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_analytics/intent_clusters/recompute/`
}

/**
 * Trigger an asynchronous recompute of the intent cluster snapshot. The task runs in the background; poll the GET endpoint for progress (status transitions to 'idle' or 'error').
 */
export const mcpAnalyticsIntentClustersRecompute = async (
    projectId: string,
    options?: RequestInit
): Promise<MCPIntentClusterSnapshotApi> => {
    return apiMutator<MCPIntentClusterSnapshotApi>(getMcpAnalyticsIntentClustersRecomputeUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getMcpAnalyticsMissingCapabilitiesListUrl = (
    projectId: string,
    params?: McpAnalyticsMissingCapabilitiesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_analytics/missing_capabilities/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_analytics/missing_capabilities/`
}

/**
 * List missing capability reports for the current project, newest first.
 */
export const mcpAnalyticsMissingCapabilitiesList = async (
    projectId: string,
    params?: McpAnalyticsMissingCapabilitiesListParams,
    options?: RequestInit
): Promise<PaginatedMCPAnalyticsSubmissionListApi> => {
    return apiMutator<PaginatedMCPAnalyticsSubmissionListApi>(
        getMcpAnalyticsMissingCapabilitiesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getMcpAnalyticsMissingCapabilitiesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_analytics/missing_capabilities/`
}

/**
 * Create a new missing capability report for the current project.
 */
export const mcpAnalyticsMissingCapabilitiesCreate = async (
    projectId: string,
    mCPMissingCapabilityCreateApi: MCPMissingCapabilityCreateApi,
    options?: RequestInit
): Promise<MCPAnalyticsSubmissionApi> => {
    return apiMutator<MCPAnalyticsSubmissionApi>(getMcpAnalyticsMissingCapabilitiesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mCPMissingCapabilityCreateApi),
    })
}

export const getMcpAnalyticsSessionsListUrl = (projectId: string, params?: McpAnalyticsSessionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_analytics/sessions/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_analytics/sessions/`
}

/**
 * List MCP sessions for the current project, derived by grouping $mcp_tool_call events by $mcp_session_id. Ordered by newest session start first by default.
 */
export const mcpAnalyticsSessionsList = async (
    projectId: string,
    params?: McpAnalyticsSessionsListParams,
    options?: RequestInit
): Promise<PaginatedMCPSessionListApi> => {
    return apiMutator<PaginatedMCPSessionListApi>(getMcpAnalyticsSessionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMcpAnalyticsSessionsGenerateIntentUrl = (
    projectId: string,
    id: string,
    params?: McpAnalyticsSessionsGenerateIntentParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_analytics/sessions/${id}/generate_intent/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_analytics/sessions/${id}/generate_intent/`
}

/**
 * Generate (or return the cached) LLM summary of the agent's goal for a session, derived from its recorded $mcp_intents. The first call summarises and persists the result; subsequent calls return the stored summary.
 */
export const mcpAnalyticsSessionsGenerateIntent = async (
    projectId: string,
    id: string,
    params?: McpAnalyticsSessionsGenerateIntentParams,
    options?: RequestInit
): Promise<MCPSessionIntentApi> => {
    return apiMutator<MCPSessionIntentApi>(getMcpAnalyticsSessionsGenerateIntentUrl(projectId, id, params), {
        ...options,
        method: 'POST',
    })
}

export const getMcpAnalyticsSessionsToolCallsUrl = (
    projectId: string,
    id: string,
    params?: McpAnalyticsSessionsToolCallsParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_analytics/sessions/${id}/tool_calls/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_analytics/sessions/${id}/tool_calls/`
}

/**
 * List a page of the $mcp_tool_call events that belong to a given $session_id, in chronological order.
 */
export const mcpAnalyticsSessionsToolCalls = async (
    projectId: string,
    id: string,
    params?: McpAnalyticsSessionsToolCallsParams,
    options?: RequestInit
): Promise<PaginatedMCPToolCallListApi> => {
    return apiMutator<PaginatedMCPToolCallListApi>(getMcpAnalyticsSessionsToolCallsUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getMcpAnalyticsSessionsActivityOverviewUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_analytics/sessions/activity_overview/`
}

/**
 * Aggregate counters, top tools, agent clients, and the most recent tool calls for the last 30 days, computed in one request. Powers the dashboard's activity view; always computed fresh so polling callers watch data arrive.
 */
export const mcpAnalyticsSessionsActivityOverview = async (
    projectId: string,
    options?: RequestInit
): Promise<MCPActivityOverviewApi> => {
    return apiMutator<MCPActivityOverviewApi>(getMcpAnalyticsSessionsActivityOverviewUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMcpAnalyticsSessionsIntentDigestUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_analytics/sessions/intent_digest/`
}

/**
 * Generate (or return the cached) LLM digest of what agents are trying to do with this MCP server, derived from the most recent recorded $mcp_intents across all sessions. Content-addressed cache: only regenerates when new intents arrive. Powers the dashboard's low-volume activity stage.
 */
export const mcpAnalyticsSessionsIntentDigest = async (
    projectId: string,
    options?: RequestInit
): Promise<MCPIntentDigestApi> => {
    return apiMutator<MCPIntentDigestApi>(getMcpAnalyticsSessionsIntentDigestUrl(projectId), {
        ...options,
        method: 'POST',
    })
}
