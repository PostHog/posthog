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

import type { ResolvedState } from '@/hono/request-state-resolver'
import { ToolCatalog } from '@/hono/tool-catalog'
import { ToolExecutor } from '@/hono/tool-executor'
import { InstructionsBuilder } from '@/hono/instructions'
import type { RequestProperties } from '@/lib/request-properties'

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
            trackContextSwitchEvent: vi.fn(),
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

        catalog = new ToolCatalog()
        await catalog.warmup()
        executor = new ToolExecutor(catalog, new InstructionsBuilder(''))
    })

    describe('direct tool calls', () => {
        it('records success counter and duration timer', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(makeFakeTool('my-tool') as any)

            await executor.handleToolCall(
                { name: 'my-tool', arguments: {} },
                makeProps(),
                makeState([{ name: 'my-tool' }])
            )

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

            await executor.handleToolCall(
                { name: 'fail-tool', arguments: {} },
                makeProps(),
                makeState([{ name: 'fail-tool' }])
            )

            expect(mockToolCallsInc).toHaveBeenCalledWith({ tool: 'fail-tool', status: 'error' })
            expect(mockToolErrorsInc).toHaveBeenCalledWith({ tool: 'fail-tool', error_type: 'internal' })
            expect(mockToolDurationStartTimer.mock.results[0]!.value).toHaveBeenCalledWith({ status: 'error' })
        })

        it('records validation_error without starting a timer', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue({
                name: 'strict-tool',
                base: { schema: z.object({ required_field: z.string() }), handler: vi.fn(), _meta: undefined },
            } as any)

            await executor.handleToolCall(
                { name: 'strict-tool', arguments: {} },
                makeProps(),
                makeState([{ name: 'strict-tool' }])
            )

            expect(mockToolCallsInc).toHaveBeenCalledWith({ tool: 'strict-tool', status: 'validation_error' })
            expect(mockToolDurationStartTimer).not.toHaveBeenCalled()
        })

        it('records error for unknown tool', async () => {
            await executor.handleToolCall({ name: 'nonexistent', arguments: {} }, makeProps(), makeState([]))

            expect(mockToolCallsInc).toHaveBeenCalledWith({ tool: 'nonexistent', status: 'error' })
        })
    })

    describe('single-exec mode', () => {
        function execState(): ResolvedState {
            return makeState(
                catalog.getPreBuiltEntries().map((e) => ({ name: e.name })),
                { useSingleExec: true, version: 2 }
            )
        }

        it('emits no exec-labelled counter or timer on success', async () => {
            await executor.handleToolCall({ name: 'exec', arguments: { command: 'tools' } }, makeProps(), execState())

            expect(callsFor(mockToolCallsInc, 'exec')).toHaveLength(0)
            expect(callsFor(mockToolDurationStartTimer, 'exec')).toHaveLength(0)
        })

        it('emits inner tool name for counter and duration on inner tool call', async () => {
            await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'call docs-search {"query": "test"}' } },
                makeProps(),
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
                makeProps(),
                execState()
            )

            const innerClassifications = callsFor(mockToolErrorsInc, 'docs-search')
            const execClassifications = callsFor(mockToolErrorsInc, 'exec')

            expect(innerClassifications.length).toBeGreaterThan(0)
            expect(innerClassifications[0].error_type).toBeTruthy()
            expect(execClassifications).toHaveLength(0)
        })

        it('emits exec-level error for framework failures before inner dispatch', async () => {
            await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'call nonexistent-tool-xyz {}' } },
                makeProps(),
                execState()
            )

            const execErrors = callsFor(mockToolCallsInc, 'exec')
            expect(execErrors.length).toBeGreaterThan(0)
            expect(execErrors[0].status).toBe('error')

            expect(callsFor(mockToolErrorsInc, 'exec').length).toBeGreaterThan(0)
        })
    })
})
