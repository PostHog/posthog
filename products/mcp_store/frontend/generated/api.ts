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
    ApplyPresetApi,
    AuditCountsApi,
    GatewayConfigUpdateApi,
    GatewayMemberSummaryApi,
    GatewayPoliciesUpsertApi,
    InstallCustomApi,
    InstallTemplateApi,
    MCPAuditEventApi,
    MCPGatewayServerApi,
    MCPGatewayServerUpdateApi,
    MCPOrgRuleApi,
    MCPServerInstallationApi,
    MCPServerInstallationToolApi,
    MCPServiceAccountApi,
    MCPServiceAccountCreateApi,
    MCPServiceAccountUpdateApi,
    MCPServiceAccountWithTokenApi,
    McpGatewayAuditListParams,
    McpGatewayRulesListParams,
    McpGatewayServersListParams,
    McpGatewayServersToolsRetrieveParams,
    McpGatewayServiceAccountsListParams,
    McpServerInstallationsAuthorizeRetrieveParams,
    McpServerInstallationsListParams,
    McpServersListParams,
    MemberAccessUpdateApi,
    OAuthRedirectResponseApi,
    PaginatedMCPAuditEventListApi,
    PaginatedMCPGatewayServerListApi,
    PaginatedMCPOrgRuleListApi,
    PaginatedMCPServerInstallationListApi,
    PaginatedMCPServerInstallationToolListApi,
    PaginatedMCPServerTemplateListApi,
    PaginatedMCPServiceAccountListApi,
    PaginatedResolvedToolPolicyListApi,
    PatchedMCPGatewayServerUpdateApi,
    PatchedMCPOrgRuleApi,
    PatchedMCPServerInstallationUpdateApi,
    PatchedMCPServiceAccountUpdateApi,
    PatchedToolApprovalUpdateApi,
    ServiceAccountAccessUpdateApi,
    TeamMCPGatewayConfigApi,
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

export const getMcpGatewayAuditListUrl = (projectId: string, params?: McpGatewayAuditListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_gateway/audit/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_gateway/audit/`
}

/**
 * Read-only trail of proxied tool calls. Admin-only — it exposes what
 * every member and agent has been doing.
 */
export const mcpGatewayAuditList = async (
    projectId: string,
    params?: McpGatewayAuditListParams,
    options?: RequestInit
): Promise<PaginatedMCPAuditEventListApi> => {
    return apiMutator<PaginatedMCPAuditEventListApi>(getMcpGatewayAuditListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMcpGatewayAuditRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/audit/${id}/`
}

/**
 * Read-only trail of proxied tool calls. Admin-only — it exposes what
 * every member and agent has been doing.
 */
export const mcpGatewayAuditRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MCPAuditEventApi> => {
    return apiMutator<MCPAuditEventApi>(getMcpGatewayAuditRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getMcpGatewayAuditCountsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_gateway/audit/counts/`
}

/**
 * Totals backing the quick-filter chips.
 */
export const mcpGatewayAuditCountsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<AuditCountsApi> => {
    return apiMutator<AuditCountsApi>(getMcpGatewayAuditCountsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMcpGatewayConfigListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_gateway/config/`
}

/**
 * The team's gateway settings, plus whether the caller can administer them.
 */
export const mcpGatewayConfigList = async (
    projectId: string,
    options?: RequestInit
): Promise<TeamMCPGatewayConfigApi> => {
    return apiMutator<TeamMCPGatewayConfigApi>(getMcpGatewayConfigListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMcpGatewayConfigApplyPresetCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_gateway/config/apply_preset/`
}

/**
 * Set the policy baseline for members or agents (admin-only).
 */
export const mcpGatewayConfigApplyPresetCreate = async (
    projectId: string,
    applyPresetApi: ApplyPresetApi,
    options?: RequestInit
): Promise<TeamMCPGatewayConfigApi> => {
    return apiMutator<TeamMCPGatewayConfigApi>(getMcpGatewayConfigApplyPresetCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(applyPresetApi),
    })
}

export const getMcpGatewayConfigUpdateSettingsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_gateway/config/update_settings/`
}

/**
 * Update team gateway settings (admin-only).
 */
export const mcpGatewayConfigUpdateSettingsCreate = async (
    projectId: string,
    gatewayConfigUpdateApi?: GatewayConfigUpdateApi,
    options?: RequestInit
): Promise<TeamMCPGatewayConfigApi> => {
    return apiMutator<TeamMCPGatewayConfigApi>(getMcpGatewayConfigUpdateSettingsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(gatewayConfigUpdateApi),
    })
}

export const getMcpGatewayMembersListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_gateway/members/`
}

/**
 * Admin overview of each member's gateway posture, plus the per-member
 * server kill switch.
 */
export const mcpGatewayMembersList = async (
    projectId: string,
    options?: RequestInit
): Promise<GatewayMemberSummaryApi[]> => {
    return apiMutator<GatewayMemberSummaryApi[]>(getMcpGatewayMembersListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMcpGatewayMembersSetAccessCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/members/${id}/set_access/`
}

