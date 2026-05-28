import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockCapture } = vi.hoisted(() => ({
    mockCapture: vi.fn(),
}))

vi.mock('@/lib/posthog', () => ({
    getPostHogClient: vi.fn(() => ({
        capture: mockCapture,
    })),
}))

import { trackInitEvent, trackToolCall } from '@/hono/analytics'
import type { ResolvedState } from '@/hono/request-state-resolver'

function makeState(overrides: Partial<ResolvedState> = {}): ResolvedState {
    return {
        reqCtx: {
            getAnalyticsContextSafe: vi.fn(async () => undefined),
            getSessionUuid: vi.fn(async () => 'session-uuid'),
        } as any,
        context: {
            stateManager: {},
        } as any,
        version: 2,
        useSingleExec: true,
        toolFeatureFlags: undefined,
        apiKeyScopes: [],
        clientProfile: {} as any,
        requestContext: {
            sessionId: 'sess-1',
            organizationId: 'org-request',
            projectId: 'project-request',
            readOnly: true,
            viaSseRedirect: true,
            requestStartTime: Date.now(),
            clientUserAgent: 'request-agent/1.0',
            mcpClientName: 'Claude Desktop',
            mcpClientVersion: '2.0',
            mcpProtocolVersion: '2025-03-26',
            transport: 'streamable-http',
            mcpSessionId: 'mcp-session-request',
            mcpConversationId: 'conversation-request',
            mcpConsumer: 'request-consumer',
            mode: 'cli',
            region: 'us',
            mcpVendorClient: 'ClaudeAI',
        },
        sessionContext: {
            mcpClientName: 'claude-code',
            mcpClientVersion: '1.0',
            mcpProtocolVersion: '2025-03-26',
            mcpConsumer: 'session-consumer',
            mcpVendorClient: 'ClaudeCode',
        },
        allTools: [],
        distinctId: 'distinct-id',
        ...overrides,
    }
}

describe('Hono MCP analytics contexts', () => {
    beforeEach(() => {
        mockCapture.mockClear()
    })

    it('emits request properties on $mcp fields and session properties on mcp_session fields', async () => {
        await trackInitEvent(makeState())

        expect(mockCapture).toHaveBeenCalledTimes(1)
        expect(mockCapture.mock.calls[0]![0].properties).toMatchObject({
            $mcp_client_name: 'Claude Desktop',
            $mcp_client_version: '2.0',
            $mcp_client_user_agent: 'request-agent/1.0',
            $mcp_protocol_version: '2025-03-26',
            $mcp_transport: 'streamable-http',
            $mcp_session_id: 'mcp-session-request',
            $mcp_conversation_id: 'conversation-request',
            $mcp_consumer: 'request-consumer',
            $mcp_mode: 'cli',
            $mcp_region: 'us',
            mcp_vendor_client: 'ClaudeAI',
            mcp_session_client_name: 'claude-code',
            mcp_session_client_version: '1.0',
            mcp_session_protocol_version: '2025-03-26',
            mcp_session_consumer: 'session-consumer',
            mcp_session_vendor_client: 'ClaudeCode',
        })
    })

    it('omits session properties when there is no MCP session context', async () => {
        await trackToolCall('user-get', 12, false, makeState({ sessionContext: null }))

        const properties = mockCapture.mock.calls[0]![0].properties
        expect(properties.$mcp_client_name).toBe('Claude Desktop')
        expect(properties.mcp_session_client_name).toBeUndefined()
        expect(properties.mcp_session_vendor_client).toBeUndefined()
    })
})
