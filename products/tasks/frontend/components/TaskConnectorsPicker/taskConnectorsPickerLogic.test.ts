/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    ConnectionStateEnumApi,
    MCPServiceAccountApi,
    MCPServiceAccountServerApi,
    MCPToolApprovalStateEnumApi,
    ResolvedToolPolicyApi,
    UserBasicApi,
} from 'products/mcp_store/frontend/generated/api.schemas'

import { taskConnectorsPickerLogic } from './taskConnectorsPickerLogic'

const YOU: UserBasicApi = {
    id: MOCK_DEFAULT_USER.id,
    uuid: MOCK_DEFAULT_USER.uuid,
    email: MOCK_DEFAULT_USER.email,
    hedgehog_config: null,
}

const TEAMMATE: UserBasicApi = {
    id: MOCK_DEFAULT_USER.id + 1,
    uuid: 'teammate-uuid',
    email: 'teammate@posthog.com',
    hedgehog_config: null,
}

function server(
    id: string,
    name: string,
    connectionState: ConnectionStateEnumApi,
    sharedBy: UserBasicApi = YOU,
    scope: MCPServiceAccountServerApi['scope'] = 'team',
    reachable: boolean = true
): MCPServiceAccountServerApi {
    return {
        id,
        shared_by: sharedBy,
        scope,
        name,
        description: `${name} workspace`,
        url: `https://mcp.${name.toLowerCase()}.example.com/mcp`,
        icon_key: name.toLowerCase(),
        icon_domain: `${name.toLowerCase()}.com`,
        connection_state: connectionState,
        reachable,
    }
}

function account(
    agentKey: MCPServiceAccountApi['agent_key'],
    servers: MCPServiceAccountServerApi[]
): MCPServiceAccountApi {
    return {
        id: `${agentKey}-id`,
        name: agentKey,
        description: `${agentKey} agent`,
        handle: `svc-${agentKey}`,
        agent_key: agentKey,
        status: 'active',
        server_ids: servers.map(({ id }) => id),
        servers,
        last_active_at: null,
        created_at: '2026-08-28T00:00:00Z',
        updated_at: '2026-08-28T00:00:00Z',
    }
}

function listResponse<T>(results: T[]): [number, { count: number; next: null; previous: null; results: T[] }] {
    return [200, { count: results.length, next: null, previous: null, results }]
}

function resolvedTool(toolName: string, policyState: MCPToolApprovalStateEnumApi): ResolvedToolPolicyApi {
    return {
        tool_name: toolName,
        description: '',
        input_schema: {},
        is_destructive: false,
        policy_state: policyState,
        team_state: null,
        locked: false,
        decided_by: 'default',
        rule_name: '',
        rule_description: '',
    }
}

describe('taskConnectorsPickerLogic', () => {
    let logic: ReturnType<typeof taskConnectorsPickerLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('offers the team shares of the workflow agent, not another agent, a personal share, or an unreachable grant', async () => {
        const personalIncident = server('incident-id', 'Incident.io', 'ready', YOU, 'personal')
        const teamIncident = server('incident-id', 'Incident.io', 'ready', TEAMMATE)
        const datadog = server('datadog-id', 'Datadog', 'needs_reauth', TEAMMATE)
        const disabledLinear = server('linear-id', 'Linear', 'ready', TEAMMATE, 'team', false)
        const scoutOnlyNotion = server('notion-id', 'Notion', 'ready')
        useMocks({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () =>
                    listResponse([
                        account('scout', [scoutOnlyNotion]),
                        account('workflow', [personalIncident, teamIncident, datadog, disabledLinear]),
                    ]),
                '/api/projects/:team_id/mcp_gateway/servers/:server_id/tools/': (req) =>
                    req.params.server_id === 'incident-id'
                        ? listResponse([
                              resolvedTool('search', 'approved'),
                              resolvedTool('create_incident', 'needs_approval'),
                              resolvedTool('delete_incident', 'do_not_use'),
                          ])
                        : [500, { detail: 'boom' }],
            },
        })

        logic = taskConnectorsPickerLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.workflowAccount?.agent_key).toEqual('workflow')
        // A grant to another agent never backs a workflow run, and neither does a personal share or a
        // grant the gateway refuses (server disabled for the project, or the sharing member revoked).
        expect(logic.values.teamWorkflowServers).toEqual([datadog, teamIncident])
        expect(logic.values.serviceAccountsFailed).toBe(false)
        // Agent-scope tool approvals load for exactly the offered servers; a failed load is marked
        // rather than mistaken for a server with no tools.
        expect(logic.values.toolPolicyCountsByServer).toEqual({
            'incident-id': { approved: 1, needs_approval: 1, do_not_use: 1 },
            'datadog-id': 'error',
        })
    })

    it('records a failed load apart from an empty one', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () => [500, { detail: 'boom' }],
            },
        })

        logic = taskConnectorsPickerLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.teamWorkflowServers).toEqual([])
        expect(logic.values.serviceAccountsFailed).toBe(true)
    })
})