/**
 * Turn one gateway server off (or back on) for one member.
 */
export const mcpGatewayMembersSetAccessCreate = async (
    projectId: string,
    id: string,
    memberAccessUpdateApi: MemberAccessUpdateApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMcpGatewayMembersSetAccessCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(memberAccessUpdateApi),
    })
}

export const getMcpGatewayRulesListUrl = (projectId: string, params?: McpGatewayRulesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_gateway/rules/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_gateway/rules/`
}

/**
 * Team guardrails evaluated before any scope policy.
 */
export const mcpGatewayRulesList = async (
    projectId: string,
    params?: McpGatewayRulesListParams,
    options?: RequestInit
): Promise<PaginatedMCPOrgRuleListApi> => {
    return apiMutator<PaginatedMCPOrgRuleListApi>(getMcpGatewayRulesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMcpGatewayRulesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_gateway/rules/`
}

/**
 * Team guardrails evaluated before any scope policy.
 */
export const mcpGatewayRulesCreate = async (
    projectId: string,
    mCPOrgRuleApi: NonReadonly<MCPOrgRuleApi>,
    options?: RequestInit
): Promise<MCPOrgRuleApi> => {
    return apiMutator<MCPOrgRuleApi>(getMcpGatewayRulesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mCPOrgRuleApi),
    })
}

export const getMcpGatewayRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/rules/${id}/`
}

/**
 * Team guardrails evaluated before any scope policy.
 */
export const mcpGatewayRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MCPOrgRuleApi> => {
    return apiMutator<MCPOrgRuleApi>(getMcpGatewayRulesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getMcpGatewayRulesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/rules/${id}/`
}

/**
 * Team guardrails evaluated before any scope policy.
 */
export const mcpGatewayRulesUpdate = async (
    projectId: string,
    id: string,
    mCPOrgRuleApi: NonReadonly<MCPOrgRuleApi>,
    options?: RequestInit
): Promise<MCPOrgRuleApi> => {
    return apiMutator<MCPOrgRuleApi>(getMcpGatewayRulesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mCPOrgRuleApi),
    })
}

export const getMcpGatewayRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/rules/${id}/`
}

/**
 * Team guardrails evaluated before any scope policy.
 */
export const mcpGatewayRulesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedMCPOrgRuleApi?: NonReadonly<PatchedMCPOrgRuleApi>,
    options?: RequestInit
): Promise<MCPOrgRuleApi> => {
    return apiMutator<MCPOrgRuleApi>(getMcpGatewayRulesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedMCPOrgRuleApi),
    })
}

export const getMcpGatewayRulesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/rules/${id}/`
}

/**
 * Team guardrails evaluated before any scope policy.
 */
