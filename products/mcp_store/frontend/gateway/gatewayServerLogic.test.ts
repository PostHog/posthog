import { MOCK_DEFAULT_BASIC_USER } from '~/lib/api.mock'

import { lemonToast } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    mcpGatewayConfigList,
    mcpGatewayMembersList,
    mcpGatewayRulesList,
    mcpGatewayServersPoliciesCreate,
    mcpGatewayServersList,
    mcpGatewayServersToolsRetrieve,
    mcpGatewayServiceAccountsList,
} from '../generated/api'
import type { MCPGatewayServerApi, ResolvedToolPolicyApi } from '../generated/api.schemas'
import { gatewayServerLogic } from './gatewayServerLogic'
import { mcpGatewayLogic } from './mcpGatewayLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    mcpGatewayConfigList: jest.fn(),
    mcpGatewayMembersList: jest.fn(),
    mcpGatewayRulesList: jest.fn(),
    mcpGatewayServersPoliciesCreate: jest.fn(),
    mcpGatewayServersList: jest.fn(),
    mcpGatewayServersToolsRetrieve: jest.fn(),
    mcpGatewayServiceAccountsList: jest.fn(),
}))

const mockConfigList = jest.mocked(mcpGatewayConfigList)
const mockMembersList = jest.mocked(mcpGatewayMembersList)
const mockPoliciesCreate = jest.mocked(mcpGatewayServersPoliciesCreate)
const mockRulesList = jest.mocked(mcpGatewayRulesList)
const mockServersList = jest.mocked(mcpGatewayServersList)
const mockToolsRetrieve = jest.mocked(mcpGatewayServersToolsRetrieve)
const mockServiceAccountsList = jest.mocked(mcpGatewayServiceAccountsList)

function gatewayServer(): MCPGatewayServerApi {
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
        tool_count: 2,
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
    }
}

function toolPolicy(toolName: string, overrides: Partial<ResolvedToolPolicyApi> = {}): ResolvedToolPolicyApi {
    return {
        tool_name: toolName,
        description: '',
        input_schema: {},
        policy_state: 'approved',
        team_state: null,
        locked: false,
        decided_by: 'default',
        rule_name: '',
        rule_description: '',
        ...overrides,
    }
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

describe('gatewayServerLogic', () => {
    let parentLogic: ReturnType<typeof mcpGatewayLogic.build>
    let logic: ReturnType<typeof gatewayServerLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.resetAllMocks()
        mockConfigList.mockResolvedValue({
            is_admin: true,
            allow_custom_servers: true,
            allow_member_agent_access: true,
        })
        mockMembersList.mockResolvedValue({ count: 0, results: [] })
        mockRulesList.mockResolvedValue({ count: 0, results: [] })
        mockServersList.mockResolvedValue({ count: 1, results: [gatewayServer()] })
        mockServiceAccountsList.mockResolvedValue({ count: 0, results: [] })
        mockToolsRetrieve.mockResolvedValue({ count: 0, results: [] })

        parentLogic = mcpGatewayLogic()
        parentLogic.mount()
        await expectLogic(parentLogic).toFinishAllListeners()

        logic = gatewayServerLogic({ id: 'server-id' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        parentLogic.unmount()
        jest.restoreAllMocks()
    })

    it('uses the policy mutation response while keeping the loader in flight', async () => {
        const pendingResponse = deferred<Awaited<ReturnType<typeof mcpGatewayServersPoliciesCreate>>>()
        const updatedPolicy = toolPolicy('create_issue', { policy_state: 'needs_approval' })
        mockPoliciesCreate.mockReturnValue(pendingResponse.promise)

        logic.actions.setToolPolicy({ toolName: updatedPolicy.tool_name, state: updatedPolicy.policy_state })

        expect(logic.values.toolPoliciesLoading).toBe(true)
        expect(mockPoliciesCreate).toHaveBeenCalledTimes(1)

        pendingResponse.resolve({ count: 1, results: [updatedPolicy] })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.toolPoliciesLoading).toBe(false)
        expect(logic.values.toolPolicies).toEqual([updatedPolicy])
        expect(mockToolsRetrieve).toHaveBeenCalledTimes(1)
    })

    it('reports the number of tools changed by a bulk update', async () => {
        const editablePolicy = toolPolicy('create_issue')
        const lockedPolicy = toolPolicy('delete_issue', { locked: true, policy_state: 'do_not_use' })
        logic.actions.loadToolPoliciesSuccess([editablePolicy, lockedPolicy])
        mockPoliciesCreate.mockResolvedValue({
            count: 2,
            results: [{ ...editablePolicy, policy_state: 'needs_approval' }, lockedPolicy],
        })
        const toast = jest.spyOn(lemonToast, 'success')

        await expectLogic(logic, () => {
            logic.actions.setAllTools({ state: 'needs_approval' })
        }).toFinishAllListeners()

        expect(mockPoliciesCreate).toHaveBeenCalledWith(
            expect.any(String),
            'server-id',
            expect.objectContaining({
                policies: [{ tool_name: editablePolicy.tool_name, policy_state: 'needs_approval' }],
            })
        )
        expect(toast).toHaveBeenCalledWith('Updated 1 tool')
    })
})
