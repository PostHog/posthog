import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { env } from 'cloudflare:workers'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { track } from '@posthog/mcp-analytics'

import { initPostHogMcpAnalytics, type PostHogMcpAnalyticsIdentityProvider } from '@/lib/posthog-mcp-analytics'

const TEST_API_KEY = 'test-api-key'
const TEST_HOST = 'https://test.posthog.com'

describe('initPostHogMcpAnalytics', () => {
    beforeEach(() => {
        vi.mocked(track).mockClear()
        env.POSTHOG_ANALYTICS_API_KEY = TEST_API_KEY
        env.POSTHOG_ANALYTICS_HOST = TEST_HOST
    })

    function createMockIdentity(
        overrides: Partial<PostHogMcpAnalyticsIdentityProvider> = {}
    ): PostHogMcpAnalyticsIdentityProvider {
        return {
            getDistinctId: vi.fn().mockResolvedValue('user-123'),
            getSessionUuid: vi.fn().mockResolvedValue('session-uuid-456'),
            getMcpClientName: vi.fn().mockResolvedValue('claude-code'),
            getMcpClientVersion: vi.fn().mockResolvedValue('1.2.3'),
            getMcpProtocolVersion: vi.fn().mockResolvedValue('2024-11-05'),
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
            ...overrides,
        }
    }

    function getTrackOptions(): {
        identify: () => Promise<unknown>
        eventTags: () => Promise<Record<string, string>>
        eventProperties: () => Promise<Record<string, unknown>>
    } {
        const call = vi.mocked(track).mock.calls[0]!
        return call[1] as {
            identify: () => Promise<unknown>
            eventTags: () => Promise<Record<string, string>>
            eventProperties: () => Promise<Record<string, unknown>>
        }
    }

    it('calls PostHog MCP analytics track with safe defaults', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        const result = await initPostHogMcpAnalytics(server, identity)

        expect(track).toHaveBeenCalledWith(
            server,
            expect.objectContaining({
                apiKey: TEST_API_KEY,
                context: false,
                enableAITracing: true,
                enableTracing: true,
                host: TEST_HOST,
                identify: expect.any(Function),
                eventTags: expect.any(Function),
                eventProperties: expect.any(Function),
                posthogOptions: {
                    flushAt: 1,
                    flushInterval: 0,
                    host: TEST_HOST,
                },
                reportMissing: false,
            })
        )
        expect(result).toMatchObject({
            action: 'initialized',
            contextEnabled: false,
            reportMissingEnabled: false,
        })
    })

    it('enables required context only when explicitly requested', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        const result = await initPostHogMcpAnalytics(server, identity, {
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
        expect(result).toMatchObject({
            action: 'initialized',
            contextEnabled: true,
            reportMissingEnabled: false,
        })
    })

    it('enables get_more_tools (reportMissing) only when explicitly requested', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        const result = await initPostHogMcpAnalytics(server, identity, {
            contextEnabled: false,
            reportMissingEnabled: true,
        })

        expect(track).toHaveBeenCalledWith(
            server,
            expect.objectContaining({
                reportMissing: true,
            })
        )
        expect(result).toMatchObject({
            action: 'initialized',
            reportMissingEnabled: true,
        })
    })

    it.each(['POSTHOG_ANALYTICS_API_KEY', 'POSTHOG_ANALYTICS_HOST'] as const)(
        'skips initialization when %s is not set',
        async (envKey) => {
            env[envKey] = undefined as unknown as string
            const server = new McpServer({ name: 'test', version: '1.0.0' })
            const identity = createMockIdentity()

            const result = await initPostHogMcpAnalytics(server, identity)

            expect(track).not.toHaveBeenCalled()
            expect(result).toMatchObject({ action: 'skipped', reason: 'missing_config' })
        }
    )

    it('identify callback resolves identity from provider', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initPostHogMcpAnalytics(server, identity)

        expect(await getTrackOptions().identify()).toEqual({ userId: 'user-123' })
    })

    it('eventTags callback returns only $session_id when available ($ai_session_id moved to eventProperties)', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initPostHogMcpAnalytics(server, identity)

        const tags = await getTrackOptions().eventTags()
        expect(tags).toEqual({
            $session_id: 'session-uuid-456',
        })
        expect(tags).not.toHaveProperty('$ai_session_id')
    })

    it('eventTags callback returns empty when session uuid is undefined', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity({
            getSessionUuid: vi.fn().mockResolvedValue(undefined),
        })

        await initPostHogMcpAnalytics(server, identity)

        expect(await getTrackOptions().eventTags()).toEqual({})
    })

    it('eventProperties callback returns PostHog MCP context properties including $ai_session_id', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initPostHogMcpAnalytics(server, identity)

        expect(await getTrackOptions().eventProperties()).toEqual({
            $ai_session_id: 'session-uuid-456',
            $ai_product: 'mcp',
            $mcp_version: 2,
            $mcp_client_user_agent: 'test-agent/1.0',
            $mcp_client_name: 'claude-code',
            $mcp_client_version: '1.2.3',
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
            $groups: {
                organization: 'org-789',
                project: 'proj-uuid-101',
            },
        })
    })

    it('eventProperties callback omits $groups when analytics context is unavailable', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity({
            getAnalyticsContext: vi.fn().mockResolvedValue(undefined),
        })

        await initPostHogMcpAnalytics(server, identity)

        const properties = await getTrackOptions().eventProperties()
        expect(properties.$groups).toBeUndefined()
        expect(properties.$mcp_organization_id).toBeUndefined()
        expect(properties.$mcp_project_uuid).toBeUndefined()
        // $ai_session_id stays present — its presence is gated on session uuid, not analytics context.
        expect(properties.$ai_session_id).toBe('session-uuid-456')
    })

    it('eventProperties callback omits $ai_session_id when session uuid is undefined', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity({
            getSessionUuid: vi.fn().mockResolvedValue(undefined),
        })

        await initPostHogMcpAnalytics(server, identity)

        const properties = await getTrackOptions().eventProperties()
        expect(properties).not.toHaveProperty('$ai_session_id')
        // Other properties stay populated.
        expect(properties.$mcp_client_name).toBe('claude-code')
    })

    it('swallows errors if PostHog MCP analytics track throws', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        vi.mocked(track).mockImplementationOnce(() => {
            throw new Error('PostHog MCP analytics init failed')
        })

        await expect(initPostHogMcpAnalytics(server, identity)).resolves.toMatchObject({ action: 'failed' })
    })

    it('swallows errors if analytics identity resolution throws', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity({
            getDistinctId: vi.fn().mockRejectedValue(new Error('identity unavailable')),
        })

        await expect(initPostHogMcpAnalytics(server, identity)).resolves.toMatchObject({ action: 'failed' })
        expect(track).not.toHaveBeenCalled()
    })
})