export const mcpGatewayRulesDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getMcpGatewayRulesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getMcpGatewayServersListUrl = (projectId: string, params?: McpGatewayServersListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_gateway/servers/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_gateway/servers/`
}

/**
 * The team's gateway server registry. Registration happens through the
 * install/share flows in views.py — this surface reads, tunes, and removes.
 */
export const mcpGatewayServersList = async (
    projectId: string,
    params?: McpGatewayServersListParams,
    options?: RequestInit
): Promise<PaginatedMCPGatewayServerListApi> => {
    return apiMutator<PaginatedMCPGatewayServerListApi>(getMcpGatewayServersListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMcpGatewayServersRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/servers/${id}/`
}

/**
 * The team's gateway server registry. Registration happens through the
 * install/share flows in views.py — this surface reads, tunes, and removes.
 */
export const mcpGatewayServersRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MCPGatewayServerApi> => {
    return apiMutator<MCPGatewayServerApi>(getMcpGatewayServersRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getMcpGatewayServersUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/servers/${id}/`
}

/**
 * The team's gateway server registry. Registration happens through the
 * install/share flows in views.py — this surface reads, tunes, and removes.
 */
export const mcpGatewayServersUpdate = async (
    projectId: string,
    id: string,
    mCPGatewayServerUpdateApi?: MCPGatewayServerUpdateApi,
    options?: RequestInit
): Promise<MCPGatewayServerUpdateApi> => {
    return apiMutator<MCPGatewayServerUpdateApi>(getMcpGatewayServersUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mCPGatewayServerUpdateApi),
    })
}

export const getMcpGatewayServersPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/servers/${id}/`
}

/**
 * The team's gateway server registry. Registration happens through the
 * install/share flows in views.py — this surface reads, tunes, and removes.
 */
export const mcpGatewayServersPartialUpdate = async (
    projectId: string,
    id: string,
    patchedMCPGatewayServerUpdateApi?: PatchedMCPGatewayServerUpdateApi,
    options?: RequestInit
): Promise<MCPGatewayServerUpdateApi> => {
    return apiMutator<MCPGatewayServerUpdateApi>(getMcpGatewayServersPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedMCPGatewayServerUpdateApi),
    })
}

export const getMcpGatewayServersDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/servers/${id}/`
}

/**
 * The team's gateway server registry. Registration happens through the
 * install/share flows in views.py — this surface reads, tunes, and removes.
 */
export const mcpGatewayServersDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getMcpGatewayServersDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getMcpGatewayServersPoliciesCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/servers/${id}/policies/`
}

/**
 * Upsert per-tool states for a scope, returning the re-resolved catalog.
 */
export const mcpGatewayServersPoliciesCreate = async (
    projectId: string,
    id: string,
    gatewayPoliciesUpsertApi: GatewayPoliciesUpsertApi,
    options?: RequestInit
): Promise<PaginatedResolvedToolPolicyListApi> => {
    return apiMutator<PaginatedResolvedToolPolicyListApi>(getMcpGatewayServersPoliciesCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(gatewayPoliciesUpsertApi),
    })
}

export const getMcpGatewayServersToolsRetrieveUrl = (
    projectId: string,
    id: string,
    params?: McpGatewayServersToolsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_gateway/servers/${id}/tools/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_gateway/servers/${id}/tools/`
}

/**
 * Tool catalog with the resolved policy for a scope.
 */
export const mcpGatewayServersToolsRetrieve = async (
    projectId: string,
    id: string,
    params?: McpGatewayServersToolsRetrieveParams,
    options?: RequestInit
): Promise<PaginatedResolvedToolPolicyListApi> => {
    return apiMutator<PaginatedResolvedToolPolicyListApi>(getMcpGatewayServersToolsRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getMcpGatewayServiceAccountsListUrl = (
    projectId: string,
    params?: McpGatewayServiceAccountsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_gateway/service_accounts/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_gateway/service_accounts/`
}

/**
 * Agent identities: creation mints a bearer token (shown once), access
 * grants tie them to gateway servers. Reads are open to members so agent
 * activity stays legible; every write is admin-only.
 */
