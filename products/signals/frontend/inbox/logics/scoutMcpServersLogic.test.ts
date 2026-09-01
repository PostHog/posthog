/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    ConnectionStateEnumApi,
    MCPServiceAccountApi,
    MCPServiceAccountServerApi,
    UserBasicApi,
} from 'products/mcp_store/frontend/generated/api.schemas'

import { scoutMcpServersLogic } from './scoutMcpServersLogic'

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
    scope: MCPServiceAccountServerApi['scope'] = 'team'
): MCPServiceAccountServerApi {
    return {
        id,
        shared_by: sharedBy,
        scope,
        name,
        description: `${name} workspace`,
        icon_key: name.toLowerCase(),
        icon_domain: `${name.toLowerCase()}.com`,
        connection_state: connectionState,
    }
}

function account(
    agentKey: MCPServiceAccountApi['agent_key'],
    servers: MCPServiceAccountServerApi[],
    { status = 'active' }: { status?: MCPServiceAccountApi['status'] } = {}
): MCPServiceAccountApi {
    return {
        id: `${agentKey}-id`,
        name: agentKey,
        description: `${agentKey} agent`,
        handle: `svc-${agentKey}`,
        agent_key: agentKey,
        status,
        server_ids: servers.map(({ id }) => id),
        servers,
        last_active_at: null,
        created_at: '2026-07-22T00:00:00Z',
        updated_at: '2026-07-22T00:00:00Z',
    }
}

function listResponse<T>(results: T[]): [number, { count: number; next: null; previous: null; results: T[] }] {
    return [200, { count: results.length, next: null, previous: null, results }]
}

describe('scoutMcpServersLogic', () => {
    let logic: ReturnType<typeof scoutMcpServersLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('offers only team shares from the scout account, one row per server, preferring a ready share', async () => {
        const personalNotion = server('notion-id', 'Notion', 'ready', YOU, 'personal')
        const staleLinear = server('linear-id', 'linear', 'needs_reauth', YOU)
        const readyLinear = server('linear-id', 'linear', 'ready', TEAMMATE)
        const github = server('github-id', 'GitHub', 'ready', TEAMMATE)
        const supportZendesk = server('zendesk-id', 'Zendesk', 'ready')
        useMocks({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () =>
                    listResponse([
                        account('support', [supportZendesk]),
                        account('scout', [personalNotion, staleLinear, readyLinear, github]),
                    ]),
            },
        })

        logic = scoutMcpServersLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.scoutServers).toEqual([personalNotion, staleLinear, readyLinear, github])
        // The personal grant never backs a scout run, so it never shows. The two team shares
        // of Linear collapse to one row, and the ready one carries it so the health tag does
        // not report a problem the run does not have. Sorting ignores case.
        expect(logic.values.teamScoutServers).toEqual([github, readyLinear])
    })
})
