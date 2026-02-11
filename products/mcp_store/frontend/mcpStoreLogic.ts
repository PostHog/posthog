import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

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
    server: MCPServer
    configuration: Record<string, any>
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
                    return values.installations.filter((i) => i.id !== installationId)
                },
            },
        ],
    })),

    selectors({
        installedServerIds: [
            (s) => [s.installations],
            (installations: MCPServerInstallation[]): Set<string> => new Set(installations.map((i) => i.server.id)),
        ],
        recommendedServers: [
            (s) => [s.servers, s.installedServerIds],
            (servers: MCPServer[], installedServerIds: Set<string>): MCPServer[] =>
                servers.filter((s) => s.is_default && !installedServerIds.has(s.id)),
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadServers()
        actions.loadInstallations()
    }),
])