export const mcpGatewayServiceAccountsList = async (
    projectId: string,
    params?: McpGatewayServiceAccountsListParams,
    options?: RequestInit
): Promise<PaginatedMCPServiceAccountListApi> => {
    return apiMutator<PaginatedMCPServiceAccountListApi>(getMcpGatewayServiceAccountsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMcpGatewayServiceAccountsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/mcp_gateway/service_accounts/`
}

/**
 * Create an agent and mint its gateway token (returned exactly once).
 */
export const mcpGatewayServiceAccountsCreate = async (
    projectId: string,
    mCPServiceAccountCreateApi: MCPServiceAccountCreateApi,
    options?: RequestInit
): Promise<MCPServiceAccountWithTokenApi> => {
    return apiMutator<MCPServiceAccountWithTokenApi>(getMcpGatewayServiceAccountsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mCPServiceAccountCreateApi),
    })
}

export const getMcpGatewayServiceAccountsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/service_accounts/${id}/`
}

/**
 * Agent identities: creation mints a bearer token (shown once), access
 * grants tie them to gateway servers. Reads are open to members so agent
 * activity stays legible; every write is admin-only.
 */
export const mcpGatewayServiceAccountsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MCPServiceAccountApi> => {
    return apiMutator<MCPServiceAccountApi>(getMcpGatewayServiceAccountsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getMcpGatewayServiceAccountsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/service_accounts/${id}/`
}

/**
 * Agent identities: creation mints a bearer token (shown once), access
 * grants tie them to gateway servers. Reads are open to members so agent
 * activity stays legible; every write is admin-only.
 */
export const mcpGatewayServiceAccountsUpdate = async (
    projectId: string,
    id: string,
    mCPServiceAccountUpdateApi?: MCPServiceAccountUpdateApi,
    options?: RequestInit
): Promise<MCPServiceAccountUpdateApi> => {
    return apiMutator<MCPServiceAccountUpdateApi>(getMcpGatewayServiceAccountsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mCPServiceAccountUpdateApi),
    })
}

export const getMcpGatewayServiceAccountsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/service_accounts/${id}/`
}

/**
 * Agent identities: creation mints a bearer token (shown once), access
 * grants tie them to gateway servers. Reads are open to members so agent
 * activity stays legible; every write is admin-only.
 */
export const mcpGatewayServiceAccountsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedMCPServiceAccountUpdateApi?: PatchedMCPServiceAccountUpdateApi,
    options?: RequestInit
): Promise<MCPServiceAccountUpdateApi> => {
    return apiMutator<MCPServiceAccountUpdateApi>(getMcpGatewayServiceAccountsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedMCPServiceAccountUpdateApi),
    })
}

export const getMcpGatewayServiceAccountsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/service_accounts/${id}/`
}

/**
 * Agent identities: creation mints a bearer token (shown once), access
 * grants tie them to gateway servers. Reads are open to members so agent
 * activity stays legible; every write is admin-only.
 */
export const mcpGatewayServiceAccountsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getMcpGatewayServiceAccountsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getMcpGatewayServiceAccountsAccessCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/service_accounts/${id}/access/`
}

/**
 * Grant or revoke this agent's access to one gateway server.
 */
export const mcpGatewayServiceAccountsAccessCreate = async (
    projectId: string,
    id: string,
    serviceAccountAccessUpdateApi: ServiceAccountAccessUpdateApi,
    options?: RequestInit
): Promise<MCPServiceAccountApi> => {
    return apiMutator<MCPServiceAccountApi>(getMcpGatewayServiceAccountsAccessCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(serviceAccountAccessUpdateApi),
    })
}

export const getMcpGatewayServiceAccountsRotateTokenCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_gateway/service_accounts/${id}/rotate_token/`
}

/**
 * Mint a new token; the previous one stops working immediately.
 */
export const mcpGatewayServiceAccountsRotateTokenCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MCPServiceAccountWithTokenApi> => {
    return apiMutator<MCPServiceAccountWithTokenApi>(getMcpGatewayServiceAccountsRotateTokenCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getMcpServerInstallationsListUrl = (projectId: string, params?: McpServerInstallationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_server_installations/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_server_installations/`
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
    return `/api/projects/${projectId}/mcp_server_installations/`
}

