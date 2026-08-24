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

import { trackExecuteSqlGeneration, trackInitEvent, trackToolCall, trackToolSpan } from '@/hono/analytics'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { MAX_CAPTURED_DESCRIPTION_LENGTH, getToolDefinition } from '@/tools/toolDefinitions'

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
        oauthClientId: undefined,
        clientProfile: {} as any,
        requestContext: {
            authMethod: 'personal_api_key',
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
        gatewayToolsEnabled: false,
        distinctId: 'distinct-id',
        renderUiEnabled: false,
        metadata: undefined,
        metadataCompact: undefined,
        groupTypes: undefined,
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
            $mcp_auth_method: 'personal_api_key',
            mcp_vendor_client: 'ClaudeAI',
            mcp_session_client_name: 'claude-code',
            mcp_session_client_version: '1.0',
            mcp_session_protocol_version: '2025-03-26',
            mcp_session_consumer: 'session-consumer',
            mcp_session_vendor_client: 'ClaudeCode',
        })
    })

    it('stamps the surface as `source` so MCP events join product events', async () => {
        // Without it, $mcp_* events carry no `source` at all and sit outside the breakdown
        // that measures MCP adoption. The resolution matrix itself is covered in
        // tests/event-source.test.ts — this only proves the property reaches the event.
        await trackToolCall(
            'user-get',
            12,
            false,
            makeState({
                apiKeyScopes: ['insight:read', 'internal_run:read'],
                requestContext: { ...makeState().requestContext, mcpConsumer: 'slack' },
            })
        )

        expect(mockCaptureToolCall.mock.calls[0]![0].properties.source).toBe('slack')
    })

    it('omits session properties when there is no MCP session context', async () => {
        await trackToolCall('user-get', 12, false, makeState({ sessionContext: null }))

        const properties = mockCaptureToolCall.mock.calls[0]![0].properties
        expect(properties.$mcp_client_name).toBe('Claude Desktop')
        expect(properties.mcp_session_client_name).toBeUndefined()
        expect(properties.mcp_session_vendor_client).toBeUndefined()
    })

    it('categorizes a proxied third-party tool and names its server', async () => {
        // A gateway tool has no catalog entry, so without the fallback it lands
        // uncategorized and disappears from every category-sliced view.
        await trackToolCall('linear__create_issue', 12, false, makeState())

        const properties = mockCaptureToolCall.mock.calls[0]![0].properties
        expect(properties.$mcp_tool_category).toBe('Third-party tools')
        expect(properties.mcp_gateway_server).toBe('linear')
    })

    it('leaves a PostHog tool without a gateway server', async () => {
        await trackToolCall('user-get', 12, false, makeState())

        expect(mockCaptureToolCall.mock.calls[0]![0].properties.mcp_gateway_server).toBeUndefined()
    })

    describe('client identity live-first fallback', () => {
        // $mcp_client_name is the property this whole fix targets: `clientInfo` arrives
        // only on `initialize`, so it was empty on every tool call that followed. The
        // same live-first-then-session precedence applies to every field a live request
        // can carry.
        it.each([
            ['$mcp_client_name', 'mcpClientName'],
            ['$mcp_client_version', 'mcpClientVersion'],
            ['$mcp_protocol_version', 'mcpProtocolVersion'],
            ['$mcp_consumer', 'mcpConsumer'],
            ['mcp_vendor_client', 'mcpVendorClient'],
        ] as const)(
            '%s: live value wins when both live and session values are present',
            async (eventProp, contextField) => {
                const state = makeState({
                    requestContext: { ...makeState().requestContext, [contextField]: 'live-value' },
                    sessionContext: { ...makeState().sessionContext, [contextField]: 'session-value' },
                })
                await trackToolCall('user-get', 12, false, state)

                expect(mockCaptureToolCall.mock.calls[0]![0].properties[eventProp]).toBe('live-value')
            }
        )

        it.each([
            ['$mcp_client_name', 'mcpClientName'],
            ['$mcp_client_version', 'mcpClientVersion'],
            ['$mcp_protocol_version', 'mcpProtocolVersion'],
            ['$mcp_consumer', 'mcpConsumer'],
            ['mcp_vendor_client', 'mcpVendorClient'],
        ] as const)(
            '%s: falls back to the session-pinned value when the live request has none (the tools/call case)',
            async (eventProp, contextField) => {
                const state = makeState({
                    requestContext: { ...makeState().requestContext, [contextField]: undefined },
                    sessionContext: { ...makeState().sessionContext, [contextField]: 'session-value' },
                })
                await trackToolCall('user-get', 12, false, state)

                expect(mockCaptureToolCall.mock.calls[0]![0].properties[eventProp]).toBe('session-value')
            }
        )

        it.each([
            ['$mcp_client_name', 'mcpClientName'],
            ['$mcp_client_version', 'mcpClientVersion'],
            ['$mcp_protocol_version', 'mcpProtocolVersion'],
            ['$mcp_consumer', 'mcpConsumer'],
            ['mcp_vendor_client', 'mcpVendorClient'],
        ] as const)(
            '%s: stays undefined (never an empty string) when both live and session values are absent',
            async (eventProp, contextField) => {
                const state = makeState({
                    requestContext: { ...makeState().requestContext, [contextField]: undefined },
                    sessionContext: { ...makeState().sessionContext, [contextField]: undefined },
                })
                await trackToolCall('user-get', 12, false, state)

                expect(mockCaptureToolCall.mock.calls[0]![0].properties[eventProp]).toBeUndefined()
            }
        )

        it('initialize with no session context is unchanged: live request value is used as-is', async () => {
            await trackInitEvent(makeState({ sessionContext: null }))

            expect(mockCaptureInitialize.mock.calls[0]![0].properties).toMatchObject({
                $mcp_client_name: 'Claude Desktop',
                $mcp_client_version: '2.0',
                $mcp_protocol_version: '2025-03-26',
                $mcp_consumer: 'request-consumer',
                mcp_vendor_client: 'ClaudeAI',
            })
        })

        it('initialize with no session context and no live value stays undefined', async () => {
            const state = makeState({
                sessionContext: null,
                requestContext: { ...makeState().requestContext, mcpClientName: undefined },
            })
            await trackInitEvent(state)

            expect(mockCaptureInitialize.mock.calls[0]![0].properties.$mcp_client_name).toBeUndefined()
        })

        it.each([
            ['$mcp_client_user_agent', 'clientUserAgent'],
            ['$mcp_transport', 'transport'],
            ['$mcp_session_id', 'mcpSessionId'],
            ['$mcp_conversation_id', 'mcpConversationId'],
            ['$mcp_mode', 'mode'],
            ['$mcp_region', 'region'],
        ] as const)(
            '%s is per-request only: it stays undefined even when the live request has none, regardless of session context',
            async (eventProp, contextField) => {
                const state = makeState({
                    requestContext: { ...makeState().requestContext, [contextField]: undefined },
                })
                await trackToolCall('user-get', 12, false, state)

                expect(mockCaptureToolCall.mock.calls[0]![0].properties[eventProp]).toBeUndefined()
            }
        )

        it('mcp_runtime is a static constant, unaffected by request or session context', async () => {
            await trackToolCall('user-get', 12, false, makeState())

            expect(mockCaptureToolCall.mock.calls[0]![0].properties.mcp_runtime).toBe('hono')
        })
    })

    it('stamps $mcp_tool_category and $mcp_tool_description from the catalogued tool definition', async () => {
        await trackToolCall('query-logs', 5, false, makeState())

        const properties = mockCaptureToolCall.mock.calls[0]![0].properties
        expect(properties.$mcp_tool_category).toBe('Logs')
        // query-logs' catalogued description is ~13 KB, so this assertion also locks in
        // the capture-side clip. Description capture died silently once before (the hono
        // migration dropped it while the category stamp survived), so the two are asserted
        // together at the same call site.
        expect(properties.$mcp_tool_description).toBe(
            getToolDefinition('query-logs').description.slice(0, MAX_CAPTURED_DESCRIPTION_LENGTH)
        )
        expect((properties.$mcp_tool_description as string).length).toBe(MAX_CAPTURED_DESCRIPTION_LENGTH)
    })

    it('omits $mcp_tool_category and $mcp_tool_description for tools without a catalogued definition', async () => {
        await trackToolCall('exec', 5, false, makeState())

        expect(mockCaptureToolCall.mock.calls[0]![0].properties).not.toHaveProperty('$mcp_tool_category')
        expect(mockCaptureToolCall.mock.calls[0]![0].properties).not.toHaveProperty('$mcp_tool_description')
    })

    it('prefers the served description over the catalog text, clipped', async () => {
        // execute-sql advertises a per-request formatted description, so stamping
        // the catalog text would record words the agent never saw.
        const served = 'served '.repeat(200)
        await trackToolCall('query-logs', 5, false, makeState(), undefined, undefined, served)

        const properties = mockCaptureToolCall.mock.calls[0]![0].properties
        expect(properties.$mcp_tool_description).toBe(served.slice(0, MAX_CAPTURED_DESCRIPTION_LENGTH))
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

    describe('trackToolSpan', () => {
        it.each([
            ['a non-execute-sql tool', 'data-catalog-metric-run', { name: 'mrr' }, true],
            ['any other non-execute-sql tool', 'query-logs', { query: 'SELECT 1' }, true],
            [
                'execute-sql querying metadata',
                'execute-sql',
                { query: 'SELECT name FROM system.information_schema.metrics' },
                true,
            ],
            ['execute-sql on plain data', 'execute-sql', { query: 'SELECT count() FROM events' }, false],
            [
                'execute-sql with the marker only in a string literal',
                'execute-sql',
                { query: "SELECT distinct_id FROM events WHERE 'information_schema' != ''" },
                false,
            ],
            [
                'execute-sql with the marker only in a comment',
                'execute-sql',
                { query: 'SELECT count() FROM events -- information_schema' },
                false,
            ],
            // A proxied vendor tool's args and result are the customer's content passing
            // through the gateway. Key-based redaction only catches credential-shaped
            // fields, so capturing the payload would put arbitrary third-party content in
            // analytics to serve evaluations that target PostHog's own tools.
            ['a proxied third-party tool', 'linear__create_issue', { title: 'Customer escalation' }, false],
        ])('gates capture for %s', async (_case, toolName, input, captured) => {
            await trackToolSpan(toolName, makeState(), { durationMs: 100, isError: false, input, output: 'rows' })

            const spanCalls = mockCapture.mock.calls.filter(([payload]) => payload.event === '$ai_span')
            expect(spanCalls).toHaveLength(captured ? 1 : 0)
        })

        it('joins the MCP session trace and truncates oversized results', async () => {
            await trackToolSpan('data-catalog-metric-run', makeState(), {
                durationMs: 1500,
                isError: false,
                input: { name: 'mrr' },
                output: 'x'.repeat(50_000),
            })

            const payload = mockCapture.mock.calls[0]![0]
            expect(payload.event).toBe('$ai_span')
            expect(payload.properties).toMatchObject({
                $ai_span_name: 'data-catalog-metric-run',
                // Must match the execute-sql generations' trace id, or the span
                // detaches from the session trace evaluations are scoped to.
                $ai_trace_id: 'session-uuid',
                $session_id: 'session-uuid',
                $ai_input_state: JSON.stringify({ name: 'mrr' }),
                $ai_latency: 1.5,
                $ai_is_error: false,
                $mcp_tool_category: 'Data catalog',
            })
            expect(payload.properties.$ai_output_state).toHaveLength(30_000)
        })

        it('records the error message on failed calls', async () => {
            await trackToolSpan('data-catalog-metric-run', makeState(), {
                durationMs: 200,
                isError: true,
                errorMessage: 'metric not found',
                input: { name: 'bogus' },
            })

            expect(mockCapture.mock.calls[0]![0].properties).toMatchObject({
                $ai_is_error: true,
                $ai_error: 'metric not found',
            })
        })

        it('redacts secret-bearing fields from captured input and output', async () => {
            // Capturing every tool by default would otherwise land user-settings /
            // warehouse-source credentials in telemetry.
            await trackToolSpan('user-settings-update', makeState(), {
                durationMs: 100,
                isError: false,
                input: { first_name: 'Ada', password: 'hunter2', payload: { client_secret: 'oauth-secret' } },
                output: { id: 1, api_key: 'phx_live_123' },
            })

            const { $ai_input_state, $ai_output_state } = mockCapture.mock.calls[0]![0].properties
            expect(JSON.parse($ai_input_state)).toEqual({
                first_name: 'Ada',
                password: '[redacted]',
                payload: { client_secret: '[redacted]' },
            })
            expect(JSON.parse($ai_output_state)).toEqual({ id: 1, api_key: '[redacted]' })
        })

        // Redaction is key-name based, so a source whose credential field the
        // pattern does not name ships that credential verbatim. Cloudflare's
        // `api_token` did exactly that. These are real field names from
        // products/warehouse_sources/.../sources/*/source.py, paired with the
        // metadata and token-count fields the pattern must keep readable.
        it.each([
            ['api_token', true],
            ['database_token', true],
            ['consumer_key', true],
            ['signing_key', true],
            ['key_file', true],
            ['keypair', true],
            ['token', true],
            ['client_secret', true],
            ['connection_string', true],
            ['client_certificate', true],
            ['app_id', true],
            ['api_id', true],
            ['basic_auth_username', true],
            ['username', true],
            ['server_client_root_ca', false],
            ['token_id', false],
            ['token_url', false],
            ['app_tokens', false],
            ['input_tokens', false],
        ])('redacts %s: %s', async (field, redacted) => {
            await trackToolSpan('external-data-sources-create', makeState(), {
                durationMs: 100,
                isError: false,
                input: { payload: { [field]: 'sensitive-value' } },
            })

            const { $ai_input_state } = mockCapture.mock.calls[0]![0].properties
            expect(JSON.parse($ai_input_state).payload[field]).toBe(redacted ? '[redacted]' : 'sensitive-value')
        })
    })
})
