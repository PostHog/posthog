import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { fromParamsGivenUrl } from 'lib/utils'

import type { mcpStoreLogicType } from './mcpStoreLogicType'

export interface RecommendedServer {
    name: string
    url: string
    description: string
    icon_url: string
    auth_type: 'none' | 'api_key' | 'oauth'
    oauth_provider_kind?: string
}

export interface MCPServerInstallation {
    id: string
    server_id: string | null
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
    }),

    reducers({
        addCustomServerModalVisible: [
            false,
            {
                openAddCustomServerModal: () => true,
                closeAddCustomServerModal: () => false,
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        servers: [
            [] as RecommendedServer[],
            {
                loadServers: async () => {
                    const response = await api.mcpServers.list()
                    return response.results as RecommendedServer[]
                },
            },
        ],
        installations: [
            [] as MCPServerInstallation[],
            {
                loadInstallations: async () => {
                    const response = await api.mcpServerInstallations.list()
                    return response.results as MCPServerInstallation[]
                },
                updateInstallation: async ({ id, data }: { id: string; data: Record<string, any> }) => {
                    const updated = (await api.mcpServerInstallations.update(id, data)) as MCPServerInstallation
                    lemonToast.success('Server updated')
                    return values.installations.map((i: MCPServerInstallation) => (i.id === updated.id ? updated : i))
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
                        const installation = (await api.mcpServerInstallations.oauthCallback({
                            code,
                            server_id: serverId,
                            state_token: stateToken,
                            mcp_url: mcpUrl || '',
                            display_name: displayName || '',
                            description: description || '',
                        })) as MCPServerInstallation
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
                new Set(installations.filter((i) => i.server_id).map((i) => i.server_id!)),
        ],
        installedServerUrls: [
            (s) => [s.installations],
            (installations: MCPServerInstallation[]): Set<string> => new Set(installations.map((i) => i.url)),
        ],
        recommendedServers: [(s) => [s.servers], (servers: RecommendedServer[]): RecommendedServer[] => servers],
    }),

    urlToAction(({ actions }) => ({
        '/settings/mcp-servers': (_, searchParams) => {
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
                router.actions.replace('/settings/mcp-servers')
            } else if (code && server_id) {
                actions.completeOAuthInstall({ code, serverId: server_id, stateToken: state_token })
                router.actions.replace('/settings/mcp-servers')
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadServers()
        actions.loadInstallations()
    }),
])
