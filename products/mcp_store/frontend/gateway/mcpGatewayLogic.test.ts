import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { lemonToast } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    mcpGatewayConfigApplyPresetCreate,
    mcpGatewayConfigList,
    mcpGatewayConfigSetAllServersEnabledCreate,
    mcpGatewayMembersList,
    mcpGatewayRulesList,
    mcpGatewayServersList,
    mcpGatewayServersPartialUpdate,
    mcpGatewayServersSetTemplateEnabledCreate,
    mcpGatewayServiceAccountsAccessCreate,
    mcpGatewayServiceAccountsList,
    mcpServerInstallationsInstallCustomCreate,
    mcpServerInstallationsInstallTemplateCreate,
    mcpServerInstallationsToolsRefreshCreate,
    mcpServersList,
} from '../generated/api'
import type {
    GatewayMemberSummaryApi,
    MCPAgentGrantScopeEnumApi,
    MCPGatewayServerApi,
    MCPServerInstallationApi,
    MCPServerTemplateApi,
    MCPServiceAccountApi,
    UserBasicApi,
} from '../generated/api.schemas'
import { GATEWAY_MEMBERS_PAGE_SIZE, mcpGatewayLogic } from './mcpGatewayLogic'

const YOU: UserBasicApi = {
    id: MOCK_DEFAULT_USER.id,
    uuid: MOCK_DEFAULT_USER.uuid,
    email: MOCK_DEFAULT_USER.email,
    hedgehog_config: null,
}

jest.mock('../generated/api', () => ({
    mcpGatewayConfigApplyPresetCreate: jest.fn(),
    mcpGatewayConfigList: jest.fn(),
    mcpGatewayConfigSetAllServersEnabledCreate: jest.fn(),
    mcpGatewayMembersList: jest.fn(),
    mcpGatewayRulesList: jest.fn(),
    mcpGatewayServersList: jest.fn(),
    mcpGatewayServersPartialUpdate: jest.fn(),
    mcpGatewayServersSetTemplateEnabledCreate: jest.fn(),
    mcpGatewayServiceAccountsAccessCreate: jest.fn(),
    mcpGatewayServiceAccountsList: jest.fn(),
    mcpServerInstallationsInstallCustomCreate: jest.fn(),
    mcpServerInstallationsInstallTemplateCreate: jest.fn(),
    mcpServerInstallationsToolsRefreshCreate: jest.fn(),
    mcpServersList: jest.fn(),
}))

const mockApplyPreset = mcpGatewayConfigApplyPresetCreate as jest.MockedFunction<
    typeof mcpGatewayConfigApplyPresetCreate
>
const mockConfigList = mcpGatewayConfigList as jest.MockedFunction<typeof mcpGatewayConfigList>
const mockSetAllServersEnabled = mcpGatewayConfigSetAllServersEnabledCreate as jest.MockedFunction<
    typeof mcpGatewayConfigSetAllServersEnabledCreate
>
const mockMembersList = mcpGatewayMembersList as jest.MockedFunction<typeof mcpGatewayMembersList>
const mockRulesList = mcpGatewayRulesList as jest.MockedFunction<typeof mcpGatewayRulesList>
const mockServersList = mcpGatewayServersList as jest.MockedFunction<typeof mcpGatewayServersList>
const mockServersPartialUpdate = mcpGatewayServersPartialUpdate as jest.MockedFunction<
    typeof mcpGatewayServersPartialUpdate
>
const mockSetTemplateEnabled = mcpGatewayServersSetTemplateEnabledCreate as jest.MockedFunction<
    typeof mcpGatewayServersSetTemplateEnabledCreate
>
const mockServiceAccountAccess = mcpGatewayServiceAccountsAccessCreate as jest.MockedFunction<
    typeof mcpGatewayServiceAccountsAccessCreate
>
const mockServiceAccountsList = mcpGatewayServiceAccountsList as jest.MockedFunction<
    typeof mcpGatewayServiceAccountsList
>
const mockInstallCustom = mcpServerInstallationsInstallCustomCreate as jest.MockedFunction<
    typeof mcpServerInstallationsInstallCustomCreate
>
const mockInstallTemplate = mcpServerInstallationsInstallTemplateCreate as jest.MockedFunction<
    typeof mcpServerInstallationsInstallTemplateCreate
>
const mockRefreshTools = mcpServerInstallationsToolsRefreshCreate as jest.MockedFunction<
    typeof mcpServerInstallationsToolsRefreshCreate
