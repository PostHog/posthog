import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { env } from 'cloudflare:workers'
import { track } from 'mcpcat'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { initMcpCatObservability, redactSensitiveInformation, type McpCatIdentityProvider } from '@/lib/mcpcat'

const TEST_API_KEY = 'test-api-key'
const TEST_HOST = 'https://test.posthog.com'

describe('redactSensitiveInformation', () => {
    it.each([
        // PostHog project tokens
        ['Bearer phc_1a2b3c4d5e6f', '<redacted>'],
        // PostHog personal API keys
        ['Bearer phx_9z8y7x6w5v4u', '<redacted>'],
        // OAuth access and refresh tokens
        ['Bearer pha_access_token_value', '<redacted>'],
        ['Bearer phr_refresh_token_value', '<redacted>'],
        // Inside JSON strings
        ['"Authorization": "Bearer phc_abc123"', '"Authorization": "<redacted>"'],
        // Tokens with hyphens and dots (just in case we add them)
        ['Bearer phc_abc-123.xyz', '<redacted>'],
        // Multiple tokens
        ['Bearer phc_token1 and Bearer pha_token2', '<redacted> and <redacted>'],
        // No space after Bearer
        ['Bearerphc_no_space', '<redacted>'],
        // No match
        ['no sensitive data here', 'no sensitive data here'],
    ])('redacts %j to %j', (input, expected) => {
        expect(redactSensitiveInformation(input)).toBe(expected)
    })
})

describe('initMcpCatObservability', () => {
    beforeEach(() => {
        vi.mocked(track).mockClear()
        env.POSTHOG_ANALYTICS_API_KEY = TEST_API_KEY
        env.POSTHOG_ANALYTICS_HOST = TEST_HOST
    })

    function createMockIdentity(overrides: Partial<McpCatIdentityProvider> = {}): McpCatIdentityProvider {
        return {
            getDistinctId: vi.fn().mockResolvedValue('user-123'),
            getSessionUuid: vi.fn().mockResolvedValue('session-uuid-456'),
            getMcpClientName: vi.fn().mockReturnValue('claude-code'),
            getMcpClientVersion: vi.fn().mockReturnValue('1.2.3'),
            getMcpProtocolVersion: vi.fn().mockReturnValue('2024-11-05'),
            getRegion: vi.fn().mockReturnValue('us'),
            getOrganizationId: vi.fn().mockReturnValue('org-789'),
            getProjectId: vi.fn().mockReturnValue('proj-101'),
            getClientUserAgent: vi.fn().mockReturnValue('test-agent/1.0'),
            getVersion: vi.fn().mockReturnValue(2),
            ...overrides,
        }
    }

    function getIdentifyCallback(): () => Promise<unknown> {
        const call = vi.mocked(track).mock.calls[0]!
        const options = call[2] as { identify: () => Promise<unknown> }
        return options.identify
    }

    function getEventTagsCallback(): () => Promise<Record<string, string>> {
        const call = vi.mocked(track).mock.calls[0]!
        const options = call[2] as { eventTags: () => Promise<Record<string, string>> }
        return options.eventTags
    }

    function getEventPropertiesCallback(): () => Record<string, unknown> {
        const call = vi.mocked(track).mock.calls[0]!
        const options = call[2] as { eventProperties: () => Record<string, unknown> }
        return options.eventProperties
    }

    it('calls mcpcat.track with null projectId and correct options', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initMcpCatObservability(server, identity)

        expect(track).toHaveBeenCalledWith(
            server,
            null,
            expect.objectContaining({
                enableReportMissing: false,
                enableToolCallContext: false,
                enableTracing: true,
                identify: expect.any(Function),
                eventTags: expect.any(Function),
                eventProperties: expect.any(Function),
                exporters: {
                    posthog: {
                        type: 'posthog',
                        apiKey: TEST_API_KEY,
                        host: TEST_HOST,
                        enableAITracing: true,
                    },
                },
            })
        )
    })

    it('skips initialization when POSTHOG_ANALYTICS_API_KEY is not set', async () => {
        env.POSTHOG_ANALYTICS_API_KEY = undefined as unknown as string
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initMcpCatObservability(server, identity)
        expect(track).not.toHaveBeenCalled()
    })

    it('skips initialization when POSTHOG_ANALYTICS_HOST is not set', async () => {
        env.POSTHOG_ANALYTICS_HOST = undefined as unknown as string
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initMcpCatObservability(server, identity)
        expect(track).not.toHaveBeenCalled()
    })

    it('identify callback resolves identity from provider', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initMcpCatObservability(server, identity)

        const result = await getIdentifyCallback()()
        expect(result).toEqual({ userId: 'user-123' })
    })

    it('eventTags callback returns $session_id and $ai_session_id when available', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initMcpCatObservability(server, identity)

        const result = await getEventTagsCallback()()
        expect(result).toEqual({
            $session_id: 'session-uuid-456',
            $ai_session_id: 'session-uuid-456',
        })
    })

    it('eventTags callback returns empty when session uuid is undefined', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity({
            getSessionUuid: vi.fn().mockResolvedValue(undefined),
        })

        await initMcpCatObservability(server, identity)

        const result = await getEventTagsCallback()()
        expect(result).toEqual({})
    })

    it('eventProperties callback returns all metadata', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        await initMcpCatObservability(server, identity)

        const result = getEventPropertiesCallback()()
        expect(result).toEqual({
            ai_product: 'mcp',
            mcp_version: 2,
            client_user_agent: 'test-agent/1.0',
            mcp_client_name: 'claude-code',
            mcp_client_version: '1.2.3',
            mcp_protocol_version: '2024-11-05',
            mcp_region: 'us',
        })
    })

    it('eventProperties callback includes undefined values from provider', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity({
            getVersion: vi.fn().mockReturnValue(undefined),
            getClientUserAgent: vi.fn().mockReturnValue(undefined),
            getMcpClientName: vi.fn().mockReturnValue(undefined),
            getMcpClientVersion: vi.fn().mockReturnValue(undefined),
            getMcpProtocolVersion: vi.fn().mockReturnValue(undefined),
            getRegion: vi.fn().mockReturnValue(undefined),
        })

        await initMcpCatObservability(server, identity)

        const result = getEventPropertiesCallback()()
        expect(result).toEqual({
            ai_product: 'mcp',
            mcp_version: undefined,
            client_user_agent: undefined,
            mcp_client_name: undefined,
            mcp_client_version: undefined,
            mcp_protocol_version: undefined,
            mcp_region: undefined,
        })
    })

    it('swallows errors if mcpcat.track throws', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        vi.mocked(track).mockImplementationOnce(() => {
            throw new Error('mcpcat init failed')
        })

        await expect(initMcpCatObservability(server, identity)).resolves.toBeUndefined()
    })
})
