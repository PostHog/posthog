import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type {
    MCPServerInstallationApi,
    MCPServerInstallationToolApi,
    MCPServerTemplateApi,
} from './generated/api.schemas'
import type { mcpStoreLogicType } from './mcpStoreLogicType'

export type ToolApprovalState = 'approved' | 'needs_approval' | 'do_not_use'

export interface CustomServerFormValues {
    name: string
    url: string
    description: string
    auth_type: string
    api_key: string
    client_id: string
    client_secret: string
    // Set when the modal is opened from a template (api_key templates reuse
    // the same modal to collect the key). Empty for truly custom installs.
    template_id: string
}

const CUSTOM_SERVER_FORM_DEFAULTS: CustomServerFormValues = {
    name: '',
    url: '',
    description: '',
    auth_type: 'oauth',
    api_key: '',
    client_id: '',
    client_secret: '',
    template_id: '',
}

export const mcpStoreLogic = kea<mcpStoreLogicType>([
    path(['products', 'mcp_store', 'frontend', 'mcpStoreLogic']),

    actions({
        openAddCustomServerModal: true,
        openAddCustomServerModalWithDefaults: (defaults: Partial<CustomServerFormValues>) => ({ defaults }),
        closeAddCustomServerModal: true,
        toggleServerEnabled: ({ id, enabled }: { id: string; enabled: boolean }) => ({ id, enabled }),
        setInstallations: (installations: MCPServerInstallationApi[]) => ({ installations }),
        installTemplate: ({ templateId }: { templateId: string }) => ({ templateId }),
        loadInstallationTools: ({ installationId }: { installationId: string }) => ({ installationId }),
        refreshInstallationTools: ({ installationId }: { installationId: string }) => ({ installationId }),
        setToolApprovalState: ({
            installationId,
            toolName,
            approvalState,
        }: {
            installationId: string
            toolName: string
            approvalState: ToolApprovalState
        }) => ({ installationId, toolName, approvalState }),
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
        installationTools: [
            {} as Record<string, MCPServerInstallationToolApi[]>,
            {
                setToolApprovalState: (
                    state: Record<string, MCPServerInstallationToolApi[]>,
                    {
                        installationId,
                        toolName,
                        approvalState,
                    }: { installationId: string; toolName: string; approvalState: ToolApprovalState }
                ) => {
                    const existing = state[installationId]
                    if (!existing) {
                        return state
                    }
                    return {
                        ...state,
                        [installationId]: existing.map((tool) =>
                            tool.tool_name === toolName ? { ...tool, approval_state: approvalState } : tool
                        ),
                    }
                },
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
            submit: async ({ name, url, description, auth_type, api_key, client_id, client_secret, template_id }) => {
                try {
                    const result = template_id
                        ? await api.mcpServerInstallations.installTemplate({
                              template_id,
                              api_key: api_key || undefined,
                          })
                        : await api.mcpServerInstallations.installCustom({
                              name,
                              url,
                              auth_type,
                              api_key,
                              description,
                              // Optional per-installation OAuth credentials; the backend
                              // falls back to DCR when both are empty.
                              client_id: client_id || undefined,
                              client_secret: client_secret || undefined,
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
            [] as MCPServerTemplateApi[],
            {
                loadServers: async () => {
                    const response = await api.mcpServers.list()
                    return response.results as MCPServerTemplateApi[]
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
        installationTools: [
            {} as Record<string, MCPServerInstallationToolApi[]>,
            {
                loadInstallationTools: async ({ installationId }) => {
                    const response = await api.mcpServerInstallations.listTools(installationId)
                    return {
                        ...values.installationTools,
                        [installationId]: response.results as MCPServerInstallationToolApi[],
                    }
                },
                refreshInstallationTools: async ({ installationId }) => {
                    try {
                        const response = await api.mcpServerInstallations.refreshTools(installationId)
                        lemonToast.success('Tools refreshed')
                        return {
                            ...values.installationTools,
                            [installationId]: response.results as MCPServerInstallationToolApi[],
                        }
                    } catch (e: any) {
                        lemonToast.error(e.detail || 'Failed to refresh tools')
                        throw e
                    }
                },
            },
        ],
    })),

    selectors({
        installedTemplateIds: [
            (s) => [s.installations],
            (installations: MCPServerInstallationApi[]): Set<string> =>
                new Set(installations.map((i) => i.template_id).filter((id): id is string => !!id)),
        ],
        installedServerUrls: [
            (s) => [s.installations],
            (installations: MCPServerInstallationApi[]): Set<string> =>
                new Set(installations.map((i) => i.url).filter((url): url is string => !!url)),
        ],
        recommendedServers: [(s) => [s.servers], (servers: MCPServerTemplateApi[]): MCPServerTemplateApi[] => servers],
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
        installTemplate: async ({ templateId }) => {
            try {
                const result = await api.mcpServerInstallations.installTemplate({ template_id: templateId })
                if (result?.redirect_url) {
                    window.location.href = result.redirect_url
                    return
                }
                lemonToast.success('Server installed')
                actions.loadInstallations()
            } catch (e: any) {
                lemonToast.error(e.detail || 'Failed to install server')
            }
        },
        setToolApprovalState: async ({ installationId, toolName, approvalState }) => {
            // Optimistic update already applied in the reducer. Reload from server on failure.
            try {
                await api.mcpServerInstallations.updateToolApproval(installationId, toolName, approvalState)
            } catch (e: any) {
                lemonToast.error(e.detail || 'Failed to update tool approval')
                actions.loadInstallationTools({ installationId })
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
            if (name === 'auth_type' && value !== 'oauth') {
                if (values.customServerForm.client_id) {
                    actions.setCustomServerFormValue('client_id', '')
                }
                if (values.customServerForm.client_secret) {
                    actions.setCustomServerFormValue('client_secret', '')
                }
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
