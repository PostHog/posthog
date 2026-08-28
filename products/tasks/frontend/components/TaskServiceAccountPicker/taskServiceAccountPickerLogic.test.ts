import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { mcpGatewayServiceAccountsList } from 'products/mcp_store/frontend/generated/api'
import type { MCPServiceAccountApi } from 'products/mcp_store/frontend/generated/api.schemas'

import { taskServiceAccountPickerLogic } from './taskServiceAccountPickerLogic'

jest.mock('products/mcp_store/frontend/generated/api', () => ({
    mcpGatewayServiceAccountsList: jest.fn(),
}))

const mockServiceAccountsList = jest.mocked(mcpGatewayServiceAccountsList)

function serviceAccount(overrides: Partial<MCPServiceAccountApi>): MCPServiceAccountApi {
    return {
        id: 'account-id',
        name: 'Account',
        description: '',
        handle: 'agent-account',
        agent_key: null,
        kind: 'custom',
        status: 'active',
        server_ids: [],
        servers: [],
        last_active_at: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        ...overrides,
    }
}

describe('taskServiceAccountPickerLogic', () => {
    let logic: ReturnType<typeof taskServiceAccountPickerLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        mockServiceAccountsList.mockResolvedValue({ count: 0, results: [] })
    })

    it('excludes built-in agents from the workflow task picker', async () => {
        const custom = serviceAccount({ id: 'custom-id', name: 'SRE', kind: 'custom' })
        const builtIn = serviceAccount({
            id: 'support-id',
            name: 'Support agent',
            handle: 'posthog-support',
            agent_key: 'support',
            kind: 'built_in',
        })
        mockServiceAccountsList.mockResolvedValue({ count: 2, results: [custom, builtIn] })

        logic = taskServiceAccountPickerLogic()
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()

        expect(logic.values.selectableServiceAccounts).toEqual([custom])
    })
})
