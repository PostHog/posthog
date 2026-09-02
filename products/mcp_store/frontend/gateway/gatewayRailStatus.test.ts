import type { GatewayYourConnectionApi, MCPGatewayServerApi } from '../generated/api.schemas'
import { GatewayRailStatus, gatewayRailStatus } from './gatewayRailStatus'

function gatewayServer(overrides: Partial<MCPGatewayServerApi> = {}): MCPGatewayServerApi {
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

function connection(overrides: Partial<GatewayYourConnectionApi> = {}): GatewayYourConnectionApi {
    return {
        installation_id: 'installation-id',
        is_enabled: true,
        pending_oauth: false,
        needs_reauth: false,
        last_used_at: null,
        ...overrides,
    }
}

describe('gatewayRailStatus', () => {
    it('returns null without a personal connection', () => {
        expect(gatewayRailStatus(gatewayServer())).toBeNull()
    })

    it.each<[string, Partial<MCPGatewayServerApi>, GatewayRailStatus]>([
        ['healthy connection', { your_connection: connection() }, 'connected'],
        ['pending OAuth', { your_connection: connection({ pending_oauth: true }) }, 'pending_oauth'],
        ['invalidated token', { your_connection: connection({ needs_reauth: true }) }, 'needs_reauth'],
        ['self-disabled connection', { your_connection: connection({ is_enabled: false }) }, 'self_disabled'],
        ['team-disabled server', { your_connection: connection(), is_team_enabled: false }, 'team_off'],
        [
            'revoked access outranks connection problems',
            {
                your_connection: connection({ needs_reauth: true }),
                is_team_enabled: false,
                is_revoked_for_you: true,
            },
            'revoked',
        ],
        [
            'team off outranks a pending OAuth round-trip',
            { your_connection: connection({ pending_oauth: true }), is_team_enabled: false },
            'team_off',
        ],
    ])('%s', (_name, overrides, expected) => {
        expect(gatewayRailStatus(gatewayServer(overrides))).toBe(expected)
    })
})
