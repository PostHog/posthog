import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockToolCallsInc, mockToolDurationObserve, mockToolDurationStartTimer, mockToolErrorsInc } = vi.hoisted(() => {
    const mockStop = vi.fn()
    return {
        mockToolCallsInc: vi.fn(),
        mockToolDurationObserve: vi.fn(),
        mockToolDurationStartTimer: vi.fn(() => mockStop),
        mockToolErrorsInc: vi.fn(),
    }
})

vi.mock('@/hono/metrics', () => ({
    toolCallsTotal: { inc: mockToolCallsInc },
    toolCallDurationSeconds: {
        observe: mockToolDurationObserve,
        startTimer: mockToolDurationStartTimer,
    },
    toolErrorsTotal: { inc: mockToolErrorsInc },
}))

vi.mock('@/hono/analytics', () => ({
    trackToolCall: vi.fn(),
    trackExecuteSqlGeneration: vi.fn(),
    trackToolSpan: vi.fn(),
}))

vi.mock('@/resources/internals', () => ({
    fetchContextMillResources: vi.fn().mockRejectedValue(new Error('mocked')),
    filterValidEntries: vi.fn().mockReturnValue([]),
    loadManifestFromArchive: vi.fn().mockReturnValue({ resources: [] }),
    clearResourceCache: vi.fn(),
}))

vi.mock('@/resources', () => ({
    getPromptsFromManifest: vi.fn().mockResolvedValue([]),
}))

import { z } from 'zod'

import { trackToolCall } from '@/hono/analytics'
import { InstructionsBuilder } from '@/hono/instructions'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { ToolCatalog } from '@/hono/tool-catalog'
import { ToolExecutor } from '@/hono/tool-executor'
import {
    PostHogApiError,
    PostHogRateLimitError,
    PostHogValidationError,
    ToolInputValidationError,
    wrapError,
} from '@/lib/errors'

const mockTrackToolCall = vi.mocked(trackToolCall)

/** Extra-properties bag passed to the 5th arg of `trackToolCall` for a given tool. */
function trackToolCallExtras(tool: string): Record<string, unknown> | undefined {
    const call = mockTrackToolCall.mock.calls.find((c) => c[0] === tool)
    return call?.[4]
}

function makeState(tools: { name: string }[], overrides: Partial<ResolvedState> = {}): ResolvedState {
    return {
        reqCtx: {
            cache: { get: vi.fn(), set: vi.fn() },
            safelyGetAnalyticsContext: vi.fn().mockResolvedValue(undefined),
            trackEvent: vi.fn(),
            trackContextSwitchEvent: vi.fn(),
            getSessionUuid: vi.fn().mockResolvedValue(undefined),
            getEffectiveSessionUuid: vi.fn().mockResolvedValue(undefined),
        } as any,
        context: {
            api: {},
            cache: {},
            env: {},
            stateManager: {},
            sessionManager: {},
            getDistinctId: vi.fn(),
            trackEvent: vi.fn(),
        } as any,
        useSingleExec: false,
        toolFeatureFlags: undefined,
        apiKeyScopes: [],
        oauthClientId: undefined,
        clientProfile: {
            capabilities: { supportsInstructions: true },
            isCliModeEnabled: vi.fn(() => false),
            isClaudeUiHost: vi.fn(() => false),
            isInlineExecUiHost: vi.fn(() => false),
            isClaudeChatHost: vi.fn(() => false),
        } as any,
        requestContext: {
            authMethod: 'personal_api_key',
            sessionId: 'sess-1',
            mcpClientName: 'test',
            mcpClientVersion: '1.0',
            mcpProtocolVersion: '2025-03-26',
            transport: 'streamable-http',
        },
        sessionContext: null,
        allTools: tools as any,
        scopeGatedTools: [],
        gatewayToolsEnabled: false,
        distinctId: 'test-distinct-id',
        renderUiEnabled: false,
        metadata: undefined,
        metadataCompact: undefined,
        groupTypes: undefined,
        ...overrides,
    }
}

