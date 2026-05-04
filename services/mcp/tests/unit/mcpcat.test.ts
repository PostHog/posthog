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
            getVersion: vi.fn().mockResolvedValue(2),
            getOAuthClientName: vi.fn().mockResolvedValue('PostHog Code'),
            getReadOnly: vi.fn().mockResolvedValue(true),
            getTransport: vi.fn().mockResolvedValue('streamable-http'),
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

    function getEventPropertiesCallback(): () => Promise<Record<string, unknown>> {
        const call = vi.mocked(track).mock.calls[0]!
        const options = call[2] as { eventProperties: () => Promise<Record<string, unknown>> }
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

    type EventPropertiesCase = {
        name: string
        overrides: Partial<McpCatIdentityProvider>
        expected: Record<string, unknown>
    }

    it.each<EventPropertiesCase>([
        {
            name: 'full identity + full analytics context emits $groups for org + project',
            overrides: {},
            expected: {
                ai_product: 'mcp',
                mcp_version: 2,
                client_user_agent: 'test-agent/1.0',
                mcp_client_name: 'claude-code',
                mcp_client_version: '1.2.3',
                mcp_protocol_version: '2024-11-05',
                mcp_region: 'us',
                organization_id: 'org-789',
                project_id: 'proj-101',
                project_uuid: 'proj-uuid-101',
                project_name: 'Project 101',
                mcp_oauth_client_name: 'PostHog Code',
                read_only: true,
                mcp_transport: 'streamable-http',
                $groups: {
                    organization: 'org-789',
                    project: 'proj-uuid-101',
                },
            },
        },
        {
            name: 'organization-only analytics context emits a single $groups key',
            overrides: {
                getAnalyticsContext: vi.fn().mockResolvedValue({ organizationId: 'org-789' }),
            },
            expected: {
                ai_product: 'mcp',
                mcp_version: 2,
                client_user_agent: 'test-agent/1.0',
                mcp_client_name: 'claude-code',
                mcp_client_version: '1.2.3',
                mcp_protocol_version: '2024-11-05',
                mcp_region: 'us',
                organization_id: 'org-789',
                project_id: undefined,
                project_uuid: undefined,
                project_name: undefined,
                mcp_oauth_client_name: 'PostHog Code',
                read_only: true,
                mcp_transport: 'streamable-http',
                $groups: { organization: 'org-789' },
            },
        },
        {
            name: 'no analytics context omits $groups entirely',
            overrides: {
                getVersion: vi.fn().mockResolvedValue(undefined),
                getClientUserAgent: vi.fn().mockResolvedValue(undefined),
                getMcpClientName: vi.fn().mockResolvedValue(undefined),
                getMcpClientVersion: vi.fn().mockResolvedValue(undefined),
                getMcpProtocolVersion: vi.fn().mockResolvedValue(undefined),
                getRegion: vi.fn().mockResolvedValue(undefined),
                getAnalyticsContext: vi.fn().mockResolvedValue(undefined),
                getOAuthClientName: vi.fn().mockResolvedValue(undefined),
                getReadOnly: vi.fn().mockResolvedValue(undefined),
                getTransport: vi.fn().mockResolvedValue(undefined),
            },
            expected: {
                ai_product: 'mcp',
                mcp_version: undefined,
                client_user_agent: undefined,
                mcp_client_name: undefined,
                mcp_client_version: undefined,
                mcp_protocol_version: undefined,
                mcp_region: undefined,
                organization_id: undefined,
                project_id: undefined,
                project_uuid: undefined,
                project_name: undefined,
                mcp_oauth_client_name: undefined,
                read_only: undefined,
                mcp_transport: undefined,
            },
        },
    ])('eventProperties: $name', async ({ overrides, expected }) => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity(overrides)

        await initMcpCatObservability(server, identity)

        const result = await getEventPropertiesCallback()()
        expect(result).toEqual(expected)
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
