import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    mcpGatewayConfigList,
    mcpGatewayMembersList,
    mcpGatewayRulesList,
    mcpGatewayServersList,
    mcpGatewayServiceAccountsList,
    mcpServerInstallationsInstallCustomCreate,
    mcpServerInstallationsInstallTemplateCreate,
} from '../generated/api'
import type { GatewayMemberSummaryApi, MCPGatewayServerApi } from '../generated/api.schemas'
import { GATEWAY_MEMBERS_PAGE_SIZE, mcpGatewayLogic } from './mcpGatewayLogic'

jest.mock('../generated/api', () => ({
    mcpGatewayConfigList: jest.fn(),
    mcpGatewayMembersList: jest.fn(),
    mcpGatewayRulesList: jest.fn(),
    mcpGatewayServersList: jest.fn(),
    mcpGatewayServiceAccountsList: jest.fn(),
    mcpServerInstallationsInstallCustomCreate: jest.fn(),
    mcpServerInstallationsInstallTemplateCreate: jest.fn(),
}))

const mockConfigList = mcpGatewayConfigList as jest.MockedFunction<typeof mcpGatewayConfigList>
const mockMembersList = mcpGatewayMembersList as jest.MockedFunction<typeof mcpGatewayMembersList>
const mockRulesList = mcpGatewayRulesList as jest.MockedFunction<typeof mcpGatewayRulesList>
const mockServersList = mcpGatewayServersList as jest.MockedFunction<typeof mcpGatewayServersList>
const mockServiceAccountsList = mcpGatewayServiceAccountsList as jest.MockedFunction<
    typeof mcpGatewayServiceAccountsList
>
const mockInstallCustom = mcpServerInstallationsInstallCustomCreate as jest.MockedFunction<
    typeof mcpServerInstallationsInstallCustomCreate
>
const mockInstallTemplate = mcpServerInstallationsInstallTemplateCreate as jest.MockedFunction<
    typeof mcpServerInstallationsInstallTemplateCreate
>

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

function gatewayServer(overrides: Partial<MCPGatewayServerApi>): MCPGatewayServerApi {
    return {
        id: 'server-id',
        name: 'Test server',
        url: 'https://mcp.example.com/mcp',
        description: '',
        category: 'dev',
        auth_mode: 'individual',
        template_auth_type: null,
        is_team_enabled: true,
        allow_personal_connections: true,
        icon_key: '',
        icon_domain: '',
        docs_url: '',
        template_id: null,
        tool_count: 0,
        connections: [],
        your_connection: null,
        shared_credential: null,
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
        mockInstallCustom.mockResolvedValue({ redirect_url: '' })
        mockInstallTemplate.mockResolvedValue({ redirect_url: '' })

        logic = mcpGatewayLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
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
