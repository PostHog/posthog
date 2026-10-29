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
    MCPEventArgumentsApi,
    MCPEventPreviewApi,
    MCPEventSubscribeApi,
    MCPEventSubscriptionApi,
    MCPEventUnsubscribeApi,
    McpEventSubscriptionsListParams,
    PaginatedMCPEventSubscriptionListApi,
} from './api.schemas'

export const getMcpEventSubscriptionsListUrl = (projectId: string, params?: McpEventSubscriptionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_event_subscriptions/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_event_subscriptions/`
}

export const mcpEventSubscriptionsList = async (
    projectId: string,
    params?: McpEventSubscriptionsListParams,
    options?: RequestInit
): Promise<PaginatedMCPEventSubscriptionListApi> => {
    return apiMutator<PaginatedMCPEventSubscriptionListApi>(getMcpEventSubscriptionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMcpEventSubscriptionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_event_subscriptions/${id}/`
}

export const mcpEventSubscriptionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MCPEventSubscriptionApi> => {
    return apiMutator<MCPEventSubscriptionApi>(getMcpEventSubscriptionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getMcpEventSubscriptionsPreviewUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_event_subscriptions/preview/`
}

export const mcpEventSubscriptionsPreview = async (
    projectId: string,
    mCPEventArgumentsApi: MCPEventArgumentsApi,
    options?: RequestInit
): Promise<MCPEventPreviewApi> => {
    return apiMutator<MCPEventPreviewApi>(getMcpEventSubscriptionsPreviewUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mCPEventArgumentsApi),
    })
}

export const getMcpEventSubscriptionsSubscribeCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_event_subscriptions/subscribe/`
}

export const mcpEventSubscriptionsSubscribeCreate = async (
    projectId: string,
    mCPEventSubscribeApi: MCPEventSubscribeApi,
    options?: RequestInit
): Promise<MCPEventSubscriptionApi> => {
    return apiMutator<MCPEventSubscriptionApi>(getMcpEventSubscriptionsSubscribeCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mCPEventSubscribeApi),
    })
}

export const getMcpEventSubscriptionsUnsubscribeCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_event_subscriptions/unsubscribe/`
}

export const mcpEventSubscriptionsUnsubscribeCreate = async (
    projectId: string,
    mCPEventUnsubscribeApi: MCPEventUnsubscribeApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMcpEventSubscriptionsUnsubscribeCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mCPEventUnsubscribeApi),
    })
}
