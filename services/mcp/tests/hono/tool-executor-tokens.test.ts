import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockTrackToolCall, mockTrackExecuteSqlGeneration } = vi.hoisted(() => ({
    mockTrackToolCall: vi.fn(),
    mockTrackExecuteSqlGeneration: vi.fn(),
}))

vi.mock('@/hono/analytics', () => ({
    trackToolCall: mockTrackToolCall,
    trackExecuteSqlGeneration: mockTrackExecuteSqlGeneration,
    trackToolSpan: vi.fn(),
}))

vi.mock('@/resources/internals', () => ({
    fetchContextMillResources: vi.fn().mockRejectedValue(new Error('mocked')),
    filterValidEntries: vi.fn().mockReturnValue([]),
    loadManifestFromArchive: vi.fn().mockReturnValue({ resources: [] }),
}))

vi.mock('@/resources', () => ({
    getPromptsFromManifest: vi.fn().mockResolvedValue([]),
}))

import { z } from 'zod'

import { MCP_OPENAI_RESULT_FILES_FEATURE_FLAG } from '@/hono/constants'
import { InstructionsBuilder } from '@/hono/instructions'
import { ToolCatalog } from '@/hono/tool-catalog'
import { ToolExecutor } from '@/hono/tool-executor'
import { MCPClientProfile } from '@/lib/client-detection'
import { estimateTokens } from '@/lib/estimate-tokens'

import { makeToolExecutorState, toolFromPreBuilt } from '../shared/test-utils'

type FakeToolBase = {
    schema: z.ZodObject<Record<string, never>>
    handler: ReturnType<typeof vi.fn>
    _meta?: { ui?: { resourceUri?: string } }
}