>
const mockTemplatesList = mcpServersList as jest.MockedFunction<typeof mcpServersList>

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

function apiError(detail: string): Error & { detail: string } {
    return Object.assign(new Error(detail), { detail })
}

function gatewayServer(overrides: Partial<MCPGatewayServerApi>): MCPGatewayServerApi {
    return {
        id: 'server-id',
        name: 'Test server',
        url: 'https://mcp.example.com/mcp',
        description: '',
        category: 'dev',
        template_auth_type: null,
        is_team_enabled: true,
        icon_key: '',
        icon_domain: '',
        docs_url: '',
        template_id: null,
        tool_count: 0,
        connections: [],
        your_connection: null,
        agents: [],
        revoked_user_ids: [],
        is_revoked_for_you: false,
        created_by: {
            id: MOCK_DEFAULT_BASIC_USER.id,
            uuid: MOCK_DEFAULT_BASIC_USER.uuid,
            distinct_id: MOCK_DEFAULT_BASIC_USER.distinct_id,
            first_name: MOCK_DEFAULT_BASIC_USER.first_name,
            email: MOCK_DEFAULT_BASIC_USER.email,
            hedgehog_config: null,
        },
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        ...overrides,
    }
}

function serverTemplate(overrides: Partial<MCPServerTemplateApi>): MCPServerTemplateApi {
    return {
        id: 'template-id',
        name: 'Catalog template',
        url: 'https://mcp.template.example.com/mcp',
        docs_url: '',
        description: '',
        auth_type: 'oauth',
        icon_key: '',
        icon_domain: '',
        category: 'dev',
        ...overrides,
    }
}

function serviceAccountWithShare(scope: MCPAgentGrantScopeEnumApi): MCPServiceAccountApi {
    return {
        id: 'account-id',
        name: 'Scout agent',
        description: '',
        handle: 'posthog-scout',
        agent_key: 'scout',
        status: 'active',
        server_ids: ['server-id'],
        servers: [
            {
                id: 'server-id',
                shared_by: YOU,
                scope,
                name: 'Test server',
                description: '',
                icon_key: '',
                icon_domain: '',
                connection_state: 'ready',
            },
        ],
        last_active_at: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    }
}

function gatewayMember(userId: number): GatewayMemberSummaryApi {
    return {
        user: {
            id: userId,
            uuid: `user-${userId}`,
            first_name: 'Test',
            last_name: 'Member',
            email: `member-${userId}@example.com`,
            hedgehog_config: null,
        },
        is_org_admin: false,
        connected_server_ids: [],
        revoked_server_ids: [],
    }
}

function serviceAccount(): MCPServiceAccountApi {
    return {
        id: 'scout-id',
        name: 'Scout',
        description: 'Product analyst',
        handle: 'posthog-scout',
        agent_key: 'scout',
        status: 'active',
        server_ids: [],
        servers: [],
        last_active_at: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    }
}

function installation(): MCPServerInstallationApi {
    return {
        id: 'installation-id',
        template_id: null,
        name: 'Custom server',
        icon_key: '',
        icon_domain: '',
        display_name: 'Custom server',
        url: 'https://mcp.example.com/mcp',
        description: '',
        auth_type: 'api_key',
        is_enabled: true,
        scope: 'personal',
        is_owner: true,
        needs_reauth: false,
        pending_oauth: false,
        proxy_url: '',
        tool_count: 0,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    }
}

