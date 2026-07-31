import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

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
    mcpGatewayServiceAccountsList,
    mcpServerInstallationsInstallCustomCreate,
    mcpServerInstallationsInstallTemplateCreate,
    mcpServersList,
} from '../generated/api'
import type { GatewayMemberSummaryApi, MCPGatewayServerApi, MCPServerTemplateApi } from '../generated/api.schemas'
import { GATEWAY_MEMBERS_PAGE_SIZE, mcpGatewayLogic } from './mcpGatewayLogic'

jest.mock('../generated/api', () => ({
    mcpGatewayConfigApplyPresetCreate: jest.fn(),
    mcpGatewayConfigList: jest.fn(),
    mcpGatewayConfigSetAllServersEnabledCreate: jest.fn(),
    mcpGatewayMembersList: jest.fn(),
    mcpGatewayRulesList: jest.fn(),
    mcpGatewayServersList: jest.fn(),
    mcpGatewayServersPartialUpdate: jest.fn(),
    mcpGatewayServersSetTemplateEnabledCreate: jest.fn(),
    mcpGatewayServiceAccountsList: jest.fn(),
    mcpServerInstallationsInstallCustomCreate: jest.fn(),
    mcpServerInstallationsInstallTemplateCreate: jest.fn(),
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
const mockServiceAccountsList = mcpGatewayServiceAccountsList as jest.MockedFunction<
    typeof mcpGatewayServiceAccountsList
>
const mockInstallCustom = mcpServerInstallationsInstallCustomCreate as jest.MockedFunction<
    typeof mcpServerInstallationsInstallCustomCreate
>
const mockInstallTemplate = mcpServerInstallationsInstallTemplateCreate as jest.MockedFunction<
    typeof mcpServerInstallationsInstallTemplateCreate
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

describe('mcpGatewayLogic', () => {
    let logic: ReturnType<typeof mcpGatewayLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.resetAllMocks()
        mockConfigList.mockResolvedValue({ is_admin: true, allow_custom_servers: true })
        mockMembersList.mockResolvedValue({ count: 0, results: [] })
        mockRulesList.mockResolvedValue({ count: 0, results: [] })
        mockServersList.mockResolvedValue({ count: 0, results: [] })
        mockServiceAccountsList.mockResolvedValue({ count: 0, results: [] })
        mockTemplatesList.mockResolvedValue({ count: 0, results: [] })
        mockInstallCustom.mockResolvedValue({ redirect_url: '' })
        mockInstallTemplate.mockResolvedValue({ redirect_url: '' })

        logic = mcpGatewayLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
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

    it('does not connect an API-key server without a key', () => {
        const server = gatewayServer({ id: 'custom-server' })
        logic.actions.loadServersSuccess([server])
        logic.actions.connectServer(server.id)
        logic.actions.setConnectionAuthType('api_key')

        logic.actions.submitConnection()

        expect(logic.values.connectionSubmitDisabledReason).toBe('Enter an API key to connect this server.')
        expect(mockInstallCustom).not.toHaveBeenCalled()
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
        pendingBulk.resolve({ ...logic.values.config!, default_servers_enabled: false })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSetAllServersEnabled).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), { enabled: false })
        expect(mockServersPartialUpdate).not.toHaveBeenCalled()
        expect(logic.values.defaultServersEnabled).toBe(false)
        expect(logic.values.servers).toEqual([{ ...server, is_team_enabled: false }])
        expect(logic.values.allServersEnabledLoading).toBe(false)
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
            })
            logic.actions.loadTemplatesSuccess([serverTemplate({ id: 'fresh-template' })])

            if (!visible) {
                expect(logic.values.templateOnlyServers).toEqual([])
            } else {
                expect(logic.values.templateOnlyServers).toHaveLength(1)
                expect(logic.values.templateOnlyServers[0].is_team_enabled).toBe(defaultEnabled)
            }
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
})
