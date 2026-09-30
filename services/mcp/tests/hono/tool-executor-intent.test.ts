import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

vi.mock('@/tools', async () => {
    const { default: executeSql } = await import('@/tools/posthogAiTools/executeSql')
    const { default: getProjects } = await import('@/tools/projects/getProjects')
    return { TOOL_MAP: { 'execute-sql': executeSql, 'projects-get': getProjects } }
})

vi.mock('@/tools/generated', () => ({ GENERATED_TOOL_MAP: {} }))

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
    const client = new PostHogMCP('phc_test', { disabled: true, captureModel: true })
    return { getPostHogClient: () => client }
})

import { InstructionsBuilder } from '@/hono/instructions'
import { ToolCatalog } from '@/hono/tool-catalog'
import { ToolExecutor } from '@/hono/tool-executor'
import { getPostHogClient } from '@/lib/posthog'
import { MAX_CAPTURED_DESCRIPTION_LENGTH } from '@/tools/toolDefinitions'

import { makeToolExecutorState, mockApi } from '../shared/test-utils'

describe('ToolExecutor analytics capture', () => {
    let catalog: ToolCatalog
    let executor: ToolExecutor

    afterEach(() => {
        vi.restoreAllMocks()
    })

    beforeAll(async () => {
        catalog = new ToolCatalog()
        await catalog.warmup()
        executor = new ToolExecutor(catalog, new InstructionsBuilder(''))
    })

    it('injects the analytics arguments into advertised tools', async () => {
        const state = makeToolExecutorState([], { useSingleExec: true })

        const result = await executor.handleToolsList(state)

        const execEntry = result.tools.find((t) => t.name === 'exec')!
        const properties = execEntry.inputSchema.properties as Record<string, unknown>
        // The SDK injects `context` (required, to nudge the agent to state intent)
        // while leaving the existing `command` arg untouched.
        expect(properties).toHaveProperty('context')
        expect(properties).toHaveProperty('llm_model')
        expect(properties).toHaveProperty('command')
        expect(execEntry.inputSchema.required).toContain('context')
        expect(execEntry.inputSchema.required).toContain('llm_model')
    })

    it.each([
        {
            label: 'forwards the agent intent and strips context before the handler',
            args: {
                command: 'tools',
                context: 'investigating signup drop',
                llm_model: 'gpt-5.6-codex',
            },
            expectedIntent: 'investigating signup drop',
            expectedSource: 'context_parameter',
            expectedModel: 'gpt-5.6-codex',
            expectedModelSource: 'self_reported',
            expectedMissingReason: undefined,
        },
        {
            label: 'prefers Codex request metadata over an unknown self-report',
            args: {
                command: 'tools',
                context: 'checking the available tools',
                llm_model: 'unknown',
            },
            requestMeta: { 'x-codex-turn-metadata': { model: 'gpt-5.6-sol' } },
            expectedIntent: 'checking the available tools',
            expectedSource: 'context_parameter',
            expectedModel: 'gpt-5.6-sol',
            expectedModelSource: 'client_metadata',
            expectedMissingReason: undefined,
        },
        {
            label: 'captures no intent when the agent omits context',
            args: { command: 'tools' },
            expectedIntent: undefined,
            expectedSource: undefined,
            expectedModel: undefined,
            expectedModelSource: undefined,
            expectedMissingReason: 'missing',
        },
        ...[
            { llm_model: ' UnKnOwN ', reason: 'unknown' },
            { llm_model: '   ', reason: 'invalid' },
            { llm_model: null, reason: 'invalid' },
            { llm_model: 42, reason: 'invalid' },
        ].map(({ llm_model, reason }) => ({
            label: `records ${reason} for model argument ${JSON.stringify(llm_model)}`,
            args: { command: 'tools', llm_model },
            requestMeta: undefined,
            expectedIntent: undefined,
            expectedSource: undefined,
            expectedModel: undefined,
            expectedModelSource: undefined,
            expectedMissingReason: reason,
        })),
    ])(
        'exec call $label',
        async ({
            args,
            requestMeta,
            expectedIntent,
            expectedSource,
            expectedModel,
            expectedModelSource,
            expectedMissingReason,
        }) => {
            const captureSpy = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})

            const filteredTools = catalog
                .getFilteredTools({ scopes: ['*'] })
                .filter((tool) => tool.name === 'execute-sql' || tool.name === 'organization-get')
            const state = makeToolExecutorState(filteredTools, { useSingleExec: true })
            await executor.handleToolsList(state)

            const result = (await executor.handleToolCall(
                { name: 'exec', arguments: args, _meta: requestMeta },
                state
            )) as any

            // context (when present) must not break exec validation — proves it was stripped.
            expect(result.isError).toBeFalsy()

            expect(captureSpy).toHaveBeenCalledTimes(1)
            const arg = captureSpy.mock.calls[0]![0]
            expect(arg.toolName).toBe('exec')
            expect(arg.intent).toBe(expectedIntent)
            expect(arg.intentSource).toBe(expectedSource)
            expect(arg.llmModel).toBe(expectedModel)
            expect(arg.llmModelSource).toBe(expectedModelSource)
            expect(arg.properties?.$mcp_llm_model_missing_reason).toBe(expectedMissingReason)

            captureSpy.mockRestore()
        }
    )

    it.each([
        ['states an intent', { command: 'tools', context: 'auditing the dashboard tiles' }],
        ['states none', { command: 'tools' }],
    ] as const)(
        'leaves the shared API client alone, so a concurrent call cannot pick up this intent — the agent %s',
        async (_label, args) => {
            vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})
            const state = makeToolExecutorState([], { useSingleExec: true })

            await executor.handleToolCall({ name: 'exec', arguments: args }, state)

            expect(state.context.api.config.intent).toBeUndefined()
        }
    )

    it('runs the call without an intent when the API client cannot carry one', async () => {
        vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})
        const state = makeToolExecutorState([], { useSingleExec: true })
        state.context.api = mockApi({
            withIntent: () => {
                throw new Error('cannot copy this client')
            },
        }) as any

        const result = (await executor.handleToolCall(
            { name: 'exec', arguments: { command: 'tools', context: 'auditing the dashboard tiles' } },
            state
        )) as { isError?: boolean }

        expect(result.isError).toBeFalsy()
    })

    it.each(['not_captured', 'capture_error'] as const)(
        'records %s when analytics preparation cannot capture a supplied model',
        async (reason) => {
            const client = getPostHogClient()
            vi.spyOn(client, 'prepareToolCall').mockImplementationOnce((_name, args) => {
                if (reason === 'capture_error') {
                    throw new Error('Analytics preparation failed')
                }
                return { args, isMissingCapability: false, isFeedback: false }
            })
            const captureSpy = vi.spyOn(client, 'captureToolCall').mockImplementation(() => {})

            const result = (await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'tools', llm_model: 'example-model' } },
                makeToolExecutorState([], { useSingleExec: true })
            )) as { isError?: boolean }

            expect(result.isError).toBeFalsy()
            expect(captureSpy).toHaveBeenCalledTimes(1)
            expect(captureSpy.mock.calls[0]![0].properties?.$mcp_llm_model_missing_reason).toBe(reason)
            expect(captureSpy.mock.calls[0]![0].llmModel).toBeUndefined()
        }
    )

    // A native (non-exec) tool call with context: proves the native callTool path
    // strips context and forwards intent. The native path now also tracks schema
    // rejections, so "captureToolCall fired" alone no longer implies validation
    // passed — assert the absence of a validation error explicitly, otherwise an
    // unstripped `context` (rejected as an unrecognized key) would satisfy this
    // test. (projects-get hits the API, which the harness can't fulfill, so we
    // assert on the captured analytics, not the tool's own result.)
    it('strips analytics arguments before a native tool validates and forwards their values', async () => {
        const state = makeToolExecutorState([{ name: 'projects-get' }])
        await executor.handleToolsList(state)
        const captureSpy = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})

        await executor.handleToolCall(
            {
                name: 'projects-get',
                arguments: {
                    context: 'looking up the current user',
                    llm_model: 'claude-sonnet-4-20250514',
                },
            },
            state
        )

        expect(captureSpy).toHaveBeenCalledTimes(1)
        const arg = captureSpy.mock.calls[0]![0]
        expect(arg.toolName).toBe('projects-get')
        expect(arg.intent).toBe('looking up the current user')
        expect(arg.llmModel).toBe('claude-sonnet-4-20250514')
        expect(arg.llmModelSource).toBe('self_reported')
        expect(arg.properties).not.toHaveProperty('$mcp_llm_model_missing_reason')
        expect(arg.properties?.$mcp_error_type).not.toBe('validation')

        captureSpy.mockRestore()
    })

    // execute-sql is the one tool whose advertised description is formatted per
    // request rather than served from the catalog; the stamped
    // $mcp_tool_description must be the formatted text the agent saw. One case
    // per dispatch path, since each wires the served description independently.
    // (Both handlers fail against the harness's empty api; the error path still
    // captures the event, which is the shape being pinned.)
    it.each([
        {
            label: 'native path',
            call: { name: 'execute-sql', arguments: { query: 'SELECT 1' } },
            state: () => makeToolExecutorState([{ name: 'execute-sql' }]),
        },
        {
            label: 'exec path',
            call: { name: 'exec', arguments: { command: 'call execute-sql {"query": "SELECT 1"}' } },
            state: () =>
                makeToolExecutorState(
                    catalog.getFilteredTools({ scopes: ['*'] }).filter((tool) => tool.name === 'execute-sql'),
                    { useSingleExec: false }
                ),
        },
    ])('stamps the formatted execute-sql description on the $label', async ({ call, state }) => {
        const captureSpy = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})

        await executor.handleToolCall(call, state())

        // trackToolCall is fire-and-forget; wait for the capture to land so the
        // assertion (and the spy restore) never race the pending promise.
        await vi.waitFor(() => expect(captureSpy).toHaveBeenCalledTimes(1))
        const arg = captureSpy.mock.calls[0]![0]
        expect(arg.toolName).toBe('execute-sql')
        const expected = new InstructionsBuilder('').formatExecuteSqlDescription()
        expect(arg.properties?.$mcp_tool_description).toBe(expected.slice(0, MAX_CAPTURED_DESCRIPTION_LENGTH))

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
            makeToolExecutorState([{ name: 'projects-get' }])
        )) as any

        expect(result.content).toBeTruthy()
        expect(captureSpy).toHaveBeenCalledTimes(1)
        expect(captureSpy.mock.calls[0]![0].intent).toBeUndefined()
        expect(captureSpy.mock.calls[0]![0].properties?.$mcp_llm_model_missing_reason).toBe('missing')

        captureSpy.mockRestore()
    })

    // MCP 2026-07-28 carries no session of its own, so the agent's handle is the only one
    // these calls can group by.
    const statelessState = (): ReturnType<typeof makeToolExecutorState> =>
        makeToolExecutorState([], {
            useSingleExec: true,
            requestContext: { authMethod: 'personal_api_key', mcpProtocolVersion: '2026-07-28' } as any,
        })

    const readConversationHandle = (result: unknown): string | undefined => {
        const content = (result as { content?: { text?: string }[] }).content ?? []
        for (const part of content) {
            try {
                const parsed = JSON.parse(part.text ?? '')
                if (parsed && typeof parsed.conversation_id === 'string') {
                    return parsed.conversation_id
                }
            } catch {
                continue
            }
        }
        return undefined
    }

    it('hands a session handle to a client that carries none, and groups the echoed call with it', async () => {
        const captureSpy = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})
        const state = statelessState()
        await executor.handleToolsList(state)

        const first = await executor.handleToolCall({ name: 'exec', arguments: { command: 'tools' } }, state)
        const handle = readConversationHandle(first)

        expect(handle).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
        await vi.waitFor(() => expect(captureSpy).toHaveBeenCalledTimes(1))
        expect(captureSpy.mock.calls[0]![0].conversationId).toBe(handle)

        const second = await executor.handleToolCall(
            { name: 'exec', arguments: { command: 'tools', conversation_id: handle } },
            state
        )

        await vi.waitFor(() => expect(captureSpy).toHaveBeenCalledTimes(2))
        expect(captureSpy.mock.calls[1]![0].conversationId).toBe(handle)
        // `RequestContext` holds this same object; a copy would leave its events sessionless.
        expect(state.requestContext.mcpConversationId).toBe(handle)
        // Repeating it would spend tokens telling the agent what it just told us.
        expect(readConversationHandle(second)).toBeUndefined()
        expect((second as { isError?: boolean }).isError).toBeFalsy()

        captureSpy.mockRestore()
    })

    it('leaves a client that already has a session untouched', async () => {
        const captureSpy = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})
        // `makeToolExecutorState` carries `sessionId: 'sess-1'`, the wrapper-app id.
        const state = makeToolExecutorState([], { useSingleExec: true })
        await executor.handleToolsList(state)

        const result = await executor.handleToolCall({ name: 'exec', arguments: { command: 'tools' } }, state)

        // Minting here would split the session these clients already group by, and append a
        // block to every first result, for the majority of today's traffic.
        expect(readConversationHandle(result)).toBeUndefined()
        await vi.waitFor(() => expect(captureSpy).toHaveBeenCalledTimes(1))
        expect(captureSpy.mock.calls[0]![0].conversationId).toBeUndefined()

        captureSpy.mockRestore()
    })

    it('keeps the handle a wrapper app sent on the conversation header', async () => {
        const captureSpy = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})
        const state = makeToolExecutorState([], {
            useSingleExec: true,
            requestContext: { authMethod: 'personal_api_key', mcpConversationId: 'conv-from-header' } as any,
        })
        await executor.handleToolsList(state)

        const result = await executor.handleToolCall({ name: 'exec', arguments: { command: 'tools' } }, state)

        // The header is the app's own grouping. Minting over it would replace that app's
        // conversation with a fresh handle on every call.
        expect(readConversationHandle(result)).toBeUndefined()
        await vi.waitFor(() => expect(captureSpy).toHaveBeenCalledTimes(1))
        expect(captureSpy.mock.calls[0]![0].conversationId).toBe('conv-from-header')

        captureSpy.mockRestore()
    })
})
