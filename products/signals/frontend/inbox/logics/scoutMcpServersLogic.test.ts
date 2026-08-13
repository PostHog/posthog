/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

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
    scope: MCPServiceAccountServerApi['scope'] = 'personal'
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

describe('scoutMcpServersLogic', () => {
    let logic: ReturnType<typeof scoutMcpServersLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('separates your Scout grants from teammate team shares and flags the ones needing setup', async () => {
        const notion = server('notion-id', 'Notion', 'missing_credential')
        const linear = server('linear-id', 'Linear', 'ready')
        const teammateGithub = server('github-id', 'GitHub', 'ready', TEAMMATE, 'team')
        const teammateSentry = server('sentry-id', 'Sentry', 'ready', TEAMMATE)
        const zendesk = server('zendesk-id', 'Zendesk', 'ready')
        useMocks({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () => [
                    200,
                    {
                        count: 2,
                        next: null,
                        previous: null,
                        results: [
                            account('support', [zendesk]),
                            account('scout', [notion, linear, teammateGithub, teammateSentry]),
                        ],
                    },
                ],
            },
        })

        logic = scoutMcpServersLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.scoutServers).toEqual([notion, linear, teammateGithub, teammateSentry])
        expect(logic.values.yourScoutServers).toEqual([notion, linear])
        expect(logic.values.teammateScoutServers).toEqual([teammateGithub])
        expect(logic.values.isScoutMcpAccessEnabled).toBe(true)
        expect(logic.values.readyScoutServers).toEqual([linear, teammateGithub])
        expect(logic.values.availableScoutServers).toEqual([linear, teammateGithub])
        expect(logic.values.scoutServersNeedingSetup).toEqual([notion])
    })

    it('counts a server the viewer already shares once, even when a teammate team-shares it too', async () => {
        const yourLinear = server('linear-id', 'Linear', 'ready')
        const teammateLinear = server('linear-id', 'Linear', 'ready', TEAMMATE, 'team')
        useMocks({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () => [
                    200,
                    {
                        count: 1,
                        next: null,
                        previous: null,
                        results: [account('scout', [yourLinear, teammateLinear])],
                    },
                ],
            },
        })

        logic = scoutMcpServersLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.readyScoutServers).toEqual([yourLinear])
        expect(logic.values.availableScoutServers).toEqual([yourLinear])
    })

    it('attributes no grants while the current user is still loading', async () => {
        const linear = server('linear-id', 'Linear', 'ready')
        const teammateGithub = server('github-id', 'GitHub', 'ready', TEAMMATE)
        useMocks({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () => [
                    200,
                    {
                        count: 1,
                        next: null,
                        previous: null,
                        results: [account('scout', [linear, teammateGithub])],
                    },
                ],
            },
        })

        logic = scoutMcpServersLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        userLogic.actions.loadUserSuccess(null)

        expect(logic.values.currentUserId).toBeNull()
        expect(logic.values.yourScoutServers).toEqual([])
        expect(logic.values.teammateScoutServers).toEqual([])
        expect(logic.values.availableScoutServers).toEqual([])
        expect(logic.values.scoutServersNeedingSetup).toEqual([])
    })

    it('does not expose ready servers when MCP access is paused', async () => {
        const linear = server('linear-id', 'Linear', 'ready')
        useMocks({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () => [
                    200,
                    {
                        count: 1,
                        next: null,
                        previous: null,
                        results: [account('scout', [linear], { status: 'paused' })],
                    },
                ],
            },
        })

        logic = scoutMcpServersLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.scoutServers).toEqual([linear])
        expect(logic.values.isScoutMcpAccessEnabled).toBe(false)
        expect(logic.values.readyScoutServers).toEqual([linear])
        expect(logic.values.availableScoutServers).toEqual([])
        expect(logic.values.scoutServersNeedingSetup).toEqual([])
    })
})
