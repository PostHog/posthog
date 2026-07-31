import type {
    GatewayConnectionApi,
    GatewayYourConnectionApi,
    MCPGatewayServerApi,
    UserBasicApi,
} from '../generated/api.schemas'
import { getGatewayServerRemovalAction } from './gatewayServerRemoval'

function user(id: number): UserBasicApi {
    return {
        id,
        uuid: `user-${id}`,
        email: `user-${id}@example.com`,
        hedgehog_config: null,
    }
}

function yourConnection(overrides: Partial<GatewayYourConnectionApi> = {}): GatewayYourConnectionApi {
    return {
        installation_id: 'installation-1',
        is_enabled: true,
        pending_oauth: false,
        needs_reauth: false,
        last_used_at: null,
        ...overrides,
    }
}

function connection(userId: number, overrides: Partial<GatewayConnectionApi> = {}): GatewayConnectionApi {
    return {
        installation_id: 'installation-1',
        user: user(userId),
        last_used_at: null,
        pending_oauth: false,
        needs_reauth: false,
        ...overrides,
    }
}

function server(overrides: Partial<MCPGatewayServerApi> = {}): MCPGatewayServerApi {
    return {
        id: 'server-1',
        name: 'Internal wiki',
        url: 'https://mcp.example.com/sse',
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

describe('getGatewayServerRemovalAction', () => {
    it.each([
        ['an admin deleting a custom server', server({ created_by: user(2) }), true, undefined, 'delete_for_everyone'],
        [
            'a member deleting a custom server they added when connection summaries are hidden',
            server({
                created_by: user(1),
                your_connection: yourConnection(),
            }),
            false,
            1,
            'delete_for_you',
        ],
        [
            'a member disconnecting from a custom server someone else added',
            server({
                created_by: user(2),
                your_connection: yourConnection(),
                connections: [connection(1)],
            }),
            false,
            1,
            'disconnect',
        ],
        [
            'a member disconnecting from a catalog server',
            server({
                template_id: 'template-1',
                created_by: user(1),
                your_connection: yourConnection(),
                connections: [connection(1)],
            }),
            false,
            1,
            'disconnect',
        ],
        [
            'a caller without a current user ID when their connection summary identifies the creator',
            server({
                created_by: user(1),
                your_connection: yourConnection(),
                connections: [connection(1)],
            }),
            false,
            undefined,
            'delete_for_you',
        ],
        [
            'a caller without a current user ID or visible connection summary',
            server({ created_by: null, your_connection: yourConnection() }),
            false,
            undefined,
            'disconnect',
        ],
        ['an admin without a connection to a catalog server', server({ template_id: 'template-1' }), true, 1, null],
        ['a member without a personal connection', server({ created_by: user(1) }), false, 1, null],
    ] as const)('returns the correct action for %s', (_label, input, isAdmin, currentUserId, expected) => {
        expect(getGatewayServerRemovalAction(input, isAdmin, currentUserId)).toBe(expected)
    })
})
