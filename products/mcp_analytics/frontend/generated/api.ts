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
    MCPAnalyticsSubmissionApi,
    MCPFeedbackCreateApi,
    MCPMissingCapabilityCreateApi,
    McpAnalyticsFeedbackListParams,
    McpAnalyticsMissingCapabilitiesListParams,
    PaginatedMCPAnalyticsSubmissionListApi,
} from './api.schemas'

/**
 * List MCP feedback submissions for the current project, newest first.
 */
export const getMcpAnalyticsFeedbackListUrl = (projectId: string, params?: McpAnalyticsFeedbackListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/mcp_analytics/feedback/?${stringifiedParams}`
        : `/api/environments/${projectId}/mcp_analytics/feedback/`
}

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

/**
 * Create a new MCP feedback submission for the current project.
 */
export const getMcpAnalyticsFeedbackCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/mcp_analytics/feedback/`
}

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

/**
 * List missing capability reports for the current project, newest first.
 */
export const getMcpAnalyticsMissingCapabilitiesListUrl = (
    projectId: string,
    params?: McpAnalyticsMissingCapabilitiesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/mcp_analytics/missing_capabilities/?${stringifiedParams}`
        : `/api/environments/${projectId}/mcp_analytics/missing_capabilities/`
}

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

/**
 * Create a new missing capability report for the current project.
 */
export const getMcpAnalyticsMissingCapabilitiesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/mcp_analytics/missing_capabilities/`
}

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
