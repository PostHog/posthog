import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { fromParamsGivenUrl } from 'lib/utils'

import type { mcpStoreLogicType } from './mcpStoreLogicType'

export interface MCPServer {
    id: string
    name: string
    url: string
    description: string
    icon_url: string
    auth_type: 'none' | 'api_key' | 'oauth'
    is_default: boolean
    created_at: string
    updated_at: string
    created_by: Record<string, any> | null
}

export interface MCPServerInstallation {
    id: string
    server: MCPServer | null
    name: string
    display_name: string
    url: string
    description: string
    auth_type: 'none' | 'api_key' | 'oauth'
    configuration: Record<string, any>
    needs_reauth: boolean
    pending_oauth: boolean
    created_at: string
    updated_at: string
}

export const mcpStoreLogic = kea<mcpStoreLogicType>([
    path(['products', 'mcp_store', 'frontend', 'mcpStoreLogic']),

    actions({
        openAddCustomServerModal: true,
        closeAddCustomServerModal: true,
        setConfiguringServerId: (serverId: string | null) => ({ serverId }),
    }),

    reducers({
        addCustomServerModalVisible: [
            false,
            {
                openAddCustomServerModal: () => true,
                closeAddCustomServerModal: () => false,
            },
        ],
        configuringServerId: [
            null as string | null,
            {
                setConfiguringServerId: (_, { serverId }) => serverId,
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        servers: [
            [] as MCPServer[],
            {
                loadServers: async () => {
                    const response = await api.mcpServers.list()
                    return response.results
                },
            },
        ],
        installations: [
            [] as MCPServerInstallation[],
            {
                loadInstallations: async () => {
                    const response = await api.mcpServerInstallations.list()
                    return response.results
                },
                installServer: async ({
                    serverId,
                    configuration,
                }: {
                    serverId: string
                    configuration?: Record<string, any>
                }) => {
                    const installation = await api.mcpServerInstallations.create({
                        server_id: serverId,
                        ...(configuration ? { configuration } : {}),
                    })
                    lemonToast.success('Server installed')
                    actions.setConfiguringServerId(null)
                    return [...values.installations, installation]
                },
                uninstallServer: async (installationId: string) => {
                    await api.mcpServerInstallations.delete(installationId)
                    lemonToast.success('Server uninstalled')
                    return values.installations.filter((i: MCPServerInstallation) => i.id !== installationId)
                },
                completeOAuthInstall: async ({
                    code,
                    serverId,
                    stateToken,
                    mcpUrl,
                    displayName,
                    description,
                }: {
                    code: string
                    serverId: string
                    stateToken: string
                    mcpUrl?: string
                    displayName?: string
                    description?: string
                }) => {
                    try {
                        const installation = await api.mcpServerInstallations.oauthCallback({
                            code,
                            server_id: serverId,
                            state_token: stateToken,
                            mcp_url: mcpUrl || '',
                            display_name: displayName || '',
                            description: description || '',
                        })
                        lemonToast.success('Server connected')
                        actions.loadServers()
                        const existing = values.installations.find(
                            (i: MCPServerInstallation) => i.id === installation.id
                        )
                        if (existing) {
                            return values.installations.map((i: MCPServerInstallation) =>
                                i.id === installation.id ? installation : i
                            )
                        }
                        return [...values.installations, installation]
                    } catch (e: any) {
                        lemonToast.error(e.detail || 'Failed to complete OAuth connection')
                        throw e
                    }
                },
            },
        ],
    })),

    selectors({
        installedServerIds: [
            (s) => [s.installations],
            (installations: MCPServerInstallation[]): Set<string> =>
                new Set(installations.filter((i) => i.server).map((i) => i.server!.id)),
        ],
        installedServerUrls: [
            (s) => [s.installations],
            (installations: MCPServerInstallation[]): Set<string> => new Set(installations.map((i) => i.url)),
        ],
        recommendedServers: [
            (s) => [s.servers, s.installedServerIds],
            (servers: MCPServer[], installedServerIds: Set<string>): MCPServer[] =>
                servers.filter((s) => !installedServerIds.has(s.id)),
        ],
    }),

    urlToAction(({ actions }) => ({
        '/mcp-store': (_, searchParams) => {
            const { code, state, server_id, state_token } = searchParams
            if (code && state) {
                const parsed = fromParamsGivenUrl(`?${state}`)
                actions.completeOAuthInstall({
                    code,
                    serverId: parsed.server_id,
                    stateToken: parsed.token,
                    mcpUrl: parsed.mcp_url,
                    displayName: parsed.display_name,
                    description: parsed.description,
                })
                router.actions.replace('/mcp-store')
            } else if (code && server_id) {
                actions.completeOAuthInstall({ code, serverId: server_id, stateToken: state_token })
                router.actions.replace('/mcp-store')
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadServers()
        actions.loadInstallations()
    }),
])
