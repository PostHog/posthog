import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import type { MCPServerInstallationApi, MCPServerInstallationToolApi } from './generated/api.schemas'
import { mcpStoreLogic } from './mcpStoreLogic'

jest.mock('lib/api')

function installation(id: string, url?: string): MCPServerInstallationApi {
    return {
        id,
        template_id: null,
        name: id,
        icon_key: '',
        icon_domain: '',
        url,
        scope: 'shared',
        is_owner: true,
        needs_reauth: false,
        pending_oauth: false,
        proxy_url: '',
        tool_count: 1,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    }
}

function tool(installationId: string): MCPServerInstallationToolApi {
    return {
        id: `${installationId}-tool`,
        tool_name: 'create_issue',
        display_name: 'Create issue',
        description: '',
        input_schema: {},
        approval_state: 'approved',
        team_state: null,
        locked: false,
        decided_by: 'default',
        last_seen_at: '2026-01-01T00:00:00Z',
        removed_at: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    }
}

describe('mcpStoreLogic', () => {
    let logic: ReturnType<typeof mcpStoreLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.resetAllMocks()
        jest.spyOn(api.mcpServers, 'list').mockResolvedValue({ count: 0, results: [] })
        jest.spyOn(api.mcpServerInstallations, 'list').mockResolvedValue({ count: 0, results: [] })

        logic = mcpStoreLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('reloads only loaded installations for the shared server whose policy changed', async () => {
        const installations = [
            installation('source', 'https://shared.example.com/mcp'),
            installation('same-server', 'https://shared.example.com/mcp'),
            installation('other-server', 'https://other.example.com/mcp'),
            installation('missing-url'),
        ]
        logic.actions.loadInstallationsSuccess(installations)
        logic.actions.loadInstallationToolsSuccess(Object.fromEntries(installations.map(({ id }) => [id, [tool(id)]])))
        jest.spyOn(api.mcpServerInstallations, 'updateToolApproval').mockResolvedValue({})
        const listTools = jest
            .spyOn(api.mcpServerInstallations, 'listTools')
            .mockImplementation(async (installationId) => ({ results: [tool(installationId)] }))

        await expectLogic(logic, () => {
            logic.actions.setToolApprovalState({
                installationId: 'source',
                toolName: 'create_issue',
                approvalState: 'needs_approval',
            })
        }).toFinishAllListeners()

        expect(listTools.mock.calls.map(([installationId]) => installationId).sort()).toEqual(['same-server', 'source'])
    })
})
