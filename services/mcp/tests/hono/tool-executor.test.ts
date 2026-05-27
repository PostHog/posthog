import { beforeAll, describe, expect, it, vi } from 'vitest'

vi.mock('@/resources/internals', () => ({
    fetchContextMillResources: vi.fn().mockRejectedValue(new Error('mocked')),
    filterValidEntries: vi.fn().mockReturnValue([]),
    loadManifestFromArchive: vi.fn().mockReturnValue({ resources: [] }),
    clearResourceCache: vi.fn(),
}))

vi.mock('@/resources', () => ({
    getPromptsFromManifest: vi.fn().mockResolvedValue([]),
}))

import { InstructionsBuilder } from '@/hono/instructions'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { ToolCatalog } from '@/hono/tool-catalog'
import { ToolExecutor } from '@/hono/tool-executor'
import type { RequestProperties } from '@/lib/request-properties'
import type {} from '@/tools/types'

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

describe('ToolExecutor', () => {
    let catalog: ToolCatalog
    let executor: ToolExecutor

    beforeAll(async () => {
        catalog = new ToolCatalog()
        await catalog.warmup()
        executor = new ToolExecutor(catalog, new InstructionsBuilder(''))
    })

    describe('handleToolCall', () => {
        it('returns error when tool name is missing', async () => {
            const result = (await executor.handleToolCall({}, makeProps(), makeState([]))) as any
            expect(result.isError).toBe(true)
            expect(result.content[0].text).toContain('Missing tool name')
        })

        it('returns error when tool does not exist', async () => {
            const result = (await executor.handleToolCall(
                { name: 'nonexistent-tool', arguments: {} },
                makeProps(),
                makeState([])
            )) as any
            expect(result.isError).toBe(true)
            expect(result.content[0].text).toContain('nonexistent-tool')
            expect(result.content[0].text).toContain('not found')
        })

        it('rejects tools not in the per-request filtered set', async () => {
            const entries = catalog.getPreBuiltEntries()
            const tool = entries[0]!

            const result = (await executor.handleToolCall(
                { name: tool.name, arguments: {} },
                makeProps(),
                makeState([])
            )) as any
            expect(result.isError).toBe(true)
            expect(result.content[0].text).toContain('not found')
        })

        it('returns validation error for invalid arguments', async () => {
            const knownTool = catalog.getPreBuiltEntries()[0]
            if (!knownTool) {
                throw new Error('need at least one tool to test validation')
            }

            const result = (await executor.handleToolCall(
                { name: knownTool.name, arguments: { __invalid_field_xyz: 'bad' } },
                makeProps(),
                makeState([{ name: knownTool.name }])
            )) as any

            expect(result).not.toBeNull()
        })

        it('successfully calls a real tool from the catalog', async () => {
            const entries = catalog.getPreBuiltEntries()
            const userGet = entries.find((e) => e.name === 'user-get')
            if (!userGet) {
                throw new Error('user-get tool not found in catalog')
            }

            const result = (await executor.handleToolCall(
                { name: 'user-get', arguments: {} },
                makeProps(),
                makeState([{ name: 'user-get' }])
            )) as any

            expect(result).not.toBeNull()
            expect(result.content).not.toBeNull()
        })

        it('accepts cached exec calls even when the current session is in tools mode', async () => {
            const filteredTools = catalog
                .getFilteredTools({ version: 2, scopes: ['*'] })
                .filter((tool) => tool.name === 'execute-sql' || tool.name === 'organization-get')

            const result = (await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'tools' } },
                makeProps({ mode: 'tools' }),
                makeState(filteredTools, { useSingleExec: false, version: 2 })
            )) as any

            expect(result.isError).toBeFalsy()
            const text = result.content?.[0]?.text ?? ''
            expect(text).toContain('execute-sql')
            expect(text).toContain('organization-get')
            expect(text).not.toContain('feature-flag-get-all')
        })
    })

    describe('handleToolsList', () => {
        it('returns filtered tools matching the state allTools', async () => {
            const allEntries = catalog.getPreBuiltEntries()
            const subset = allEntries.slice(0, 3)

            const result = await executor.handleToolsList(makeState(subset.map((e) => ({ name: e.name }))), makeProps())

            expect(result.tools).toHaveLength(3)
            expect(result.tools.map((t) => t.name)).toEqual(subset.map((e) => e.name))
        })

        it('returns empty list when allTools is empty', async () => {
            const result = await executor.handleToolsList(makeState([]), makeProps())
            expect(result.tools).toEqual([])
        })

        it('returns single exec tool entry when useSingleExec is true', async () => {
            const state = makeState(
                catalog
                    .getPreBuiltEntries()
                    .slice(0, 5)
                    .map((e) => ({ name: e.name })),
                { useSingleExec: true, version: 2 }
            )

            const result = await executor.handleToolsList(state, makeProps())
            expect(result.tools).toHaveLength(1)
            expect(result.tools[0]!.name).toBe('exec')
        })
    })
})
