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
import { PostHogRateLimitError, wrapError } from '@/lib/errors'

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
        clientProfile: {
            capabilities: { supportsInstructions: true },
            isCliModeEnabled: vi.fn(() => false),
            isClaudeUiHost: vi.fn(() => false),
            isInlineExecUiHost: vi.fn(() => false),
            isClaudeChatHost: vi.fn(() => false),
        } as any,
        requestContext: {
            sessionId: 'sess-1',
            mcpClientName: 'test',
            mcpClientVersion: '1.0',
            mcpProtocolVersion: '2025-03-26',
            transport: 'streamable-http',
        },
        sessionContext: null,
        allTools: tools as any,
        scopeGatedTools: [],
        distinctId: 'test-distinct-id',
        renderUiEnabled: false,
        metadata: undefined,
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

        it('emits exec-level error for framework failures before inner dispatch', async () => {
            await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'call nonexistent-tool-xyz {}' } },
                execState()
            )

            const execErrors = callsFor(mockToolCallsInc, 'exec')
            expect(execErrors.length).toBeGreaterThan(0)
            expect(execErrors[0].status).toBe('error')

            expect(callsFor(mockToolErrorsInc, 'exec').length).toBeGreaterThan(0)
        })
    })
})
