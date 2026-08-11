import { MOCK_DEFAULT_BASIC_USER } from '~/lib/api.mock'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    mcpGatewayConfigList,
    mcpGatewayMembersList,
    mcpGatewayMembersRetrieve,
    mcpGatewayRulesList,
    mcpGatewayServersList,
    mcpGatewayServiceAccountsList,
    mcpServersList,
} from '../generated/api'
import type { GatewayMemberSummaryApi, MCPGatewayServerApi } from '../generated/api.schemas'
import { gatewayMemberLogic } from './gatewayMemberLogic'
import { mcpGatewayLogic } from './mcpGatewayLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    mcpGatewayConfigList: jest.fn(),
    mcpGatewayMembersList: jest.fn(),
    mcpGatewayMembersRetrieve: jest.fn(),
    mcpGatewayRulesList: jest.fn(),
    mcpGatewayServersList: jest.fn(),
    mcpGatewayServiceAccountsList: jest.fn(),
    mcpServersList: jest.fn(),
}))

const mockConfigList = jest.mocked(mcpGatewayConfigList)
const mockMembersList = jest.mocked(mcpGatewayMembersList)
const mockMemberRetrieve = jest.mocked(mcpGatewayMembersRetrieve)
const mockRulesList = jest.mocked(mcpGatewayRulesList)
const mockServersList = jest.mocked(mcpGatewayServersList)
const mockServiceAccountsList = jest.mocked(mcpGatewayServiceAccountsList)
const mockTemplatesList = jest.mocked(mcpServersList)

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

function gatewayMember(): GatewayMemberSummaryApi {
    return {
        user: {
            id: MOCK_DEFAULT_BASIC_USER.id,
            uuid: MOCK_DEFAULT_BASIC_USER.uuid,
            distinct_id: MOCK_DEFAULT_BASIC_USER.distinct_id,
            first_name: MOCK_DEFAULT_BASIC_USER.first_name,
            email: MOCK_DEFAULT_BASIC_USER.email,
            hedgehog_config: null,
        },
        is_org_admin: false,
        connected_server_ids: [],
        revoked_server_ids: [],
    }
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
        created_by: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        ...overrides,
    }
}

describe('gatewayMemberLogic', () => {
    let parentLogic: ReturnType<typeof mcpGatewayLogic.build>
    let logic: ReturnType<typeof gatewayMemberLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.resetAllMocks()
        mockConfigList.mockResolvedValue({
            is_admin: true,
            registered_template_ids: [],
            allow_custom_servers: true,
            allow_member_agent_access: true,
        })
        mockMembersList.mockResolvedValue({ count: 0, results: [] })
        mockRulesList.mockResolvedValue({ count: 0, results: [] })
        mockServersList.mockResolvedValue({ count: 0, results: [] })
        mockServiceAccountsList.mockResolvedValue({ count: 0, results: [] })
        mockTemplatesList.mockResolvedValue({ count: 0, results: [] })

        parentLogic = mcpGatewayLogic()
        parentLogic.mount()
        await expectLogic(parentLogic).toFinishAllListeners()
    })

    afterEach(() => {
        logic?.unmount()
        parentLogic.unmount()
    })

    it('loads the member directly while reusing the gateway server registry', async () => {
        const member = gatewayMember()
        const pendingMember = deferred<GatewayMemberSummaryApi>()
        mockMemberRetrieve.mockReturnValue(pendingMember.promise)

        logic = gatewayMemberLogic({ id: String(member.user.id) })
        logic.mount()

        expect(logic.values.member).toBeNull()
        expect(logic.values.memberInitialized).toBe(false)
        expect(logic.values.memberLoading).toBe(true)

        pendingMember.resolve(member)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockMemberRetrieve).toHaveBeenCalledWith(expect.any(String), String(member.user.id))
        expect(mockServersList).toHaveBeenCalledTimes(1)
        expect(logic.values.member).toEqual(member)
        expect(logic.values.memberInitialized).toBe(true)
    })

    it('ignores deleted server ids in the access count and keeps connection details', async () => {
        const member = gatewayMember()
        const lastUsedAt = '2026-07-24T12:00:00Z'
        parentLogic.actions.loadServersSuccess([
            gatewayServer({
                id: 'connected-server',
                connections: [
                    {
                        installation_id: 'installation-id',
                        user: member.user,
                        last_used_at: lastUsedAt,
                        pending_oauth: false,
                        needs_reauth: false,
                    },
                ],
            }),
            gatewayServer({ id: 'revoked-server' }),
        ])
        mockMemberRetrieve.mockResolvedValue({
            ...member,
            connected_server_ids: ['connected-server'],
            revoked_server_ids: ['revoked-server', 'deleted-server'],
        })

        logic = gatewayMemberLogic({ id: String(member.user.id) })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.allowedServerCount).toBe(1)
        expect(logic.values.memberConnectionsByServerId['connected-server'].last_used_at).toBe(lastUsedAt)
    })
})
