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

import type { RequestProperties } from '@/lib/request-properties'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { ToolCatalog } from '@/hono/tool-catalog'
import { ToolExecutor } from '@/hono/tool-executor'
import { InstructionsBuilder } from '@/hono/instructions'

function makeProps(overrides: Partial<RequestProperties> = {}): RequestProperties {
    return {
        userHash: 'test-user',
        apiToken: 'phx_test',
        sessionId: 'sess-1',
        mcpClientName: 'test',
        mcpClientVersion: '1.0',
        mcpProtocolVersion: '2025-03-26',
        transport: 'streamable-http',
        requestStartTime: Date.now(),
        ...overrides,
    }
}

function makeState(tools: { name: string }[], overrides: Partial<ResolvedState> = {}): ResolvedState {
    return {
        reqCtx: {
            cache: { get: vi.fn(), set: vi.fn() },
            getAnalyticsContextSafe: vi.fn().mockResolvedValue(undefined),
            trackEvent: vi.fn(),
            getSessionUuid: vi.fn().mockResolvedValue(undefined),
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
        version: 1,
        useSingleExec: false,
        toolFeatureFlags: undefined,
        apiKeyScopes: [],
        clientProfile: { capabilities: { supportsInstructions: true } } as any,
        allTools: tools as any,
        distinctId: 'test-distinct-id',
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

describe('ToolExecutor metrics', () => {
    let catalog: ToolCatalog
    let executor: ToolExecutor

    beforeEach(async () => {
        mockToolCallsInc.mockClear()
        mockToolDurationObserve.mockClear()
        mockToolDurationStartTimer.mockClear()
        mockToolErrorsInc.mockClear()

        catalog = new ToolCatalog()
        await catalog.warmup()
        executor = new ToolExecutor(catalog, new InstructionsBuilder(''))
    })

    describe('non-exec mode', () => {
        it('emits counter and duration with the tool name on success', async () => {
            const fake = makeFakeTool('my-tool')
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(fake as any)

            await executor.handleToolCall(
                { name: 'my-tool', arguments: {} },
                makeProps(),
                makeState([{ name: 'my-tool' }])
            )

            expect(mockToolDurationStartTimer).toHaveBeenCalledWith({ tool: 'my-tool' })
            expect(mockToolCallsInc).toHaveBeenCalledWith({ tool: 'my-tool', status: 'success' })

            const stopFn = mockToolDurationStartTimer.mock.results[0]!.value
            expect(stopFn).toHaveBeenCalledWith({ status: 'success' })
        })

        it('emits counter, duration, and error classification on handler failure', async () => {
            const fake = makeFakeTool('fail-tool', async () => {
                throw new Error('boom')
            })
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(fake as any)

            await executor.handleToolCall(
                { name: 'fail-tool', arguments: {} },
                makeProps(),
                makeState([{ name: 'fail-tool' }])
            )

            expect(mockToolCallsInc).toHaveBeenCalledWith({ tool: 'fail-tool', status: 'error' })
            expect(mockToolErrorsInc).toHaveBeenCalledWith({ tool: 'fail-tool', error_type: 'internal' })

            const stopFn = mockToolDurationStartTimer.mock.results[0]!.value
            expect(stopFn).toHaveBeenCalledWith({ status: 'error' })
        })

        it('emits validation_error status for invalid arguments', async () => {
            const strictTool = {
                name: 'strict-tool',
                base: {
                    schema: z.object({ required_field: z.string() }),
                    handler: vi.fn(),
                    _meta: undefined,
                },
            }
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(strictTool as any)

            await executor.handleToolCall(
                { name: 'strict-tool', arguments: {} },
                makeProps(),
                makeState([{ name: 'strict-tool' }])
            )

            expect(mockToolCallsInc).toHaveBeenCalledWith({ tool: 'strict-tool', status: 'validation_error' })
            expect(mockToolDurationStartTimer).not.toHaveBeenCalled()
        })

        it('emits error for unknown tool name', async () => {
            await executor.handleToolCall({ name: 'nonexistent', arguments: {} }, makeProps(), makeState([]))

            expect(mockToolCallsInc).toHaveBeenCalledWith({ tool: 'nonexistent', status: 'error' })
        })
    })

    describe('single-exec mode', () => {
        it('does not emit outer exec-level Prometheus metrics', async () => {
            const entries = catalog.getPreBuiltEntries().slice(0, 3)
            const state = makeState(
                entries.map((e) => ({ name: e.name })),
                { useSingleExec: true, version: 2 }
            )

            await executor.handleToolCall({ name: 'exec', arguments: { command: 'tools' } }, makeProps(), state)

            const execTimerCalls = mockToolDurationStartTimer.mock.calls.filter((c: any[]) => c[0]?.tool === 'exec')
            expect(execTimerCalls).toHaveLength(0)

            const execCountCalls = mockToolCallsInc.mock.calls.filter((c: any[]) => c[0]?.tool === 'exec')
            expect(execCountCalls).toHaveLength(0)
        })

        it('emits metrics with inner tool name when calling a real tool', async () => {
            const entries = catalog.getPreBuiltEntries()
            const state = makeState(
                entries.map((e) => ({ name: e.name })),
                { useSingleExec: true, version: 2 }
            )

            await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'call docs-search {"query": "test"}' } },
                makeProps(),
                state
            )

            const innerCountCalls = mockToolCallsInc.mock.calls.filter((c: any[]) => c[0]?.tool === 'docs-search')
            expect(innerCountCalls.length).toBeGreaterThan(0)
            expect(innerCountCalls[0]![0].status).toMatch(/^(success|error)$/)

            const innerDurationCalls = mockToolDurationObserve.mock.calls.filter(
                (c: any[]) => c[0]?.tool === 'docs-search'
            )
            expect(innerDurationCalls.length).toBeGreaterThan(0)
            expect(innerDurationCalls[0]![1]).toBeGreaterThanOrEqual(0)

            const execCalls = mockToolCallsInc.mock.calls.filter((c: any[]) => c[0]?.tool === 'exec')
            expect(execCalls).toHaveLength(0)
        })
    })
})
