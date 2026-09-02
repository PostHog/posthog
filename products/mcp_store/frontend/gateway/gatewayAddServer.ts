import type { InstallCustomApi, MCPAgentGrantScopeEnumApi } from '../generated/api.schemas'

export interface GatewayAddServerValues {
    name: string
    url: string
    description: string
    authType: InstallCustomApi['auth_type']
    apiKey: string
    clientId: string
    clientSecret: string
    teamEnabled: boolean
    agentScope: MCPAgentGrantScopeEnumApi
}

export const GATEWAY_ADD_SERVER_DEFAULTS: GatewayAddServerValues = {
    name: '',
    url: '',
    description: '',
    authType: 'oauth',
    apiKey: '',
    clientId: '',
    clientSecret: '',
    teamEnabled: true,
    agentScope: 'personal',
}

export function isValidMcpUrl(url: string): boolean {
    try {
        const parsedUrl = new URL(url.trim())
        const usesHttp = parsedUrl.protocol === 'http:' || parsedUrl.protocol === 'https:'
        const hostname = parsedUrl.hostname
        const isIpv6Address = hostname.startsWith('[') && hostname.endsWith(']') && hostname.length > 2
        const hasValidHostname =
            isIpv6Address || hostname.split('.').every((label) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label))

        return usesHttp && Boolean(hostname) && hasValidHostname
    } catch {
        return false
    }
}

export function canSubmitGatewayServer(values: Pick<GatewayAddServerValues, 'name' | 'url'>): boolean {
    return values.name.trim() !== '' && isValidMcpUrl(values.url)
}

export function buildGatewayInstallRequest(
    values: GatewayAddServerValues,
    options: { isAdmin: boolean; canManageAgentAccess: boolean }
): InstallCustomApi {
    return {
        name: values.name.trim(),
        url: values.url.trim(),
        description: values.description.trim(),
        auth_type: values.authType,
        ...(values.authType === 'api_key' && values.apiKey.trim() ? { api_key: values.apiKey.trim() } : {}),
        ...(values.authType === 'oauth' && values.clientId.trim() ? { client_id: values.clientId.trim() } : {}),
        ...(values.authType === 'oauth' && values.clientSecret.trim()
            ? { client_secret: values.clientSecret.trim() }
            : {}),
        ...(options.isAdmin ? { team_enabled: values.teamEnabled } : {}),
        ...(options.canManageAgentAccess ? { agent_scope: values.agentScope } : {}),
    }
}
