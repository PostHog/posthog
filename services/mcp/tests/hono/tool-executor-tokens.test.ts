import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockTrackToolCall } = vi.hoisted(() => ({ mockTrackToolCall: vi.fn() }))

vi.mock('@/hono/analytics', () => ({
    trackToolCall: mockTrackToolCall,
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

import { InstructionsBuilder } from '@/hono/instructions'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { ToolCatalog } from '@/hono/tool-catalog'
import { ToolExecutor } from '@/hono/tool-executor'
import { estimateTokens } from '@/lib/estimate-tokens'

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
        useSingleExec: false,
        toolFeatureFlags: undefined,
        apiKeyScopes: [],
        clientProfile: {
            capabilities: { supportsInstructions: true },
            isCliModeEnabled: vi.fn(() => false),
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
        ...overrides,
    }
}

function makeFakeTool(
    name: string,
    handler: () => Promise<unknown> = async () => 'ok',
    _meta?: { ui?: { resourceUri?: string } }
): {
    name: string
    base: {
        schema: z.ZodObject<Record<string, never>>
        handler: ReturnType<typeof vi.fn>
        _meta?: { ui?: { resourceUri?: string } }
    }
} {
    return {
        name,
        base: {
            schema: z.object({}),
            handler: vi.fn().mockImplementation(handler),
            _meta,
        },
    }
}

function joinedText(response: { content: Array<{ text: string }> }): string {
    return response.content.map((part) => part.text).join('')
}

describe('ToolExecutor token estimates', () => {
    let catalog: ToolCatalog
    let executor: ToolExecutor

    beforeEach(async () => {
        mockTrackToolCall.mockClear()
        catalog = new ToolCatalog()
        await catalog.warmup()
        executor = new ToolExecutor(catalog, new InstructionsBuilder(''))
    })

    describe('direct tool calls', () => {
        it('measures output tokens from the returned text, not the re-serialized payload', async () => {
            const handlerResult = {
                rows: [
                    { id: 1, name: 'alpha' },
                    { id: 2, name: 'beta' },
                ],
            }
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(
                makeFakeTool('my-tool', async () => handlerResult) as any
            )

            const response = (await executor.handleToolCall(
                { name: 'my-tool', arguments: {} },
                makeState([{ name: 'my-tool' }])
            )) as any

            const [toolName, , isError, , extra] = mockTrackToolCall.mock.calls[0]!
            expect(toolName).toBe('my-tool')
            expect(isError).toBe(false)
            expect(extra.input_tokens).toBe(estimateTokens({}))
            expect(extra.output_tokens).toBe(estimateTokens(joinedText(response)))
            // Regression: the estimate must not measure JSON.stringify of the whole
            // payload — the {content:[...]} wrapper and escaping inflate the count.
            expect(extra.output_tokens).not.toBe(estimateTokens(response))
        })

        it('excludes structuredContent from the output estimate for UI tools', async () => {
            const handlerResult = {
                rows: [
                    { id: 1, name: 'alpha' },
                    { id: 2, name: 'beta' },
                ],
            }
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(
                makeFakeTool('ui-tool', async () => handlerResult, { ui: { resourceUri: 'ui://test-app' } }) as any
            )

            const response = (await executor.handleToolCall(
                { name: 'ui-tool', arguments: {} },
                makeState([{ name: 'ui-tool' }])
            )) as any

            // structuredContent rides along for UI tools but must not be double-billed.
            expect(response.structuredContent).not.toBeUndefined()
            const [, , , , extra] = mockTrackToolCall.mock.calls[0]!
            expect(extra.output_tokens).toBe(estimateTokens(joinedText(response)))
        })

        it('omits token estimates on error', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(
                makeFakeTool('fail-tool', async () => {
                    throw new Error('boom')
                }) as any
            )

            await executor.handleToolCall({ name: 'fail-tool', arguments: {} }, makeState([{ name: 'fail-tool' }]))

            const [toolName, , isError, , extra] = mockTrackToolCall.mock.calls[0]!
            expect(toolName).toBe('fail-tool')
            expect(isError).toBe(true)
            expect(extra).toBeUndefined()
        })
    })

    describe('exec wrapper event', () => {
        it('measures output tokens from the text returned by exec', async () => {
            const tools = catalog
                .getFilteredTools({ scopes: ['*'] })
                .filter((tool) => tool.name === 'execute-sql' || tool.name === 'organization-get')

            const response = (await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'tools' } },
                makeState(tools, { useSingleExec: true })
            )) as any

            const execCall = mockTrackToolCall.mock.calls.find((call) => call[0] === 'exec')!
            expect(execCall[2]).toBe(false)
            expect(execCall[4].input_tokens).toBe(estimateTokens({ command: 'tools' }))
            expect(execCall[4].output_tokens).toBe(estimateTokens(joinedText(response)))
            expect(execCall[4].output_tokens).not.toBe(estimateTokens(response))
        })
    })
})
