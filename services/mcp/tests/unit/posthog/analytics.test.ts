import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { env } from 'cloudflare:workers'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { track } from '@posthog/mcp-analytics'

import { buildMCPAnalyticsGroups, buildMCPContextProperties, type MCPAnalyticsContext } from '@/lib/posthog/analytics'
import { initMcpAnalytics, type IdentityProvider } from '@/lib/posthog/analytics'

const TEST_API_KEY = 'test-api-key'
const TEST_HOST = 'https://test.posthog.com'

describe('buildMCPAnalyticsGroups', () => {
    it.each<[string, MCPAnalyticsContext, Record<string, string>]>([
        [
            'full context uses UUID as the project group key',
            { organizationId: 'org-1', projectId: '123', projectUuid: 'project-uuid-123' },
            { organization: 'org-1', project: 'project-uuid-123' },
        ],
        ['organization only', { organizationId: 'org-1' }, { organization: 'org-1' }],
        ['project UUID only', { projectUuid: 'project-uuid-123' }, { project: 'project-uuid-123' }],
        ['ignores projectId when projectUuid is absent', { projectId: '123' }, {}],
        ['empty context', {}, {}],
    ])('%s', (_, input, expected) => {
        expect(buildMCPAnalyticsGroups(input)).toEqual(expected)
    })
})

describe('buildMCPContextProperties', () => {
    it.each<[string, MCPAnalyticsContext, { prefix?: string } | undefined, Record<string, string>]>([
        [
            'full context → snake_case properties',
            {
                organizationId: 'org-1',
                projectId: '123',
                projectUuid: 'project-uuid-123',
                projectName: 'My Project',
            },
            undefined,
            {
                organization_id: 'org-1',
                project_id: '123',
                project_uuid: 'project-uuid-123',
                project_name: 'My Project',
            },
        ],
        [
            'prefix applies to every key (used for previous_* on context-switch events)',
            { organizationId: 'org-1', projectUuid: 'project-uuid-123' },
            { prefix: 'previous_' },
            { previous_organization_id: 'org-1', previous_project_uuid: 'project-uuid-123' },
        ],
        ['empty context yields empty object', {}, undefined, {}],
        [
            'partial context omits absent keys rather than emitting undefined',
            { organizationId: 'org-1' },
            undefined,
            { organization_id: 'org-1' },
        ],
    ])('%s', (_, input, options, expected) => {
        expect(buildMCPContextProperties(input, options)).toEqual(expected)
    })
})