function makeFakeTool(
    name: string,
    handler: () => Promise<unknown> = async () => 'ok'
): {
    name: string
    base: { schema: z.ZodObject<Record<string, never>>; handler: ReturnType<typeof vi.fn>; _meta: undefined }
} {
    return {
        name,
        base: {
            schema: z.object({}),
            handler: vi.fn().mockImplementation(handler),
            _meta: undefined,
        },
    }
}

function callsFor(mock: ReturnType<typeof vi.fn>, tool: string): any[] {
    return mock.mock.calls.filter((c: any[]) => c[0]?.tool === tool).map((c: any[]) => c[0])
}

describe('ToolExecutor metrics', () => {
    let catalog: ToolCatalog
    let executor: ToolExecutor

    beforeEach(async () => {
        mockToolCallsInc.mockClear()
        mockToolDurationObserve.mockClear()
        mockToolDurationStartTimer.mockClear()
        mockToolErrorsInc.mockClear()
        mockTrackToolCall.mockClear()

        catalog = new ToolCatalog()
        await catalog.warmup()
        executor = new ToolExecutor(catalog, new InstructionsBuilder(''))
    })

    describe('direct tool calls', () => {
        it('records success counter and duration timer', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(makeFakeTool('my-tool') as any)

            await executor.handleToolCall({ name: 'my-tool', arguments: {} }, makeState([{ name: 'my-tool' }]))

            expect(mockToolDurationStartTimer).toHaveBeenCalledWith({ tool: 'my-tool' })
            expect(mockToolCallsInc).toHaveBeenCalledWith({ tool: 'my-tool', status: 'success' })
            expect(mockToolDurationStartTimer.mock.results[0]!.value).toHaveBeenCalledWith({ status: 'success' })
        })

        it('records error counter, duration timer, and error classification on failure', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(
                makeFakeTool('fail-tool', async () => {
                    throw new Error('boom')
                }) as any
            )

            await executor.handleToolCall({ name: 'fail-tool', arguments: {} }, makeState([{ name: 'fail-tool' }]))

            expect(mockToolCallsInc).toHaveBeenCalledWith({ tool: 'fail-tool', status: 'error' })
            expect(mockToolErrorsInc).toHaveBeenCalledWith({ tool: 'fail-tool', error_type: 'internal' })
            expect(mockToolDurationStartTimer.mock.results[0]!.value).toHaveBeenCalledWith({ status: 'error' })
        })

        it('stamps $mcp_error_type on the analytics event so the dashboard can slice failures by reason', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(
                makeFakeTool('fail-tool', async () => {
                    throw new Error('boom')
                }) as any
            )

            await executor.handleToolCall({ name: 'fail-tool', arguments: {} }, makeState([{ name: 'fail-tool' }]))

            expect(trackToolCallExtras('fail-tool')).toMatchObject({ $mcp_error_type: 'internal' })
        })

        // $mcp_error_message is readable by every analytics viewer in the project, not just
        // the caller that received the tool result — so only messages whose shape WE control
        // are captured. Arbitrary thrown values echo caller input (document previews, SQL
        // fragments, upstream response bodies) and must never reach analytics.
        it.each([
            ['a generic Error', new Error('preview of caller document: SECRET=abc123')],
            ['a thrown string', 'raw string echoing tool input'],
            ['a non-Error object', { secret_payload: 'do not capture' }],
        ])('omits $mcp_error_message when the tool throws %s', async (_label, thrown) => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(
                makeFakeTool('fail-tool', async () => {
                    throw thrown
                }) as any
            )

            await executor.handleToolCall({ name: 'fail-tool', arguments: {} }, makeState([{ name: 'fail-tool' }]))

            const extras = trackToolCallExtras('fail-tool')
            expect(extras).toMatchObject({ $mcp_error_type: 'internal' })
            expect(extras).not.toHaveProperty('$mcp_error_message')
            expect(extras).not.toHaveProperty('$mcp_error_code')
            expect(extras).not.toHaveProperty('$mcp_error_field')
        })

        // The code and normalized field path are what make leaf failure modes measurable:
        // $mcp_error_message is free text, so dashboards can't group on it, and the raw
        // attr fragments per array index ("actions__0__...", "actions__3__...").
        it('stamps $mcp_error_code and index-normalized $mcp_error_field for a PostHogValidationError', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(
                makeFakeTool('fail-tool', async () => {
                    throw new PostHogValidationError({
                        detail: "Email input must contain a 'from' property",
                        attr: 'actions__2__inputs__email',
                        code: 'invalid_input',
                        extra: undefined,
                        url: 'https://us.posthog.com/api/environments/2/hog_flows/',
                        method: 'POST',
                    })
                }) as any
            )

            await executor.handleToolCall({ name: 'fail-tool', arguments: {} }, makeState([{ name: 'fail-tool' }]))

            const extras = trackToolCallExtras('fail-tool')
            expect(extras).toMatchObject({
                $mcp_error_type: 'validation',
                $mcp_error_code: 'invalid_input',
                $mcp_error_field: 'actions__N__inputs__email',
            })
            // The detail body echoes caller input, so it must never ride along.
            expect(JSON.stringify(extras)).not.toContain("'from' property")
        })

        it.each([
            [
                'a ToolInputValidationError (value-free field descriptors)',
                new ToolInputValidationError('Invalid input for tool: date_from (invalid_type)', {
                    fields: ['date_from'],
                }),
                'Invalid input for tool: date_from (invalid_type)',
            ],
            [
                'a PostHogValidationError (controlled code + field only, never the detail body)',
                new PostHogValidationError({
                    // detail echoes the caller's offending expression; a query tool caller can
                    // hide a secret here, so it must never reach analytics.
                    detail: 'Unable to resolve field: SECRET=sk_live_abc123',
                    attr: 'query',
                    code: 'invalid_input',
                    extra: undefined,
                    url: 'https://us.posthog.com/api/environments/2/query/',
                    method: 'POST',
                }),
                'Validation error: invalid_input (field: query)',
            ],
            [
                'a TimeoutError',
                Object.assign(new Error('deadline of 30000ms exceeded while calling https://internal.example'), {
                    name: 'TimeoutError',
                }),
                'Tool call timed out',
            ],
        ])('stamps $mcp_error_message for %s', async (_label, thrown, expected) => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(
                makeFakeTool('fail-tool', async () => {
                    throw thrown
                }) as any
            )

            await executor.handleToolCall({ name: 'fail-tool', arguments: {} }, makeState([{ name: 'fail-tool' }]))

            expect(trackToolCallExtras('fail-tool')).toMatchObject({ $mcp_error_message: expected })
        })

        // An API-layer rejection used to carry no structured field, so it was only
        // reachable by string-parsing $mcp_error_message. It now populates the same
        // property a local schema rejection does — the API's free-text `detail` still
        // never reaches analytics.
        it('stamps $mcp_validation_fields for an API validation error, without the detail body', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(
                makeFakeTool('fail-tool', async () => {
                    throw new PostHogValidationError({
                        detail: 'Unable to resolve field: SECRET=sk_live_abc123',
                        attr: 'series.0.event',
                        code: 'invalid_input',
                        extra: undefined,
                        url: 'https://us.posthog.com/api/environments/2/query/',
                        method: 'POST',
                    })
                }) as any
            )

            await executor.handleToolCall({ name: 'fail-tool', arguments: {} }, makeState([{ name: 'fail-tool' }]))

            const extras = trackToolCallExtras('fail-tool')
            expect(extras).toMatchObject({
                $mcp_error_type: 'validation',
                // Array indices collapse here too, matching the schema path.
                $mcp_validation_fields: ['series.N.event:invalid_input'],
            })
            expect(JSON.stringify(extras)).not.toContain('sk_live_abc123')
        })

        it('rebuilds PostHogApiError messages from status + path, never the response body or query string', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(
                makeFakeTool('fail-tool', async () => {
                    throw new PostHogApiError({
                        status: 502,
                        statusText: 'Bad Gateway',
                        body: '{"secret": "upstream response body must not leak"}',
                        url: 'https://us.posthog.com/api/environments/2/insights/?token=sk_live_secret',
                        method: 'GET',
                    })
                }) as any
            )

            await executor.handleToolCall({ name: 'fail-tool', arguments: {} }, makeState([{ name: 'fail-tool' }]))

            expect(trackToolCallExtras('fail-tool')).toMatchObject({
                $mcp_error_message: 'HTTP 502 Bad Gateway on GET /api/environments/2/insights/',
            })
        })

        it('truncates $mcp_error_message and strips control characters, keeping newlines', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(
                makeFakeTool('fail-tool', async () => {
                    // ToolInputValidationError.message is passed through verbatim, so it exercises
                    // the sanitizer/truncation path in extractErrorMessage.
                    throw new ToolInputValidationError(`line2\x00\x08${'x'.repeat(3000)}`, { fields: ['date_from'] })
                }) as any
            )

            await executor.handleToolCall({ name: 'fail-tool', arguments: {} }, makeState([{ name: 'fail-tool' }]))

            const message = trackToolCallExtras('fail-tool')?.$mcp_error_message as string
            expect(message.startsWith('line2xxx')).toBe(true)
            expect(message).toHaveLength(2048)
        })

        it('carries the upstream status alongside the error type for API failures', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(
                makeFakeTool('execute-sql', async () => {
                    throw new PostHogRateLimitError({
                        body: '{}',
                        url: 'https://us.posthog.com/api/environments/2/mcp_tools/execute_sql/',
                        method: 'POST',
                        retryAfterSeconds: 5,
                    })
                }) as any
            )

            await executor.handleToolCall({ name: 'execute-sql', arguments: {} }, makeState([{ name: 'execute-sql' }]))

            expect(trackToolCallExtras('execute-sql')).toMatchObject({
                $mcp_error_type: 'rate_limited',
                $mcp_error_status: 429,
                // Subclasses of PostHogApiError get the same rebuilt-safe message shape.
                $mcp_error_message: 'HTTP 429 Too Many Requests on POST /api/environments/2/mcp_tools/execute_sql/',
            })
        })

        it('classifies a downstream 429 as rate_limited, keeping it out of the error rate', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(
                makeFakeTool('execute-sql', async () => {
                    throw new PostHogRateLimitError({
                        body: '{}',
                        url: 'https://us.posthog.com/api/environments/2/mcp_tools/execute_sql/',
                        method: 'POST',
                        retryAfterSeconds: 5,
                    })
                }) as any
            )

            await executor.handleToolCall({ name: 'execute-sql', arguments: {} }, makeState([{ name: 'execute-sql' }]))

            expect(mockToolErrorsInc).toHaveBeenCalledWith({ tool: 'execute-sql', error_type: 'rate_limited' })
        })

        it('classifies a 429 wrapped in a cause chain as rate_limited', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(
                makeFakeTool('execute-sql', async () => {
                    throw wrapError(
                        'Failed to run query',
                        new PostHogRateLimitError({
                            body: '{}',
                            url: 'https://us.posthog.com/api/environments/2/mcp_tools/execute_sql/',
                            method: 'POST',
                            retryAfterSeconds: null,
                        })
                    )
                }) as any
            )

            await executor.handleToolCall({ name: 'execute-sql', arguments: {} }, makeState([{ name: 'execute-sql' }]))

            expect(mockToolErrorsInc).toHaveBeenCalledWith({ tool: 'execute-sql', error_type: 'rate_limited' })
        })

        it('records validation_error without starting a timer', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue({
                name: 'strict-tool',
                base: { schema: z.object({ required_field: z.string() }), handler: vi.fn(), _meta: undefined },
            } as any)

            await executor.handleToolCall({ name: 'strict-tool', arguments: {} }, makeState([{ name: 'strict-tool' }]))

            expect(mockToolCallsInc).toHaveBeenCalledWith({ tool: 'strict-tool', status: 'validation_error' })
            expect(mockToolDurationStartTimer).not.toHaveBeenCalled()
        })

        // The direct path used to return before tracking, so a schema rejection in
        // 'tools' mode produced no `$mcp_tool_call` at all — leaving every
        // exec-vs-direct error comparison silently flattering direct mode. Pin both
        // the event and the value-free diagnostics that make it actionable.
        it('emits an errored analytics event with the rejected fields on a schema rejection', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue({
                name: 'strict-tool',
                base: { schema: z.object({ required_field: z.string() }), handler: vi.fn(), _meta: undefined },
            } as any)

            await executor.handleToolCall(
                { name: 'strict-tool', arguments: { requiredField: 'sent under the wrong name' } },
                makeState([{ name: 'strict-tool' }])
            )

            // Exactly one event: the rejection returns before the handler runs, so
            // neither the success nor the catch tracker can also fire. A second emit
            // here would double-count the call in every error-rate metric.
            const calls = mockTrackToolCall.mock.calls.filter((c) => c[0] === 'strict-tool')
            expect(calls).toHaveLength(1)
            const call = calls[0]!
            expect(call[2]).toBe(true)
            // No handler ran, so the call carries no duration (mirrors the exec path).
            expect(call[1]).toBe(0)
            expect(trackToolCallExtras('strict-tool')).toMatchObject({
                $mcp_error_type: 'validation',
                // `:undefined` is the received type — the param was absent, not
                // mistyped, which is what separates an alias slip from a coercion bug.
                $mcp_validation_fields: ['required_field:invalid_type:undefined'],
                $mcp_validation_input_keys: ['requiredField'],
            })
        })

        it('records error for unknown tool', async () => {
            await executor.handleToolCall({ name: 'nonexistent', arguments: {} }, makeState([]))

            expect(mockToolCallsInc).toHaveBeenCalledWith({ tool: 'nonexistent', status: 'error' })
        })
    })

    describe('single-exec mode', () => {
        function execState(): ResolvedState {
            // Mirror getFilteredTools: full tool objects with real schemas and
            // handlers, so exec's inner dispatch (schema validation, handler
            // call) behaves as in production.
            const tools = catalog.getPreBuiltEntries().map((entry) => {
                const preBuilt = catalog.getToolByName(entry.name)!
                return {
                    ...preBuilt.base,
                    title: entry.title,
                    description: entry.description ?? '',
                    annotations: entry.annotations,
                    scopes: [],
                }
            })
            return makeState(tools as any, { useSingleExec: true })
        }

        it('emits no exec-labelled counter or timer on success', async () => {
            await executor.handleToolCall({ name: 'exec', arguments: { command: 'tools' } }, execState())

            expect(callsFor(mockToolCallsInc, 'exec')).toHaveLength(0)
            expect(callsFor(mockToolDurationStartTimer, 'exec')).toHaveLength(0)
        })

        // Without the verb, every non-`call` command lands in one undifferentiated
        // `exec` bucket — schema discovery, tool search and a mistyped verb become
        // indistinguishable, and `unknown_command` records nothing to diagnose.
        // `$mcp_exec_target_tool` is what links an `info <tool>` to the `call <tool>`
        // that follows it, and is the only trace of an attempted unknown tool.
        it.each([
            ['tools', { $mcp_exec_verb: 'tools' }],
            ['info docs-search', { $mcp_exec_verb: 'info', $mcp_exec_target_tool: 'docs-search' }],
            ['schema docs-search query', { $mcp_exec_verb: 'schema', $mcp_exec_target_tool: 'docs-search' }],
            // A verb or tool name we don't recognize is caller text, so the event
            // records that it was unrecognized rather than the token itself.
            ['frobnicate whatever', { $mcp_exec_verb: 'unrecognized' }],
            ['call not-a-real-tool {}', { $mcp_exec_verb: 'call', $mcp_exec_target_tool: 'unrecognized' }],
        ])('stamps the exec verb and target for "%s"', async (command, expected) => {
            await executor.handleToolCall({ name: 'exec', arguments: { command } }, execState())

            const call = mockTrackToolCall.mock.calls.at(-1)
            expect(call?.[4]).toMatchObject(expected)
        })

        it('emits inner tool name for counter and duration on inner tool call', async () => {
            await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'call docs-search {"query": "test"}' } },
                execState()
            )

            const innerCounts = callsFor(mockToolCallsInc, 'docs-search')
            expect(innerCounts.length).toBeGreaterThan(0)
            expect(innerCounts[0].status).toMatch(/^(success|error)$/)

            const innerDurations = mockToolDurationObserve.mock.calls.filter((c: any[]) => c[0]?.tool === 'docs-search')
            expect(innerDurations.length).toBeGreaterThan(0)

            expect(callsFor(mockToolCallsInc, 'exec')).toHaveLength(0)
        })

        it('classifies inner tool errors under the inner tool name, not exec', async () => {
            await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'call docs-search {"query": "test"}' } },
                execState()
            )

            const innerClassifications = callsFor(mockToolErrorsInc, 'docs-search')
            const execClassifications = callsFor(mockToolErrorsInc, 'exec')

            expect(innerClassifications.length).toBeGreaterThan(0)
            expect(innerClassifications[0].error_type).toBeTruthy()
            expect(execClassifications).toHaveLength(0)
        })

        it('records inner validation_error without a duration observation', async () => {
            await executor.handleToolCall({ name: 'exec', arguments: { command: 'call docs-search {}' } }, execState())

            expect(callsFor(mockToolCallsInc, 'docs-search')).toEqual([
                { tool: 'docs-search', status: 'validation_error' },
            ])
            const innerDurations = mockToolDurationObserve.mock.calls.filter((c: any[]) => c[0]?.tool === 'docs-search')
            expect(innerDurations).toHaveLength(0)
            expect(callsFor(mockToolCallsInc, 'exec')).toHaveLength(0)
        })

        it('classifies inner validation failures as validation, not internal', async () => {
            await executor.handleToolCall({ name: 'exec', arguments: { command: 'call docs-search {}' } }, execState())

            expect(callsFor(mockToolErrorsInc, 'docs-search')).toEqual([
                { tool: 'docs-search', error_type: 'validation' },
            ])
            expect(callsFor(mockToolErrorsInc, 'exec')).toHaveLength(0)
        })

        // Dispatcher rejections are agent mistakes, not server faults: they must not
        // land in the `internal` bucket the error-rate alert watches, they stay
        // attributed to `exec` (no inner tool ran), and they must carry a value-free
        // message so the failure is debuggable from analytics.
        it.each([
            ['call nonexistent-tool-xyz {}', 'unknown_tool'],
            ['frobnicate', 'unknown_command'],
            ['call docs-search {not json}', 'invalid_json'],
        ])('classifies %s as validation', async (command, reason) => {
            await executor.handleToolCall({ name: 'exec', arguments: { command } }, execState())

            expect(callsFor(mockToolCallsInc, 'exec')).toEqual([{ tool: 'exec', status: 'validation_error' }])
            expect(callsFor(mockToolErrorsInc, 'exec')).toEqual([{ tool: 'exec', error_type: 'validation' }])
            expect(trackToolCallExtras('exec')).toMatchObject({
                $mcp_error_type: 'validation',
                $mcp_error_code: reason,
                $mcp_error_message: `Exec command rejected: ${reason}`,
            })
        })

        it('classifies a scope-gated tool as permission, not validation', async () => {
            // The agent can't fix this by sending different input — the connection has
            // to be reauthorized, which is what the permission-rate alert watches for.
            const state = execState()
            state.scopeGatedTools = [{ name: 'gated-tool', missingScopes: ['insight:read'] }] as any

            await executor.handleToolCall({ name: 'exec', arguments: { command: 'info gated-tool' } }, state)

            expect(callsFor(mockToolErrorsInc, 'exec')).toEqual([{ tool: 'exec', error_type: 'permission' }])
            expect(trackToolCallExtras('exec')).toMatchObject({
                $mcp_error_message: 'Exec command rejected: missing_scope',
            })
        })
    })
})
