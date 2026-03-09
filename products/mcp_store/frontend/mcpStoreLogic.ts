import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { MCPServerInstallationApi, RecommendedServerApi } from './generated/api.schemas'
import type { mcpStoreLogicType } from './mcpStoreLogicType'

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
        toggleServerEnabled: ({ id, enabled }: { id: string; enabled: boolean }) => ({ id, enabled }),
        setInstallations: (installations: MCPServerInstallationApi[]) => ({ installations }),
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
        installations: [
            [] as MCPServerInstallationApi[],
            {
                toggleServerEnabled: (
                    state: MCPServerInstallationApi[],
                    { id, enabled }: { id: string; enabled: boolean }
                ) => state.map((i) => (i.id === id ? { ...i, is_enabled: enabled } : i)),
                setInstallations: (
                    _state: MCPServerInstallationApi[],
                    { installations }: { installations: MCPServerInstallationApi[] }
                ) => installations,
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

    loaders(({ values }) => ({
        servers: [
            [] as RecommendedServerApi[],
            {
                loadServers: async () => {
                    const response = await api.mcpServers.list()
                    return response.results as RecommendedServerApi[]
                },
            },
        ],
        installations: [
            [] as MCPServerInstallationApi[],
            {
                loadInstallations: async () => {
                    const response = await api.mcpServerInstallations.list()
                    return response.results as MCPServerInstallationApi[]
                },
                updateInstallation: async ({ id, data }: { id: string; data: Record<string, any> }) => {
                    const updated = (await api.mcpServerInstallations.update(id, data)) as MCPServerInstallationApi
                    lemonToast.success('Server updated')
                    return values.installations.map((i: MCPServerInstallationApi) =>
                        i.id === updated.id ? updated : i
                    )
                },
                uninstallServer: async (installationId: string) => {
                    await api.mcpServerInstallations.delete(installationId)
                    lemonToast.success('Server uninstalled')
                    return values.installations.filter((i: MCPServerInstallationApi) => i.id !== installationId)
                },
            },
        ],
    })),

    selectors({
        installedServerIds: [
            (s) => [s.installations],
            (installations: MCPServerInstallationApi[]): Set<string> =>
                new Set(installations.filter((i) => i.server_id).map((i) => i.server_id!)),
        ],
        installedServerUrls: [
            (s) => [s.installations],
            (installations: MCPServerInstallationApi[]): Set<string> =>
                new Set(installations.map((i) => i.url).filter((url): url is string => !!url)),
        ],
        recommendedServers: [(s) => [s.servers], (servers: RecommendedServerApi[]): RecommendedServerApi[] => servers],
    }),

    listeners(({ actions, values }) => ({
        toggleServerEnabled: async ({ id, enabled }) => {
            try {
                await api.mcpServerInstallations.update(id, { is_enabled: enabled })
            } catch (e: any) {
                lemonToast.error(e.detail || 'Failed to update server')
                actions.setInstallations(
                    values.installations.map((i: MCPServerInstallationApi) =>
                        i.id === id ? { ...i, is_enabled: !enabled } : i
                    )
                )
            }
        },
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
            if (searchParams.oauth_complete === 'true') {
                lemonToast.success('Server connected')
                actions.loadInstallations()
                actions.loadServers()
                router.actions.replace('/settings/mcp-servers')
            } else if (searchParams.oauth_error) {
                lemonToast.error('OAuth authorization failed')
                router.actions.replace('/settings/mcp-servers')
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadServers()
        actions.loadInstallations()
    }),
])