describe('initMcpAnalytics', () => {
    beforeEach(() => {
        vi.mocked(track).mockClear()
        env.POSTHOG_ANALYTICS_API_KEY = TEST_API_KEY
        env.POSTHOG_ANALYTICS_HOST = TEST_HOST
    })

    function createMockIdentity(overrides: Partial<IdentityProvider> = {}): IdentityProvider {
        return {
            getDistinctId: vi.fn().mockResolvedValue('user-123'),
            getSessionUuid: vi.fn().mockResolvedValue('session-uuid-456'),
            getMcpClientName: vi.fn().mockResolvedValue('claude-code'),
            getMcpClientVersion: vi.fn().mockResolvedValue('1.2.3'),
            getMcpProtocolVersion: vi.fn().mockResolvedValue('2024-11-05'),
            getMcpVendorClient: vi.fn().mockResolvedValue('ClaudeCode'),
            getRegion: vi.fn().mockResolvedValue('us'),
            getAnalyticsContext: vi.fn().mockResolvedValue({
                organizationId: 'org-789',
                projectId: 'proj-101',
                projectUuid: 'proj-uuid-101',
                projectName: 'Project 101',
            }),
            getClientUserAgent: vi.fn().mockResolvedValue('test-agent/1.0'),
            getMcpVersion: vi.fn().mockResolvedValue(2),
            getOAuthClientName: vi.fn().mockResolvedValue('PostHog Code'),
            getReadOnly: vi.fn().mockResolvedValue(true),
            getTransport: vi.fn().mockResolvedValue('streamable-http'),
            getMcpConsumer: vi.fn().mockResolvedValue('posthog-code'),
            getMcpMode: vi.fn().mockResolvedValue('cli'),
            getMcpSessionId: vi.fn().mockResolvedValue('mcp-session-abc'),
            getMcpConversationId: vi.fn().mockResolvedValue('mcp-conversation-xyz'),
            ...overrides,
        }
    }

    function getTrackOptions(): {
        identify: { userId: string }
        eventTags: () => Promise<Record<string, string>>
        eventProperties: (request?: unknown) => Promise<Record<string, unknown>>
    } {
        const call = vi.mocked(track).mock.calls[0]!
        return call[1] as {
            identify: { userId: string }
            eventTags: () => Promise<Record<string, string>>
            eventProperties: (request?: unknown) => Promise<Record<string, unknown>>
        }
    }

    it('calls PostHog MCP analytics track with safe defaults', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        const result = await initMcpAnalytics(server, identity)

        expect(track).toHaveBeenCalledWith(
            server,
            expect.objectContaining({
                posthogClient: expect.any(Object),
                context: false,
                enableAITracing: true,
                enableTracing: true,
                identify: expect.objectContaining({ userId: expect.any(String) }),
                eventTags: expect.any(Function),
                eventProperties: expect.any(Function),
                reportMissing: false,
            })
        )
        expect(result).toMatchObject({ action: 'initialized' })
    })

    it('enables required context only when explicitly requested', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        const result = await initMcpAnalytics(server, identity, {
            contextEnabled: true,
            reportMissingEnabled: false,
        })

        expect(track).toHaveBeenCalledWith(
            server,
            expect.objectContaining({
                context: true,
                enableAITracing: true,
                reportMissing: false,
            })
        )
        expect(result).toMatchObject({ action: 'initialized' })
    })

    it('enables get_more_tools (reportMissing) only when explicitly requested', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        const result = await initMcpAnalytics(server, identity, {
            contextEnabled: false,
            reportMissingEnabled: true,
        })

        expect(track).toHaveBeenCalledWith(
            server,
            expect.objectContaining({
                reportMissing: true,
            })
        )
        expect(result).toMatchObject({ action: 'initialized' })
    })

    it.each(['POSTHOG_ANALYTICS_API_KEY', 'POSTHOG_ANALYTICS_HOST'] as const)(
        'skips initialization when %s is not set',
        async (envKey) => {
            env[envKey] = undefined as unknown as string
            const server = new McpServer({ name: 'test', version: '1.0.0' })
            const identity = createMockIdentity()

            const result = await initMcpAnalytics(server, identity)

            expect(track).not.toHaveBeenCalled()
            expect(result).toMatchObject({ action: 'skipped', reason: 'missing_config' })
        }
    )

    it('identify callback resolves identity from provider', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initMcpAnalytics(server, identity)

        expect(getTrackOptions().identify).toEqual({ userId: 'user-123' })
    })

    it('eventTags callback returns $session_id and $ai_session_id when available', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initMcpAnalytics(server, identity)

        expect(await getTrackOptions().eventTags()).toEqual({
            $session_id: 'session-uuid-456',
            $ai_session_id: 'session-uuid-456',
        })
    })

    it('eventTags callback returns empty when session uuid is undefined', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity({
            getSessionUuid: vi.fn().mockResolvedValue(undefined),
        })

        await initMcpAnalytics(server, identity)

        expect(await getTrackOptions().eventTags()).toEqual({})
    })

    it('eventProperties callback returns PostHog MCP context properties', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initMcpAnalytics(server, identity)

        expect(await getTrackOptions().eventProperties()).toEqual({
            $ai_product: 'mcp',
            $mcp_version: 2,
            $mcp_client_user_agent: 'test-agent/1.0',
            $mcp_client_name: 'claude-code',
            $mcp_client_version: '1.2.3',
            mcp_vendor_client: 'ClaudeCode',
            $mcp_protocol_version: '2024-11-05',
            $mcp_region: 'us',
            $mcp_organization_id: 'org-789',
            $mcp_project_id: 'proj-101',
            $mcp_project_uuid: 'proj-uuid-101',
            $mcp_project_name: 'Project 101',
            $mcp_oauth_client_name: 'PostHog Code',
            $mcp_read_only: true,
            $mcp_transport: 'streamable-http',
            $mcp_consumer: 'posthog-code',
            $mcp_mode: 'cli',
            $mcp_session_id: 'mcp-session-abc',
            $mcp_conversation_id: 'mcp-conversation-xyz',
            $groups: {
                organization: 'org-789',
                project: 'proj-uuid-101',
            },
        })
    })

    it.each<{
        scenario: string
        resolverReturn: { name: string; description: string } | undefined
        expectedProperties: Record<string, unknown>
        absentProperties: string[]
    }>([
        {
            scenario: 'adds name + description when the resolver returns an inner tool',
            resolverReturn: { name: 'execute-sql', description: 'Run a HogQL/SQL query.' },
            expectedProperties: {
                $mcp_exec_tool_call_name: 'execute-sql',
                $mcp_exec_tool_call_description: 'Run a HogQL/SQL query.',
            },
            absentProperties: [],
        },
        {
            scenario: 'omits both properties when the resolver returns undefined',
            resolverReturn: undefined,
            expectedProperties: {},
            absentProperties: ['$mcp_exec_tool_call_name', '$mcp_exec_tool_call_description'],
        },
    ])('eventProperties $scenario', async ({ resolverReturn, expectedProperties, absentProperties }) => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()
        const resolveExecInnerToolCall = vi.fn().mockReturnValue(resolverReturn)

        await initMcpAnalytics(server, identity, {
            contextEnabled: false,
            reportMissingEnabled: false,
            resolveExecInnerToolCall,
        })

        const fakeRequest = { params: { name: 'exec', arguments: { command: 'call execute-sql {}' } } }
        const properties = await getTrackOptions().eventProperties(fakeRequest)

        expect(resolveExecInnerToolCall).toHaveBeenCalledWith(fakeRequest)
        for (const [key, value] of Object.entries(expectedProperties)) {
            expect(properties[key]).toBe(value)
        }
        for (const key of absentProperties) {
            expect(properties).not.toHaveProperty(key)
        }
        // Identity-derived properties should always be there regardless of resolver outcome.
        expect(properties.$mcp_organization_id).toBe('org-789')
    })

    it('eventProperties does not call the resolver when none is configured', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initMcpAnalytics(server, identity)

        const properties = await getTrackOptions().eventProperties({
            params: { name: 'exec', arguments: { command: 'call execute-sql {}' } },
        })

        expect(properties).not.toHaveProperty('$mcp_exec_tool_call_name')
        expect(properties).not.toHaveProperty('$mcp_exec_tool_call_description')
    })

    it('eventProperties attaches $mcp_exec_inner_tool_names on tools/list when execInnerToolNames is configured', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()
        const execInnerToolNames = ['execute-sql', 'feature-flag-get-all', 'insight-get']

        await initMcpAnalytics(server, identity, {
            contextEnabled: false,
            reportMissingEnabled: false,
            execInnerToolNames,
        })

        const listRequest = { method: 'tools/list', params: {} }
        const properties = await getTrackOptions().eventProperties(listRequest)

        expect(properties.$mcp_exec_inner_tool_names).toEqual(execInnerToolNames)
        // Other inner-call properties should be absent since this isn't a `call` request.
        expect(properties).not.toHaveProperty('$mcp_exec_tool_call_name')
    })

    it('eventProperties does not attach $mcp_exec_inner_tool_names on non-list methods', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initMcpAnalytics(server, identity, {
            contextEnabled: false,
            reportMissingEnabled: false,
            execInnerToolNames: ['execute-sql'],
        })

        const callRequest = {
            method: 'tools/call',
            params: { name: 'exec', arguments: { command: 'call execute-sql {}' } },
        }
        const properties = await getTrackOptions().eventProperties(callRequest)

        expect(properties).not.toHaveProperty('$mcp_exec_inner_tool_names')
    })

    it('eventProperties does not attach $mcp_exec_inner_tool_names when execInnerToolNames is empty', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initMcpAnalytics(server, identity, {
            contextEnabled: false,
            reportMissingEnabled: false,
            execInnerToolNames: [],
        })

        const properties = await getTrackOptions().eventProperties({ method: 'tools/list', params: {} })

        expect(properties).not.toHaveProperty('$mcp_exec_inner_tool_names')
    })

    it('eventProperties callback omits $groups when analytics context is unavailable', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity({
            getAnalyticsContext: vi.fn().mockResolvedValue(undefined),
        })

        await initMcpAnalytics(server, identity)

        const properties = await getTrackOptions().eventProperties()
        expect(properties.$groups).toBeUndefined()
        expect(properties.$mcp_organization_id).toBeUndefined()
        expect(properties.$mcp_project_uuid).toBeUndefined()
    })

    it('swallows errors if PostHog MCP analytics track throws', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        vi.mocked(track).mockImplementationOnce(() => {
            throw new Error('PostHog MCP analytics init failed')
        })

        await expect(initMcpAnalytics(server, identity)).resolves.toMatchObject({ action: 'failed' })
    })

    it('swallows errors if analytics identity resolution throws', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity({
            getDistinctId: vi.fn().mockRejectedValue(new Error('identity unavailable')),
        })

        await expect(initMcpAnalytics(server, identity)).resolves.toMatchObject({ action: 'failed' })
        expect(track).not.toHaveBeenCalled()
    })
})
