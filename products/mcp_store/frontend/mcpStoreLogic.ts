import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
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
    auth_type: 'api_key' | 'oauth'
    oauth_provider_kind?: string
}

export interface MCPServerInstallation {
    id: string
    server_id: string | null
    name: string
    display_name: string
    url: string
    description: string
    auth_type: 'api_key' | 'oauth'
    needs_reauth: boolean
    pending_oauth: boolean
    created_at: string
    updated_at: string
}

export interface CustomServerFormValues {
    name: string
    url: string
    description: string
    auth_type: string
    api_key: string
}

const CUSTOM_SERVER_FORM_DEFAULTS: CustomServerFormValues = {
    name: '',
    url: '',
    description: '',
    auth_type: 'oauth',
    api_key: '',
}

export const mcpStoreLogic = kea<mcpStoreLogicType>([
    path(['products', 'mcp_store', 'frontend', 'mcpStoreLogic']),

    actions({
        openAddCustomServerModal: true,
        openAddCustomServerModalWithDefaults: (defaults: Partial<CustomServerFormValues>) => ({ defaults }),
        closeAddCustomServerModal: true,
    }),

    reducers({
        addCustomServerModalVisible: [
            false,
            {
                openAddCustomServerModal: () => true,
                openAddCustomServerModalWithDefaults: () => true,
                closeAddCustomServerModal: () => false,
            },
        ],
        customServerFormPrefilled: [
            false,
            {
                openAddCustomServerModalWithDefaults: () => true,
                openAddCustomServerModal: () => false,
                closeAddCustomServerModal: () => false,
            },
        ],
    }),

    forms(({ actions }) => ({
        customServerForm: {
            defaults: CUSTOM_SERVER_FORM_DEFAULTS,
            errors: ({ name, url }) => ({
                name: !name ? 'Name is required' : undefined,
                url: !url ? 'URL is required' : undefined,
            }),
            submit: async ({ name, url, description, auth_type, api_key }) => {
                try {
                    const result = await api.mcpServerInstallations.installCustom({
                        name,
                        url,
                        auth_type,
                        api_key,
                        description,
                    })
                    if (result?.redirect_url) {
                        window.location.href = result.redirect_url
                        return
                    }
                    lemonToast.success('Server added and installed')
                    actions.loadInstallations()
                    actions.closeAddCustomServerModal()
                } catch (e: any) {
                    if (e.status === 302 || e.detail?.includes?.('redirect')) {
                        return
                    }
                    lemonToast.error(e.detail || 'Failed to add server')
                    throw e
                }
            },
        },
    })),

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
                }: {
                    code: string
                    serverId: string
                    stateToken: string
                }) => {
                    try {
                        const installation = (await api.mcpServerInstallations.oauthCallback({
                            code,
                            server_id: serverId,
                            state_token: stateToken,
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

    listeners(({ actions, values }) => ({
        openAddCustomServerModalWithDefaults: ({ defaults }) => {
            actions.resetCustomServerForm()
            for (const [key, value] of Object.entries(defaults)) {
                actions.setCustomServerFormValue(key as keyof CustomServerFormValues, value)
            }
        },
        closeAddCustomServerModal: () => {
            actions.resetCustomServerForm()
        },
        setCustomServerFormValue: ({ name, value }) => {
            if (name === 'auth_type' && value !== 'api_key' && values.customServerForm.api_key) {
                actions.setCustomServerFormValue('api_key', '')
            }
        },
    })),

    urlToAction(({ actions }) => ({
        '/settings/mcp-servers': (_, searchParams) => {
            const { code, state, server_id, state_token } = searchParams
            if (code && state) {
                const parsed = fromParamsGivenUrl(`?${state}`)
                actions.completeOAuthInstall({
                    code,
                    serverId: parsed.server_id,
                    stateToken: parsed.token,
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
