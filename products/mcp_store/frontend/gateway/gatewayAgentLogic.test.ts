import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    mcpGatewayAuditList,
    mcpGatewayConfigList,
    mcpGatewayMembersList,
    mcpGatewayRulesList,
    mcpGatewayServersList,
    mcpGatewayServiceAccountsList,
    mcpServersList,
} from '../generated/api'
import type { MCPAuditEventApi, MCPGatewayServerApi, MCPServiceAccountApi } from '../generated/api.schemas'
import { gatewayAgentLogic } from './gatewayAgentLogic'
import { mcpGatewayLogic } from './mcpGatewayLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    mcpGatewayAuditList: jest.fn(),
    mcpGatewayConfigList: jest.fn(),
    mcpGatewayMembersList: jest.fn(),
    mcpGatewayRulesList: jest.fn(),
    mcpGatewayServersList: jest.fn(),
    mcpGatewayServiceAccountsList: jest.fn(),
    mcpServersList: jest.fn(),
}))

const mockAuditList = jest.mocked(mcpGatewayAuditList)
const mockConfigList = jest.mocked(mcpGatewayConfigList)
const mockMembersList = jest.mocked(mcpGatewayMembersList)
const mockRulesList = jest.mocked(mcpGatewayRulesList)
const mockServersList = jest.mocked(mcpGatewayServersList)
const mockServiceAccountsList = jest.mocked(mcpGatewayServiceAccountsList)
const mockTemplatesList = jest.mocked(mcpServersList)

function gatewayServer(id: string): MCPGatewayServerApi {
    return {
        id,
        name: `${id} name`,
        url: `https://${id}.example.com/mcp`,
        description: '',
        category: 'dev',
        template_auth_type: null,
        is_team_enabled: true,
        icon_key: '',
        icon_domain: '',
        docs_url: '',
        template_id: null,
        tool_count: 2,
        connections: [],
        your_connection: null,
        agents: [],
        revoked_user_ids: [],
        is_revoked_for_you: false,
        created_by: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    }
}

function serviceAccount(): MCPServiceAccountApi {
    return {
        id: 'support-agent',
        name: 'Support agent',
        description: 'Helps answer support questions',
        handle: 'posthog-support',
        agent_key: 'support',
        status: 'active',
        server_ids: ['shared-server'],
        servers: [],
        last_active_at: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    }
}

function auditEvent(index: number): MCPAuditEventApi {
    return {
        id: `event-${index}`,
        created_at: '2026-07-24T00:00:00Z',
        server_name: 'Shared server',
        tool_name: `tool-${index}`,
        decision: 'auto',
        actor_user: null,
        actor_service_account: {
            id: 'support-agent',
            name: 'Support agent',
            handle: 'posthog-support',
        },
        actor_label: 'posthog-support',
        credential_owner: null,
        grant_scope: '',
    }
}

describe('gatewayAgentLogic', () => {
    let parentLogic: ReturnType<typeof mcpGatewayLogic.build>
    let logic: ReturnType<typeof gatewayAgentLogic.build>

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
        mockServersList.mockResolvedValue({
            count: 2,
            results: [gatewayServer('unshared-server'), gatewayServer('shared-server')],
        })
        mockServiceAccountsList.mockResolvedValue({ count: 1, results: [serviceAccount()] })
        mockTemplatesList.mockResolvedValue({ count: 0, results: [] })
        mockAuditList.mockResolvedValue({
            count: 12,
            results: Array.from({ length: 12 }, (_, index) => auditEvent(index)),
        })

        parentLogic = mcpGatewayLogic()
        parentLogic.mount()
        await expectLogic(parentLogic).toFinishAllListeners()

        logic = gatewayAgentLogic({ id: 'support-agent' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        parentLogic.unmount()
    })

    it('partitions shared servers ahead of servers without access', () => {
        expect(logic.values.sharedServers.map((server) => server.id)).toEqual(['shared-server'])
        expect(logic.values.unsharedServers.map((server) => server.id)).toEqual(['unshared-server'])
    })

    it('loads enough recent calls for progressive disclosure', async () => {
        expect(mockAuditList).toHaveBeenCalledWith(expect.any(String), {
            actor_service_account_id: 'support-agent',
            limit: 50,
        })
        expect(logic.values.visibleRecentCalls).toHaveLength(5)

        await expectLogic(logic, () => logic.actions.showMoreRecentCalls()).toMatchValues({
            visibleRecentCalls: logic.values.recentCalls,
        })
    })
})
