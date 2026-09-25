import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import * as generated from './generated/api'
import type {
    MCPServerInstallationApi,
    MCPServerInstallationToolApi,
    MCPServerTemplateApi,
} from './generated/api.schemas'
import { mcpStoreLogic } from './mcpStoreLogic'

jest.mock('./generated/api')

const mocked = jest.mocked(generated)

function installation(id: string, url?: string): MCPServerInstallationApi {
    return {
        id,
        template_id: null,
        name: id,
        description: '',
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
        mocked.mcpServersList.mockResolvedValue({ count: 0, results: [] })
        mocked.mcpServerInstallationsList.mockResolvedValue({ count: 0, results: [] })

        logic = mcpStoreLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('disables a stale catalog card and refetches when its template no longer resolves', async () => {
        const template: MCPServerTemplateApi = {
            id: 'gone-template',
            name: 'Gone',
            url: 'https://gone.example.com/mcp',
            docs_url: '',
            description: '',
            auth_type: 'oauth',
            icon_key: '',
            icon_domain: '',
            category: 'dev',
        }
        logic.actions.loadServersSuccess([template])
        mocked.mcpServerInstallationsInstallTemplateCreate.mockRejectedValue({
            status: 404,
            detail: 'This server is no longer in the catalog.',
            data: { reason: 'template_unavailable' },
        })
        const listServers = mocked.mcpServersList.mockResolvedValue({ count: 0, results: [] })

        logic.actions.installTemplate({ templateId: template.id })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.unavailableTemplateIds.has(template.id)).toBe(true)
        expect(listServers).toHaveBeenCalled()
        expect(logic.values.servers).toEqual([])
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
        mocked.mcpServerInstallationsToolsPartialUpdate.mockResolvedValue(tool('source'))
        const listTools = mocked.mcpServerInstallationsToolsRetrieve.mockImplementation(
            async (_projectId, installationId) => ({ count: 1, results: [tool(installationId)] })
        )

        await expectLogic(logic, () => {
            logic.actions.setToolApprovalState({
                installationId: 'source',
                toolName: 'create_issue',
                approvalState: 'needs_approval',
            })
        }).toFinishAllListeners()

        expect(listTools.mock.calls.map(([, installationId]) => installationId).sort()).toEqual([
            'same-server',
            'source',
        ])
    })
})
