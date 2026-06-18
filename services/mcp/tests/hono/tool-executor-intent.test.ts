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

// Replace the project's PostHog client with a real (but disabled, no-network)
// PostHogMCP so `prepareToolList` / `prepareToolCall` run the actual SDK injection
// and extraction logic — this proves dotcom's wiring against real SDK behavior,
// not a stub.
vi.mock('@/lib/posthog', async () => {
    const { PostHogMCP } = await import('@posthog/mcp-analytics')
    const client = new PostHogMCP('phc_test', { disabled: true })
    return { getPostHogClient: () => client }
})

import { InstructionsBuilder } from '@/hono/instructions'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { ToolCatalog } from '@/hono/tool-catalog'
import { ToolExecutor } from '@/hono/tool-executor'
import { getPostHogClient } from '@/lib/posthog'

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

describe('ToolExecutor intent capture', () => {
    let catalog: ToolCatalog
    let executor: ToolExecutor

    beforeAll(async () => {
        catalog = new ToolCatalog()
        await catalog.warmup()
        executor = new ToolExecutor(catalog, new InstructionsBuilder(''))
    })

    it('injects the context argument into advertised tools', async () => {
        const state = makeState([], { useSingleExec: true })

        const result = await executor.handleToolsList(state)

        const execEntry = result.tools.find((t) => t.name === 'exec')!
        const properties = execEntry.inputSchema.properties as Record<string, unknown>
        // The SDK injects `context` (required, to nudge the agent to state intent)
        // while leaving the existing `command` arg untouched.
        expect(properties).toHaveProperty('context')
        expect(properties).toHaveProperty('command')
        expect(execEntry.inputSchema.required).toContain('context')
    })

    it('forwards the agent intent to captureToolCall and strips context before the handler', async () => {
        const captureSpy = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})

        const filteredTools = catalog
            .getFilteredTools({ scopes: ['*'] })
            .filter((tool) => tool.name === 'execute-sql' || tool.name === 'organization-get')

        const result = (await executor.handleToolCall(
            { name: 'exec', arguments: { command: 'tools', context: 'investigating signup drop' } },
            makeState(filteredTools, { useSingleExec: false })
        )) as any

        // context must not break exec validation — proves it was stripped before the handler.
        expect(result.isError).toBeFalsy()

        expect(captureSpy).toHaveBeenCalledTimes(1)
        const arg = captureSpy.mock.calls[0]![0]
        expect(arg.toolName).toBe('exec')
        expect(arg.intent).toBe('investigating signup drop')
        expect(arg.intentSource).toBe('context_parameter')

        captureSpy.mockRestore()
    })

    it('captures no intent when the agent omits context', async () => {
        const captureSpy = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})

        const filteredTools = catalog
            .getFilteredTools({ scopes: ['*'] })
            .filter((tool) => tool.name === 'organization-get')

        await executor.handleToolCall(
            { name: 'exec', arguments: { command: 'tools' } },
            makeState(filteredTools, { useSingleExec: false })
        )

        expect(captureSpy).toHaveBeenCalledTimes(1)
        expect(captureSpy.mock.calls[0]![0].intent).toBeUndefined()

        captureSpy.mockRestore()
    })
})
