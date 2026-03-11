import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { track } from 'mcpcat'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { initMcpCatObservability, type McpCatIdentityProvider } from '@/lib/mcpcat'

describe('initMcpCatObservability', () => {
    beforeEach(() => {
        vi.mocked(track).mockClear()
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

    it('calls mcpcat.track with null projectId and correct options', () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        initMcpCatObservability(server, identity)

        expect(track).toHaveBeenCalledWith(
            server,
            null,
            expect.objectContaining({
                enableReportMissing: false,
                enableToolCallContext: false,
                enableTracing: true,
                identify: expect.any(Function),
                exporters: {
                    posthog: {
                        type: 'posthog',
                        apiKey: 'sTMFPsFhdP1Ssg',
                        host: 'https://us.i.posthog.com',
                    },
                },
            })
        )
    })

    function getIdentifyCallback(): () => Promise<unknown> {
        const call = vi.mocked(track).mock.calls[0]!
        const options = call[2] as { identify: () => Promise<unknown> }
        return options.identify
    }

    it('identify callback resolves identity from provider', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        initMcpCatObservability(server, identity)

        const result = await getIdentifyCallback()()

        expect(result).toEqual({
            userId: 'user-123',
            userData: {
                $session_id: 'session-uuid-456',
                mcp_client_name: 'claude-code',
                mcp_client_version: '1.2.3',
                mcp_protocol_version: '2024-11-05',
                region: 'us',
                organization_id: 'org-789',
                project_id: 'proj-101',
                client_user_agent: 'test-agent/1.0',
                mcp_version: 2,
            },
        })
    })

    it('identify callback skips undefined properties in userData', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity({
            getSessionUuid: vi.fn().mockResolvedValue(undefined),
            getMcpClientName: vi.fn().mockReturnValue(undefined),
            getMcpClientVersion: vi.fn().mockReturnValue(undefined),
            getMcpProtocolVersion: vi.fn().mockReturnValue(undefined),
            getRegion: vi.fn().mockReturnValue(undefined),
            getOrganizationId: vi.fn().mockReturnValue(undefined),
            getProjectId: vi.fn().mockReturnValue(undefined),
            getClientUserAgent: vi.fn().mockReturnValue(undefined),
            getVersion: vi.fn().mockReturnValue(undefined),
        })

        initMcpCatObservability(server, identity)

        const result = await getIdentifyCallback()()

        expect(result).toEqual({
            userId: 'user-123',
            userData: {},
        })
    })

    it('identify callback returns null when provider throws', async () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity({
            getDistinctId: vi.fn().mockRejectedValue(new Error('auth failed')),
        })

        initMcpCatObservability(server, identity)

        const result = await getIdentifyCallback()()

        expect(result).toBeNull()
    })

    it('swallows errors if mcpcat.track throws', () => {
        const server = new McpServer({ name: 'test', version: '1.0.0' })
        const identity = createMockIdentity()

        vi.mocked(track).mockImplementationOnce(() => {
            throw new Error('mcpcat init failed')
        })

        expect(() => initMcpCatObservability(server, identity)).not.toThrow()
    })
})
