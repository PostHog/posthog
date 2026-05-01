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
    InstallCustomApi,
    InstallTemplateApi,
    MCPServerInstallationApi,
    MCPServerInstallationToolApi,
    McpServerInstallationsAuthorizeRetrieveParams,
    McpServerInstallationsListParams,
    McpServersListParams,
    OAuthRedirectResponseApi,
    PaginatedMCPServerInstallationListApi,
    PaginatedMCPServerInstallationToolListApi,
    PaginatedMCPServerTemplateListApi,
    PatchedMCPServerInstallationUpdateApi,
    PatchedToolApprovalUpdateApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

export const getMcpServerInstallationsListUrl = (projectId: string, params?: McpServerInstallationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/mcp_server_installations/?${stringifiedParams}`
        : `/api/environments/${projectId}/mcp_server_installations/`
}

export const mcpServerInstallationsList = async (
    projectId: string,
    params?: McpServerInstallationsListParams,
    options?: RequestInit
): Promise<PaginatedMCPServerInstallationListApi> => {
    return apiMutator<PaginatedMCPServerInstallationListApi>(getMcpServerInstallationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMcpServerInstallationsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/mcp_server_installations/`
}

export const mcpServerInstallationsCreate = async (
    projectId: string,
    mCPServerInstallationApi: NonReadonly<MCPServerInstallationApi>,
    options?: RequestInit
): Promise<MCPServerInstallationApi> => {
    return apiMutator<MCPServerInstallationApi>(getMcpServerInstallationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mCPServerInstallationApi),
    })
}

export const getMcpServerInstallationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/mcp_server_installations/${id}/`
}

export const mcpServerInstallationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MCPServerInstallationApi> => {
    return apiMutator<MCPServerInstallationApi>(getMcpServerInstallationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getMcpServerInstallationsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/mcp_server_installations/${id}/`
}

export const mcpServerInstallationsUpdate = async (
    projectId: string,
    id: string,
    mCPServerInstallationApi: NonReadonly<MCPServerInstallationApi>,
    options?: RequestInit
): Promise<MCPServerInstallationApi> => {
    return apiMutator<MCPServerInstallationApi>(getMcpServerInstallationsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mCPServerInstallationApi),
    })
}

export const getMcpServerInstallationsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/mcp_server_installations/${id}/`
}

export const mcpServerInstallationsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedMCPServerInstallationUpdateApi: PatchedMCPServerInstallationUpdateApi,
    options?: RequestInit
): Promise<MCPServerInstallationApi> => {
    return apiMutator<MCPServerInstallationApi>(getMcpServerInstallationsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedMCPServerInstallationUpdateApi),
    })
}

export const getMcpServerInstallationsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/mcp_server_installations/${id}/`
}

export const mcpServerInstallationsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMcpServerInstallationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getMcpServerInstallationsProxyCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/mcp_server_installations/${id}/proxy/`
}

export const mcpServerInstallationsProxyCreate = async (
    projectId: string,
    id: string,
    mCPServerInstallationApi: NonReadonly<MCPServerInstallationApi>,
    options?: RequestInit
): Promise<Blob> => {
    return apiMutator<Blob>(getMcpServerInstallationsProxyCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mCPServerInstallationApi),
    })
}

export const getMcpServerInstallationsToolsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/mcp_server_installations/${id}/tools/`
}

export const mcpServerInstallationsToolsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<PaginatedMCPServerInstallationToolListApi> => {
    return apiMutator<PaginatedMCPServerInstallationToolListApi>(
        getMcpServerInstallationsToolsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getMcpServerInstallationsToolsPartialUpdateUrl = (projectId: string, id: string, toolName: string) => {
    return `/api/environments/${projectId}/mcp_server_installations/${id}/tools/${toolName}/`
}

export const mcpServerInstallationsToolsPartialUpdate = async (
    projectId: string,
    id: string,
    toolName: string,
    patchedToolApprovalUpdateApi: PatchedToolApprovalUpdateApi,
    options?: RequestInit
): Promise<MCPServerInstallationToolApi> => {
    return apiMutator<MCPServerInstallationToolApi>(
        getMcpServerInstallationsToolsPartialUpdateUrl(projectId, id, toolName),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedToolApprovalUpdateApi),
        }
    )
}

export const getMcpServerInstallationsToolsRefreshCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/mcp_server_installations/${id}/tools/refresh/`
}

export const mcpServerInstallationsToolsRefreshCreate = async (
    projectId: string,
    id: string,
    mCPServerInstallationApi: NonReadonly<MCPServerInstallationApi>,
    options?: RequestInit
): Promise<PaginatedMCPServerInstallationToolListApi> => {
    return apiMutator<PaginatedMCPServerInstallationToolListApi>(
        getMcpServerInstallationsToolsRefreshCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(mCPServerInstallationApi),
        }
    )
}

/**
 * Start (or re-start) an OAuth flow.

Pass ``template_id`` to (re)connect a catalog template, or
``installation_id`` to reconnect an existing custom install using its
cached metadata and per-user DCR creds.
 */
export const getMcpServerInstallationsAuthorizeRetrieveUrl = (
    projectId: string,
    params?: McpServerInstallationsAuthorizeRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/mcp_server_installations/authorize/?${stringifiedParams}`
        : `/api/environments/${projectId}/mcp_server_installations/authorize/`
}

export const mcpServerInstallationsAuthorizeRetrieve = async (
    projectId: string,
    params?: McpServerInstallationsAuthorizeRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMcpServerInstallationsAuthorizeRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMcpServerInstallationsInstallCustomCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/mcp_server_installations/install_custom/`
}

export const mcpServerInstallationsInstallCustomCreate = async (
    projectId: string,
    installCustomApi: InstallCustomApi,
    options?: RequestInit
): Promise<OAuthRedirectResponseApi | MCPServerInstallationApi> => {
    return apiMutator<OAuthRedirectResponseApi | MCPServerInstallationApi>(
        getMcpServerInstallationsInstallCustomCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(installCustomApi),
        }
    )
}

export const getMcpServerInstallationsInstallTemplateCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/mcp_server_installations/install_template/`
}

export const mcpServerInstallationsInstallTemplateCreate = async (
    projectId: string,
    installTemplateApi: InstallTemplateApi,
    options?: RequestInit
): Promise<OAuthRedirectResponseApi | MCPServerInstallationApi> => {
    return apiMutator<OAuthRedirectResponseApi | MCPServerInstallationApi>(
        getMcpServerInstallationsInstallTemplateCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(installTemplateApi),
        }
    )
}

/**
 * Lists curated MCP server templates that users can install with one click.

Templates are seeded by PostHog operators and carry shared, encrypted
OAuth client credentials. Inactive templates are hidden from the catalog.
 */
export const getMcpServersListUrl = (projectId: string, params?: McpServersListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/mcp_servers/?${stringifiedParams}`
        : `/api/environments/${projectId}/mcp_servers/`
}

export const mcpServersList = async (
    projectId: string,
    params?: McpServersListParams,
    options?: RequestInit
): Promise<PaginatedMCPServerTemplateListApi> => {
    return apiMutator<PaginatedMCPServerTemplateListApi>(getMcpServersListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
