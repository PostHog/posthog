import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockCaptureToolCall, mockCaptureInitialize, mockCapture } = vi.hoisted(() => ({
    mockCaptureToolCall: vi.fn(),
    mockCaptureInitialize: vi.fn(),
    // Raw `capture`; must never be used for the retired legacy `mcp_*` event names.
    mockCapture: vi.fn(),
}))

vi.mock('@/lib/posthog', () => ({
    getPostHogClient: vi.fn(() => ({
        captureToolCall: mockCaptureToolCall,
        captureInitialize: mockCaptureInitialize,
        capture: mockCapture,
    })),
}))

import { trackExecuteSqlGeneration, trackInitEvent, trackToolCall } from '@/hono/analytics'
import type { ResolvedState } from '@/hono/request-state-resolver'

function makeState(overrides: Partial<ResolvedState> = {}): ResolvedState {
    return {
        reqCtx: {
            safelyGetAnalyticsContext: vi.fn(async () => undefined),
            getSessionUuid: vi.fn(async () => 'session-uuid'),
            getEffectiveSessionUuid: vi.fn(async () => 'session-uuid'),
        } as any,
        context: {
            stateManager: {},
        } as any,
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
        scopeGatedTools: [],
        distinctId: 'distinct-id',
        renderUiEnabled: false,
        ...overrides,
    }
}

describe('Hono MCP analytics contexts', () => {
    beforeEach(() => {
        mockCaptureToolCall.mockClear()
        mockCaptureInitialize.mockClear()
        mockCapture.mockClear()
    })

    it('does not dual-emit the retired legacy mcp_tool_call / mcp_initialize names', async () => {
        // Guards against reintroducing the legacy dual-emit, which double-counted every call.
        await trackInitEvent(makeState())
        await trackToolCall('user-get', 12, false, makeState())

        expect(mockCapture).not.toHaveBeenCalled()
    })

    it('emits request properties on $mcp fields and session properties on mcp_session fields', async () => {
        await trackInitEvent(makeState())

        expect(mockCaptureInitialize).toHaveBeenCalledTimes(1)
        expect(mockCaptureInitialize.mock.calls[0]![0].properties).toMatchObject({
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

        const properties = mockCaptureToolCall.mock.calls[0]![0].properties
        expect(properties.$mcp_client_name).toBe('Claude Desktop')
        expect(properties.mcp_session_client_name).toBeUndefined()
        expect(properties.mcp_session_vendor_client).toBeUndefined()
    })

    it('stamps $mcp_tool_category from the catalogued tool definition', async () => {
        await trackToolCall('query-logs', 5, false, makeState())

        expect(mockCaptureToolCall.mock.calls[0]![0].properties.$mcp_tool_category).toBe('Logs')
    })

    it('omits $mcp_tool_category for tools without a catalogued definition', async () => {
        await trackToolCall('exec', 5, false, makeState())

        expect(mockCaptureToolCall.mock.calls[0]![0].properties).not.toHaveProperty('$mcp_tool_category')
    })

    describe('trackExecuteSqlGeneration', () => {
        it('emits an $ai_generation carrying the intent as input and the HogQL as output', async () => {
            await trackExecuteSqlGeneration(
                'execute-sql',
                { query: 'SELECT count() FROM events' },
                makeState(),
                { durationMs: 1500, isError: false },
                { intent: 'count yesterday signups' }
            )

            expect(mockCapture).toHaveBeenCalledTimes(1)
            const payload = mockCapture.mock.calls[0]![0]
            expect(payload.event).toBe('$ai_generation')
            expect(payload.distinctId).toBe('distinct-id')
            expect(payload.properties).toMatchObject({
                $ai_span_name: 'execute-sql',
                $ai_trace_id: 'session-uuid',
                $session_id: 'session-uuid',
                $ai_input: [{ role: 'user', content: 'count yesterday signups' }],
                $ai_output_choices: [{ role: 'assistant', content: 'SELECT count() FROM events' }],
                $ai_latency: 1.5,
                $ai_is_error: false,
                // Rides the same base MCP context as every other event, so
                // evaluations can condition on client/session properties.
                $mcp_client_name: 'Claude Desktop',
            })
        })

        it('flags failed calls so evaluations can target errored SQL too', async () => {
            await trackExecuteSqlGeneration('execute-sql', { query: 'SELECT bogus' }, makeState(), {
                durationMs: 200,
                isError: true,
                errorMessage: 'Unknown table',
            })

            expect(mockCapture.mock.calls[0]![0].properties).toMatchObject({
                $ai_is_error: true,
                $ai_error: 'Unknown table',
            })
        })

        it.each([
            ['a different tool', 'query-logs', { query: 'SELECT 1' }],
            ['a missing query', 'execute-sql', {}],
            ['a non-string query', 'execute-sql', { query: 42 }],
        ])('does not emit for %s', async (_case, toolName, args) => {
            await trackExecuteSqlGeneration(toolName, args, makeState(), { durationMs: 5, isError: false })

            expect(mockCapture).not.toHaveBeenCalled()
        })
    })
})