describe('mcpGatewayLogic', () => {
    let logic: ReturnType<typeof mcpGatewayLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.resetAllMocks()
        mockConfigList.mockResolvedValue({ is_admin: true, allow_custom_servers: true, registered_template_ids: [] })
        mockMembersList.mockResolvedValue({ count: 0, results: [] })
        mockRulesList.mockResolvedValue({ count: 0, results: [] })
        mockServersList.mockResolvedValue({ count: 0, results: [] })
        mockServiceAccountsList.mockResolvedValue({ count: 0, results: [] })
        mockServiceAccountAccess.mockResolvedValue(serviceAccount())
        mockTemplatesList.mockResolvedValue({ count: 0, results: [] })
        mockInstallCustom.mockResolvedValue({ redirect_url: '' })
        mockInstallTemplate.mockResolvedValue({ redirect_url: '' })
        mockRefreshTools.mockResolvedValue({ count: 0, results: [] })

        logic = mcpGatewayLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('connects a custom API-key server with the selected auth type and credential', async () => {
        const server = gatewayServer({ id: 'custom-server' })
        logic.actions.loadServersSuccess([server])
        logic.actions.connectServer(server.id)
        logic.actions.setConnectionAuthType('api_key')
        logic.actions.setConnectionApiKey('sk-custom')

        await expectLogic(logic, () => {
            logic.actions.submitConnection()
        }).toFinishAllListeners()

        expect(mockInstallCustom).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({
                name: server.name,
                url: server.url,
                auth_type: 'api_key',
                api_key: 'sk-custom',
                scope: 'personal',
            })
        )
    })

    it('refreshes tools through the generated installation endpoint', async () => {
        await expectLogic(logic, () => {
            logic.actions.refreshServerTools('installation-id')
        }).toFinishAllListeners()

        expect(mockRefreshTools).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'installation-id')
        expect(logic.values.refreshingInstallationIds).toEqual(new Set())
    })

    it('keeps a failed server load distinct from a valid empty result until retry succeeds', async () => {
        logic.actions.loadServersFailure('Request failed')

        expect(logic.values.serversInitialized).toBe(true)
        expect(logic.values.serversLoadFailed).toBe(true)

        logic.actions.loadServers()
        expect(logic.values.serversLoadFailed).toBe(false)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.serversLoadFailed).toBe(false)
    })

    it('refreshes server metadata while asynchronous tool discovery settles', async () => {
        jest.useFakeTimers()
        mockServersList.mockClear()

        logic.actions.refreshServersAfterConnection()
        await Promise.resolve()
        expect(mockServersList).toHaveBeenCalledTimes(1)

        jest.advanceTimersByTime(1500)
        await Promise.resolve()
        expect(mockServersList).toHaveBeenCalledTimes(2)

        jest.advanceTimersByTime(3500)
        await Promise.resolve()
        expect(mockServersList).toHaveBeenCalledTimes(3)
        jest.useRealTimers()
    })

    it('passes the entered API key when connecting a catalog template', async () => {
        const server = gatewayServer({
            id: 'template-server',
            template_id: 'template-id',
            template_auth_type: 'api_key',
        })
        logic.actions.loadServersSuccess([server])
        logic.actions.connectServer(server.id)
        logic.actions.setConnectionApiKey('sk-template')

        await expectLogic(logic, () => {
            logic.actions.submitConnection()
        }).toFinishAllListeners()

        expect(mockInstallTemplate).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({
                template_id: server.template_id,
                api_key: 'sk-template',
                scope: 'personal',
            })
        )
    })

    it('does not connect an API-key catalog server without a key', () => {
        const server = gatewayServer({
            id: 'template-server',
            template_id: 'template-id',
            template_auth_type: 'api_key',
        })
        logic.actions.loadServersSuccess([server])
        logic.actions.connectServer(server.id)

        logic.actions.submitConnection()

        expect(logic.values.connectionSubmitDisabledReason).toBe('Enter an API key to connect this server.')
        expect(mockInstallTemplate).not.toHaveBeenCalled()
    })

    it('connects a custom server without a key when it does not require authentication', async () => {
        const server = gatewayServer({ id: 'custom-server' })
        logic.actions.loadServersSuccess([server])
        logic.actions.connectServer(server.id)
        logic.actions.setConnectionAuthType('api_key')

        await expectLogic(logic, () => {
            logic.actions.submitConnection()
        }).toFinishAllListeners()

        expect(logic.values.connectionSubmitDisabledReason).toBeNull()
        expect(mockInstallCustom).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({ auth_type: 'api_key', api_key: undefined })
        )
    })

    it('adds a custom server with team and agent sharing in one guarded request', async () => {
        const pendingInstall = deferred<Awaited<ReturnType<typeof mcpServerInstallationsInstallCustomCreate>>>()
        mockInstallCustom.mockReturnValue(pendingInstall.promise)
        logic.actions.loadServiceAccountsSuccess([serviceAccount()])
        logic.actions.openAddServerModal()
        logic.actions.setAddServerFormValue('name', '  Custom server  ')
        logic.actions.setAddServerFormValue('url', ' https://mcp.example.com/mcp ')
        logic.actions.setAddServerFormValue('authType', 'api_key')
        logic.actions.setAddServerFormValue('apiKey', 'secret-key')
        logic.actions.setAddServerFormValue('agentIds', ['scout-id'])

        logic.actions.submitAddServer()
        logic.actions.submitAddServer()

        expect(logic.values.addingServer).toBe(true)
        expect(mockInstallCustom).toHaveBeenCalledTimes(1)
        expect(mockInstallCustom).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({
                name: 'Custom server',
                url: 'https://mcp.example.com/mcp',
                auth_type: 'api_key',
                api_key: 'secret-key',
                scope: 'personal',
                team_enabled: true,
                agent_ids: ['scout-id'],
            })
        )

        pendingInstall.resolve(installation())
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.addingServer).toBe(false)
        expect(logic.values.addServerModalOpen).toBe(false)
    })

    it('sends initial per-tool policies when sharing a server with an agent', async () => {
        const account = serviceAccount()
        const updatedAccount = {
            ...account,
            server_ids: ['linear-id'],
            servers: [
                {
                    id: 'linear-id',
                    shared_by: YOU,
                    scope: 'personal' as const,
                    name: 'Linear',
                    description: '',
                    icon_key: '',
                    icon_domain: '',
                    connection_state: 'ready' as const,
                },
            ],
        }
        const policies = [
            { tool_name: 'create_issue', policy_state: 'approved' as const },
            { tool_name: 'delete_issue', policy_state: 'do_not_use' as const },
        ]
        logic.actions.loadServiceAccountsSuccess([account])
        logic.actions.loadServersSuccess([gatewayServer({ id: 'linear-id' })])
        mockServiceAccountAccess.mockResolvedValue(updatedAccount)

        await expectLogic(logic, () => {
            logic.actions.setAgentServerAccess(account.id, 'linear-id', true, 'personal', policies)
        }).toFinishAllListeners()

        expect(mockServiceAccountAccess).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), account.id, {
            gateway_server_id: 'linear-id',
            enabled: true,
            scope: 'personal',
            policies,
        })
        expect(logic.values.agentServerAccessLoadingKeys).toEqual(new Set())
        expect(logic.values.serviceAccounts[0].server_ids).toContain('linear-id')
        expect(logic.values.serviceAccounts[0].servers[0].connection_state).toBe('ready')
    })

    it('patches server.agents immediately when sharing and revoking, before the servers reload lands', async () => {
        const account = serviceAccount()
        const server = gatewayServer({ id: 'linear-id' })
        logic.actions.loadServiceAccountsSuccess([account])
        logic.actions.loadServersSuccess([server])
        mockServiceAccountAccess.mockResolvedValue({
            ...account,
            server_ids: ['linear-id'],
            servers: [
                {
                    id: 'linear-id',
                    shared_by: YOU,
                    scope: 'personal' as const,
                    name: 'Linear',
                    description: '',
                    icon_key: '',
                    icon_domain: '',
                    connection_state: 'ready' as const,
                },
            ],
        })
        const pendingReload = deferred<Awaited<ReturnType<typeof mcpGatewayServersList>>>()
        mockServersList.mockClear()
        mockServersList.mockReturnValue(pendingReload.promise)

        await expectLogic(logic, () => {
            logic.actions.setAgentServerAccess(account.id, server.id, true)
        }).toDispatchActions(['setAgentServerAccessComplete'])

        expect(logic.values.servers[0].agents.map((agent) => agent.service_account_id)).toEqual([account.id])

        await expectLogic(logic, () => {
            logic.actions.setAgentServerAccess(account.id, server.id, false)
        }).toDispatchActions(['setAgentServerAccessComplete'])

        expect(logic.values.servers[0].agents).toEqual([])

        pendingReload.resolve({ count: 1, results: [server] })
        await expectLogic(logic).toFinishAllListeners()
    })

    it('does not start a second OAuth connection while the first is in flight', async () => {
        const pendingInstall = deferred<Awaited<ReturnType<typeof mcpServerInstallationsInstallTemplateCreate>>>()
        mockInstallTemplate.mockReturnValue(pendingInstall.promise)
        const server = gatewayServer({
            id: 'oauth-template-server',
            template_id: 'template-id',
            template_auth_type: 'oauth',
        })
        logic.actions.loadServersSuccess([server])

        logic.actions.connectServer(server.id)
        logic.actions.connectServer(server.id)

        expect(mockInstallTemplate).toHaveBeenCalledTimes(1)

        pendingInstall.resolve({ redirect_url: '' })
        await expectLogic(logic).toFinishAllListeners()
    })

    it('surfaces access update failures and clears the loading state', async () => {
        const server = gatewayServer({ is_team_enabled: true })
        const toast = jest.spyOn(lemonToast, 'error')
        mockServersPartialUpdate.mockRejectedValue(apiError('You cannot update this server.'))
        logic.actions.loadServersSuccess([server])

        await expectLogic(logic, () => {
            logic.actions.toggleServerEnabled(server.id, false)
        }).toFinishAllListeners()

        expect(toast).toHaveBeenCalledWith('You cannot update this server.')
        expect(logic.values.serverEnabledLoadingIds).toEqual(new Set())
        expect(logic.values.servers[0].is_team_enabled).toBe(true)
    })

    it('bulk-disables through the config endpoint instead of per-server PATCHes', async () => {
        const server = gatewayServer({ id: 'row-server', is_team_enabled: true })
        const pendingBulk = deferred<Awaited<ReturnType<typeof mcpGatewayConfigSetAllServersEnabledCreate>>>()
        mockSetAllServersEnabled.mockReturnValue(pendingBulk.promise)
        mockServersList.mockClear()
        mockServersList.mockResolvedValue({ count: 1, results: [{ ...server, is_team_enabled: false }] })
        logic.actions.loadServersSuccess([server])

        logic.actions.setAllServersEnabled(false)
        await Promise.resolve()

        expect(logic.values.allServersEnabledLoading).toBe(true)
        expect(logic.values.allServersEnabledTarget).toBe(false)
        pendingBulk.resolve({ ...logic.values.config!, default_servers_enabled: false })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSetAllServersEnabled).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), { enabled: false })
        expect(mockServersPartialUpdate).not.toHaveBeenCalled()
        expect(logic.values.defaultServersEnabled).toBe(false)
        expect(logic.values.servers).toEqual([{ ...server, is_team_enabled: false }])
        expect(logic.values.allServersEnabledLoading).toBe(false)
        expect(logic.values.allServersEnabledTarget).toBeNull()
    })

    it.each([
        ['materializes a new row', 'materialized-server'],
        ['replaces the existing row', 'server-id'],
    ])('setTemplateEnabled %s without duplicating servers', async (_name, returnedServerId) => {
        const existing = gatewayServer({ id: 'server-id', is_team_enabled: true })
        const returned = gatewayServer({
            id: returnedServerId,
            template_id: 'catalog-template',
            is_team_enabled: false,
        })
        mockSetTemplateEnabled.mockResolvedValue(returned)
        logic.actions.loadServersSuccess([existing])

        await expectLogic(logic, () => {
            logic.actions.setTemplateEnabled('catalog-template', false)
        }).toFinishAllListeners()

        expect(mockSetTemplateEnabled).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            template_id: 'catalog-template',
            enabled: false,
        })
        expect(logic.values.servers).toEqual(returnedServerId === existing.id ? [returned] : [existing, returned])
        expect(logic.values.templateEnabledLoadingIds).toEqual(new Set())
    })

    it('recommends only catalog templates without a registry row, ignoring trailing slashes', () => {
        const linkedTemplate = serverTemplate({ id: 'linked-template', url: 'https://linked.example.com/mcp' })
        const sameUrlTemplate = serverTemplate({ id: 'same-url-template', url: 'https://custom.example.com/mcp/' })
        const freshTemplate = serverTemplate({ id: 'fresh-template', url: 'https://fresh.example.com/mcp' })
        logic.actions.loadTemplatesSuccess([linkedTemplate, sameUrlTemplate, freshTemplate])
        logic.actions.loadServersSuccess([
            gatewayServer({ id: 'linked-row', template_id: 'linked-template', url: 'https://linked.example.com/mcp' }),
            gatewayServer({ id: 'custom-row', template_id: null, url: 'https://custom.example.com/mcp' }),
        ])

        expect(logic.values.recommendedTemplates).toEqual([freshTemplate])
        expect(logic.values.mergedServers.map((server) => server.id)).toEqual([
            'linked-row',
            'custom-row',
            'template:fresh-template',
        ])
    })

    it('does not recommend a catalog template whose registry row is hidden from the member', () => {
        const hiddenTemplate = serverTemplate({ id: 'hidden-template' })
        const freshTemplate = serverTemplate({ id: 'fresh-template' })
        logic.actions.loadConfigSuccess({ is_admin: false, registered_template_ids: ['hidden-template'] })
        logic.actions.loadTemplatesSuccess([hiddenTemplate, freshTemplate])
        logic.actions.loadServersSuccess([])

        expect(logic.values.recommendedTemplates).toEqual([freshTemplate])
    })

    it('lists servers with a connection, including connections that need attention', () => {
        const connectedServer = gatewayServer({
            id: 'connected-server',
            your_connection: {
                installation_id: 'installation-id',
                is_enabled: false,
                pending_oauth: false,
                needs_reauth: true,
                last_used_at: null,
            },
        })
        const disconnectedServer = gatewayServer({ id: 'disconnected-server' })
        logic.actions.loadServersSuccess([connectedServer, disconnectedServer])

        expect(logic.values.connectedServers).toEqual([connectedServer])
    })

    it.each([
        [true, false, true],
        [false, false, false],
        [false, true, true],
    ])(
        'shows recommended templates (isAdmin=%s, defaultEnabled=%s) -> visible=%s',
        (isAdmin, defaultEnabled, visible) => {
            logic.actions.loadConfigSuccess({
                is_admin: isAdmin,
                allow_custom_servers: true,
                default_servers_enabled: defaultEnabled,
                registered_template_ids: [],
            })
            logic.actions.loadTemplatesSuccess([serverTemplate({ id: 'fresh-template' })])

            expect(logic.values.templateOnlyServers).toHaveLength(visible ? 1 : 0)
            expect(logic.values.templateOnlyServers[0]?.is_team_enabled).toBe(visible ? defaultEnabled : undefined)
        }
    )

    it('connects a recommended template through the template install flow', async () => {
        logic.actions.loadTemplatesSuccess([serverTemplate({ id: 'fresh-template', auth_type: 'oauth' })])

        await expectLogic(logic, () => {
            logic.actions.connectServer('template:fresh-template')
        }).toFinishAllListeners()

        expect(mockInstallTemplate).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({ template_id: 'fresh-template', scope: 'personal' })
        )
    })

    it('tracks preset updates by audience and uses the mutation response', async () => {
        const pendingPreset = deferred<Awaited<ReturnType<typeof mcpGatewayConfigApplyPresetCreate>>>()
        const updatedConfig = {
            ...logic.values.config!,
            member_default_preset: 'block' as const,
        }
        mockApplyPreset.mockReturnValue(pendingPreset.promise)
        const configLoadCalls = mockConfigList.mock.calls.length

        logic.actions.applyPreset('members', 'block')
        logic.actions.applyPreset('agents', 'allow')

        expect(logic.values.applyingPresetByAudience).toEqual({ members: 'block' })
        expect(mockApplyPreset).toHaveBeenCalledTimes(1)

        pendingPreset.resolve(updatedConfig)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.applyingPresetByAudience).toEqual({})
        expect(logic.values.config).toEqual(updatedConfig)
        expect(mockConfigList).toHaveBeenCalledTimes(configLoadCalls)
    })

    it('loads members one server-controlled page at a time', async () => {
        const secondPageMember = gatewayMember(101)
        mockMembersList.mockResolvedValue({ count: 101, results: [secondPageMember] })

        await expectLogic(logic, () => {
            logic.actions.setMembersOffset(GATEWAY_MEMBERS_PAGE_SIZE)
        }).toFinishAllListeners()

        expect(mockMembersList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: GATEWAY_MEMBERS_PAGE_SIZE,
            offset: GATEWAY_MEMBERS_PAGE_SIZE,
        })
        expect(logic.values.memberCount).toBe(101)
        expect(logic.values.members).toEqual([secondPageMember])
    })

    // The endpoint defaults an omitted scope back to personal, so a share sent without
    // one silently demotes a team share. The action fills in 'team', the product default.
    it.each([
        ['personal' as const, 'personal'],
        [undefined, 'team'],
    ])('sends scope %s as %s when sharing a server with an agent', async (requested, expected) => {
        mockServiceAccountAccess.mockResolvedValue(serviceAccountWithShare(expected as MCPAgentGrantScopeEnumApi))

        await expectLogic(logic, () => {
            logic.actions.setAgentServerAccess('account-id', 'server-id', true, requested)
        }).toFinishAllListeners()

        expect(mockServiceAccountAccess).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'account-id', {
            gateway_server_id: 'server-id',
            enabled: true,
            scope: expected,
        })
    })
})