function makeFakeTool(
    name: string,
    handler: () => Promise<unknown> = async () => 'ok',
    _meta?: { ui?: { resourceUri?: string } }
): { name: string; build: () => FakeToolBase; base: FakeToolBase } {
    return {
        name,
        build() {
            return this.base
        },
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
        mockTrackExecuteSqlGeneration.mockClear()
        catalog = new ToolCatalog()
        await catalog.warmup()
        executor = new ToolExecutor(catalog, new InstructionsBuilder(''))
    })

    it.each([false, true])('offloads large results and measures the pointer in exec mode %s', async (useSingleExec) => {
        const text = 'synthetic result '.repeat(4000)
        const tool = makeFakeTool('docs-search', async () => text)
        vi.spyOn(catalog, 'getToolByName').mockReturnValue(tool as any)
        const state = makeToolExecutorState(
            [{ name: 'docs-search', schema: z.object({}), handler: tool.base.handler } as any],
            {
                useSingleExec,
                toolFeatureFlags: { [MCP_OPENAI_RESULT_FILES_FEATURE_FLAG]: true },
                clientProfile: new MCPClientProfile({ clientName: 'openai-mcp' }),
            }
        )
        const store = vi
            .fn()
            .mockResolvedValue({ download_url: 'https://storage.example.com/result.json', expires_in: 3600 })
        state.context.api.request = store
        state.context.stateManager.getProjectId = vi.fn().mockResolvedValue('123')

        const response = (await executor.handleToolCall(
            useSingleExec
                ? { name: 'exec', arguments: { command: 'call docs-search {}' } }
                : { name: 'docs-search', arguments: {} },
            state
        )) as { content: Array<{ type: 'text'; text: string }> }

        expect(store).toHaveBeenCalledOnce()
        expect(JSON.parse(store.mock.calls[0]![0].body.content).content[0].text).toBe(text)
        expect(JSON.parse(response.content[0]!.text).download_url).toBe('https://storage.example.com/result.json')
        const call = mockTrackToolCall.mock.calls.find((args) => args[0] === 'docs-search')!
        expect(call[4].output_tokens).toBe(estimateTokens(joinedText(response)))
    })

    describe('direct tool calls', () => {
        it('emits the execute-sql generation with the validated args', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue({
                name: 'execute-sql',
                build() {
                    return this.base
                },
                base: {
                    schema: z.object({ query: z.string() }),
                    handler: vi.fn().mockResolvedValue('ok'),
                },
            } as any)

            await executor.handleToolCall(
                { name: 'execute-sql', arguments: { query: 'SELECT 1' } },
                makeToolExecutorState([{ name: 'execute-sql' }])
            )

            expect(mockTrackExecuteSqlGeneration).toHaveBeenCalledTimes(1)
            const [toolName, args, , meta] = mockTrackExecuteSqlGeneration.mock.calls[0]!
            expect(toolName).toBe('execute-sql')
            expect(args).toEqual({ query: 'SELECT 1' })
            expect(meta.isError).toBe(false)
        })

        it('does not emit a generation for other tools', async () => {
            vi.spyOn(catalog, 'getToolByName').mockReturnValue(makeFakeTool('my-tool') as any)

            await executor.handleToolCall(
                { name: 'my-tool', arguments: {} },
                makeToolExecutorState([{ name: 'my-tool' }])
            )

            expect(mockTrackExecuteSqlGeneration).not.toHaveBeenCalled()
        })

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
                makeToolExecutorState([{ name: 'my-tool' }])
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
                makeToolExecutorState([{ name: 'ui-tool' }])
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

            await executor.handleToolCall(
                { name: 'fail-tool', arguments: {} },
                makeToolExecutorState([{ name: 'fail-tool' }])
            )

            const [toolName, , isError, , extra] = mockTrackToolCall.mock.calls[0]!
            expect(toolName).toBe('fail-tool')
            expect(isError).toBe(true)
            // The error path carries the failure classification ($mcp_error_type) but
            // never token estimates — those only make sense on a successful call.
            expect(extra).not.toHaveProperty('input_tokens')
            expect(extra).not.toHaveProperty('output_tokens')
        })
    })

    describe('exec wrapper event', () => {
        it('measures output tokens from the text returned by exec', async () => {
            const tools = catalog
                .getFilteredTools({ scopes: ['*'] })
                .filter((tool) => tool.name === 'execute-sql' || tool.name === 'organization-get')

            const response = (await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'tools' } },
                makeToolExecutorState(tools, { useSingleExec: true })
            )) as any

            const execCall = mockTrackToolCall.mock.calls.find((call) => call[0] === 'exec')!
            expect(execCall[2]).toBe(false)
            expect(execCall[4].input_tokens).toBe(estimateTokens({ command: 'tools' }))
            expect(execCall[4].output_tokens).toBe(estimateTokens(joinedText(response)))
            expect(execCall[4].output_tokens).not.toBe(estimateTokens(response))
        })

        it('attributes the canonical event to the inner tool via the standard $mcp_tool_name', async () => {
            // Full catalog tools (real names, so the instructions builder resolves them),
            // with the target handler stubbed to keep dispatch offline + deterministic.
            const tools = catalog
                .getPreBuiltEntries()
                .map((entry) => toolFromPreBuilt(catalog.getToolByName(entry.name)!, entry))
            const target = tools.find((t) => t.name === 'docs-search')! as any
            target.handler = vi.fn(async () => 'inner-ok')
            const state = makeToolExecutorState(tools as any, { useSingleExec: true })

            await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'call docs-search {"query":"hi"}' } },
                state
            )

            // The canonical event is attributed to the real inner tool — the same standard
            // property the SDK emits for direct calls — never the `exec` dispatcher.
            const innerCall = mockTrackToolCall.mock.calls.find((call) => call[0] === 'docs-search')!
            expect(innerCall).toBeTruthy()
            expect(innerCall[2]).toBe(false)
            expect(mockTrackToolCall.mock.calls.some((call) => call[0] === 'exec')).toBe(false)

            // Regression: the inner dispatch must not ALSO emit its own `mcp_tool_call`
            // event — that would double-count the inner tool on the legacy event.
            const trackEvent = state.reqCtx.trackEvent as ReturnType<typeof vi.fn>
            expect(trackEvent.mock.calls.some((call) => call[0] === 'mcp_tool_call')).toBe(false)
        })
    })
})