export const mcpServerInstallationsCreate = async (
    projectId: string,
    mCPServerInstallationApi?: NonReadonly<MCPServerInstallationApi>,
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
    return `/api/projects/${projectId}/mcp_server_installations/${id}/`
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
    return `/api/projects/${projectId}/mcp_server_installations/${id}/`
}

export const mcpServerInstallationsUpdate = async (
    projectId: string,
    id: string,
    mCPServerInstallationApi?: NonReadonly<MCPServerInstallationApi>,
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
    return `/api/projects/${projectId}/mcp_server_installations/${id}/`
}

export const mcpServerInstallationsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedMCPServerInstallationUpdateApi?: PatchedMCPServerInstallationUpdateApi,
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
    return `/api/projects/${projectId}/mcp_server_installations/${id}/`
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
    return `/api/projects/${projectId}/mcp_server_installations/${id}/proxy/`
}

export const mcpServerInstallationsProxyCreate = async (
    projectId: string,
    id: string,
    mCPServerInstallationApi?: NonReadonly<MCPServerInstallationApi>,
    options?: RequestInit
): Promise<MCPServerInstallationApi> => {
    return apiMutator<MCPServerInstallationApi>(getMcpServerInstallationsProxyCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mCPServerInstallationApi),
    })
}

export const getMcpServerInstallationsShareCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_server_installations/${id}/share/`
}

/**
 * Escalate a personal installation to a team-wide shared one.
 *
 * Owner-only AND admin-only: sharing exposes the owner's credential to
 * every project member and all autonomous agents, so it carries the same
 * gate as creating a shared install outright.
 */
export const mcpServerInstallationsShareCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MCPServerInstallationApi> => {
    return apiMutator<MCPServerInstallationApi>(getMcpServerInstallationsShareCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getMcpServerInstallationsToolsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_server_installations/${id}/tools/`
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
    return `/api/projects/${projectId}/mcp_server_installations/${id}/tools/${toolName}/`
}

export const mcpServerInstallationsToolsPartialUpdate = async (
    projectId: string,
    id: string,
    toolName: string,
    patchedToolApprovalUpdateApi?: PatchedToolApprovalUpdateApi,
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
    return `/api/projects/${projectId}/mcp_server_installations/${id}/tools/refresh/`
}

export const mcpServerInstallationsToolsRefreshCreate = async (
    projectId: string,
    id: string,
    mCPServerInstallationApi?: NonReadonly<MCPServerInstallationApi>,
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

export const getMcpServerInstallationsUnshareCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/mcp_server_installations/${id}/unshare/`
}

/**
 * De-escalate a shared installation back to personal.
 *
 * Allowed for the credential owner OR a project admin (the reclaim path
 * for shared credentials). The row always stays owned by the ORIGINAL
 * owner — an admin unsharing someone else's install must not capture
 * their credential.
 */
export const mcpServerInstallationsUnshareCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MCPServerInstallationApi> => {
    return apiMutator<MCPServerInstallationApi>(getMcpServerInstallationsUnshareCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getMcpServerInstallationsAuthorizeRetrieveUrl = (
    projectId: string,
    params?: McpServerInstallationsAuthorizeRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_server_installations/authorize/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_server_installations/authorize/`
}

/**
 * Start (or re-start) an OAuth flow.
 *
 * Pass ``template_id`` to (re)connect a catalog template, or
 * ``installation_id`` to reconnect an existing custom install using its
 * cached metadata and per-user DCR creds.
 */
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
    return `/api/projects/${projectId}/mcp_server_installations/install_custom/`
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
    return `/api/projects/${projectId}/mcp_server_installations/install_template/`
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

export const getMcpServersListUrl = (projectId: string, params?: McpServersListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/mcp_servers/?${stringifiedParams}`
        : `/api/projects/${projectId}/mcp_servers/`
}

/**
 * Lists curated MCP server templates that users can install with one click.
 *
 * Templates are seeded by PostHog operators and carry shared, encrypted
 * OAuth client credentials. Inactive templates are hidden from the catalog.
 */
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
