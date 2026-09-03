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
    MCPRankingVersionApi,
    MCPRegistryServerDetailApi,
    McpRegistryServersCompareRetrieve200,
    McpRegistryServersCompareRetrieveParams,
    McpRegistryServersDiscoverRetrieve200,
    McpRegistryServersDiscoverRetrieveParams,
    McpRegistryServersListParams,
    PaginatedMCPRegistryServerListListApi,
} from './api.schemas'

export const getMcpRegistryServersListUrl = (projectId: string, params?: McpRegistryServersListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_registry/servers/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_registry/servers/`
}

/**
 * List registry servers ordered by static rank under the chosen ranking version.
 */
export const mcpRegistryServersList = async (
    projectId: string,
    params?: McpRegistryServersListParams,
    options?: RequestInit
): Promise<PaginatedMCPRegistryServerListListApi> => {
    return apiMutator<PaginatedMCPRegistryServerListListApi>(getMcpRegistryServersListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMcpRegistryServersRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_registry/servers/${id}/`
}

/**
 * Full server record: tools, measured stats, per-version scores, connection instructions.
 */
export const mcpRegistryServersRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MCPRegistryServerDetailApi> => {
    return apiMutator<MCPRegistryServerDetailApi>(getMcpRegistryServersRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getMcpRegistryServersCompareRetrieveUrl = (
    projectId: string,
    params: McpRegistryServersCompareRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_registry/servers/compare/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_registry/servers/compare/`
}

/**
 * Rank the same index under several ranking versions side by side. With exactly two versions the response includes per-server rank deltas, the review surface for promoting a new ranking version.
 */
export const mcpRegistryServersCompareRetrieve = async (
    projectId: string,
    params: McpRegistryServersCompareRetrieveParams,
    options?: RequestInit
): Promise<McpRegistryServersCompareRetrieve200> => {
    return apiMutator<McpRegistryServersCompareRetrieve200>(
        getMcpRegistryServersCompareRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getMcpRegistryServersDiscoverRetrieveUrl = (
    projectId: string,
    params: McpRegistryServersDiscoverRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_registry/servers/discover/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_registry/servers/discover/`
}

/**
 * Given a task, return the MCP servers most likely to do it, each with its rank rationale, real usage signal where we measure it, and ready-to-run connection instructions. One call is everything an agent needs to go from a task to a connected server.
 */
export const mcpRegistryServersDiscoverRetrieve = async (
    projectId: string,
    params: McpRegistryServersDiscoverRetrieveParams,
    options?: RequestInit
): Promise<McpRegistryServersDiscoverRetrieve200> => {
    return apiMutator<McpRegistryServersDiscoverRetrieve200>(
        getMcpRegistryServersDiscoverRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getMcpRegistryServersVersionsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_registry/servers/versions/`
}

/**
 * Registered ranking versions and their latest completed runs.
 */
export const mcpRegistryServersVersionsList = async (
    projectId: string,
    options?: RequestInit
): Promise<MCPRankingVersionApi[]> => {
    return apiMutator<MCPRankingVersionApi[]>(getMcpRegistryServersVersionsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
