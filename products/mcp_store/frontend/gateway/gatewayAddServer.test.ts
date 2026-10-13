import {
    buildGatewayInstallRequest,
    canSubmitGatewayServer,
    GATEWAY_ADD_SERVER_DEFAULTS,
    type GatewayAddServerValues,
    isValidMcpUrl,
} from './gatewayAddServer'

function values(overrides: Partial<GatewayAddServerValues> = {}): GatewayAddServerValues {
    return {
        ...GATEWAY_ADD_SERVER_DEFAULTS,
        name: 'Internal wiki',
        url: 'https://mcp.example.com/sse',
        ...overrides,
    }
}

describe('gatewayAddServer', () => {
    it.each([
        ['https URL', 'https://mcp.example.com/sse', true],
        ['http URL', '  http://localhost:3000/mcp  ', true],
        ['bare host', 'mcp.example.com', false],
        ['missing host', 'https://', false],
        ['invalid host', 'https://.', false],
        ['unsupported scheme', 'ftp://mcp.example.com', false],
        ['empty URL', '', false],
    ])('validates a %s', (_label, url, expected) => {
        expect(isValidMcpUrl(url)).toBe(expected)
    })

    it.each([
        ['complete input', values(), true],
        ['blank name', values({ name: '  ' }), false],
        ['invalid URL', values({ url: 'not-a-url' }), false],
    ])('%s has the expected submission eligibility', (_label, input, expected) => {
        expect(canSubmitGatewayServer(input)).toBe(expected)
    })

    it('builds an admin OAuth payload with allowed team and agent sharing fields', () => {
        expect(
            buildGatewayInstallRequest(
                values({
                    name: '  Internal wiki  ',
                    url: '  https://mcp.example.com/sse  ',
                    description: '  Company knowledge  ',
                    clientId: '  client-id  ',
                    clientSecret: '  client-secret  ',
                    agentScope: 'personal',
                }),
                { isAdmin: true, canManageAgentAccess: true }
            )
        ).toEqual({
            name: 'Internal wiki',
            url: 'https://mcp.example.com/sse',
            description: 'Company knowledge',
            auth_type: 'oauth',
            client_id: 'client-id',
            client_secret: 'client-secret',
            team_enabled: true,
            agent_scope: 'personal',
        })
    })

    it('omits team and agent sharing fields when a member cannot manage them', () => {
        expect(
            buildGatewayInstallRequest(values({ teamEnabled: false, agentScope: 'team' }), {
                isAdmin: false,
                canManageAgentAccess: false,
            })
        ).toEqual({
            name: 'Internal wiki',
            url: 'https://mcp.example.com/sse',
            description: '',
            auth_type: 'oauth',
        })
    })

    it('lets a permitted member pick the agent scope without sending team enablement', () => {
        expect(
            buildGatewayInstallRequest(values({ teamEnabled: false, agentScope: 'team' }), {
                isAdmin: false,
                canManageAgentAccess: true,
            })
        ).toEqual({
            name: 'Internal wiki',
            url: 'https://mcp.example.com/sse',
            description: '',
            auth_type: 'oauth',
            agent_scope: 'team',
        })
    })

    it.each([
        [
            'API key authentication',
            values({ authType: 'api_key', apiKey: 'secret-key', clientId: 'oauth-id', clientSecret: 'oauth-secret' }),
            { api_key: 'secret-key' },
            ['client_id', 'client_secret'],
        ],
        [
            'OAuth authentication',
            values({ authType: 'oauth', apiKey: 'secret-key', clientId: 'oauth-id', clientSecret: 'oauth-secret' }),
            { client_id: 'oauth-id', client_secret: 'oauth-secret' },
            ['api_key'],
        ],
    ] as const)('includes only credentials for %s', (_label, input, expected, absentProperties) => {
        const request = buildGatewayInstallRequest(input, { isAdmin: true, canManageAgentAccess: true })
        expect(request).toEqual(expect.objectContaining(expected))
        for (const property of absentProperties) {
            expect(request).not.toHaveProperty(property)
        }
    })
})
