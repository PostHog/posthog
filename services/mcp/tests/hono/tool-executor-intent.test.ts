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
            safelyGetAnalyticsContext: vi.fn().mockResolvedValue(undefined),
            trackEvent: vi.fn(),
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

    it.each([
        {
            label: 'forwards the agent intent and strips context before the handler',
            args: { command: 'tools', context: 'investigating signup drop' },
            expectedIntent: 'investigating signup drop',
            expectedSource: 'context_parameter',
        },
        {
            label: 'captures no intent when the agent omits context',
            args: { command: 'tools' },
            expectedIntent: undefined,
            expectedSource: undefined,
        },
    ])('exec call $label', async ({ args, expectedIntent, expectedSource }) => {
        const captureSpy = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})

        const filteredTools = catalog
            .getFilteredTools({ scopes: ['*'] })
            .filter((tool) => tool.name === 'execute-sql' || tool.name === 'organization-get')

        const result = (await executor.handleToolCall(
            { name: 'exec', arguments: args },
            makeState(filteredTools, { useSingleExec: false })
        )) as any

        // context (when present) must not break exec validation — proves it was stripped.
        expect(result.isError).toBeFalsy()

        expect(captureSpy).toHaveBeenCalledTimes(1)
        const arg = captureSpy.mock.calls[0]![0]
        expect(arg.toolName).toBe('exec')
        expect(arg.intent).toBe(expectedIntent)
        expect(arg.intentSource).toBe(expectedSource)

        captureSpy.mockRestore()
    })

    // A native (non-exec) tool call with context: proves the native callTool path
    // strips context and forwards intent. captureToolCall only fires *after*
    // validation passes (the validation-error path returns before tracking), so its
    // being called with the intent proves context was stripped before validation.
    // (projects-get hits the API, which the harness can't fulfill, so we assert on
    // the captured analytics, not the tool's own result.)
    it('strips context before a native tool validates and still forwards intent', async () => {
        const captureSpy = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})

        await executor.handleToolCall(
            { name: 'projects-get', arguments: { context: 'looking up the current user' } },
            makeState([{ name: 'projects-get' }])
        )

        expect(captureSpy).toHaveBeenCalledTimes(1)
        expect(captureSpy.mock.calls[0]![0].toolName).toBe('projects-get')
        expect(captureSpy.mock.calls[0]![0].intent).toBe('looking up the current user')

        captureSpy.mockRestore()
    })

    // Old-schema / old-client compatibility: an agent that doesn't know about the
    // injected context arg calls with just the tool's own args. The call is handled
    // exactly as before (a graceful result, never a thrown error) and no intent is
    // captured.
    it('handles a native call with no context (old-schema clients) gracefully', async () => {
        const captureSpy = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})

        const result = (await executor.handleToolCall(
            { name: 'projects-get', arguments: {} },
            makeState([{ name: 'projects-get' }])
        )) as any

        expect(result.content).toBeTruthy()
        expect(captureSpy).toHaveBeenCalledTimes(1)
        expect(captureSpy.mock.calls[0]![0].intent).toBeUndefined()

        captureSpy.mockRestore()
    })
})
