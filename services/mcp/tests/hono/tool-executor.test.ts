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
import { buildToolDomainsCompact } from '@/lib/instructions'
import { RENDER_UI_RESOURCE_URI, URI_MAP } from '@/resources/ui-apps.generated'
import { getToolDefinition } from '@/tools/toolDefinitions'

// A tool with a renderable (dispatchable) UI app — used to exercise the render-ui path.
const uiAppTool = {
    name: 'survey-get',
    annotations: { readOnlyHint: true },
    _meta: { ui: { resourceUri: URI_MAP['survey'] } },
}

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
            const result = (await executor.handleToolCall({}, makeState([]))) as any
            expect(result.isError).toBe(true)
            expect(result.content[0].text).toContain('Missing tool name')
        })

        it('returns error when tool does not exist', async () => {
            const result = (await executor.handleToolCall(
                { name: 'nonexistent-tool', arguments: {} },
                makeState([])
            )) as any
            expect(result.isError).toBe(true)
            expect(result.content[0].text).toContain('nonexistent-tool')
            expect(result.content[0].text).toContain('not found')
        })

        it('rejects tools not in the per-request filtered set', async () => {
            const entries = catalog.getPreBuiltEntries()
            const tool = entries[0]!

            const result = (await executor.handleToolCall({ name: tool.name, arguments: {} }, makeState([]))) as any
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
                makeState([{ name: 'user-get' }])
            )) as any

            expect(result).not.toBeNull()
            expect(result.content).not.toBeNull()
        })

        it('accepts cached exec calls even when the current session is in tools mode', async () => {
            const filteredTools = catalog
                .getFilteredTools({ scopes: ['*'] })
                .filter((tool) => tool.name === 'execute-sql' || tool.name === 'organization-get')

            const result = (await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'tools' } },
                makeState(filteredTools, { useSingleExec: false })
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

            const result = await executor.handleToolsList(makeState(subset.map((e) => ({ name: e.name }))))

            expect(result.tools).toHaveLength(3)
            expect(result.tools.map((t) => t.name)).toEqual(subset.map((e) => e.name))
        })

        it('returns empty list when allTools is empty', async () => {
            const result = await executor.handleToolsList(makeState([]))
            expect(result.tools).toEqual([])
        })

        it('returns the read-only and write exec dispatchers when useSingleExec is true', async () => {
            const state = makeState(
                catalog
                    .getPreBuiltEntries()
                    .slice(0, 5)
                    .map((e) => ({ name: e.name })),
                { useSingleExec: true }
            )

            const result = await executor.handleToolsList(state)
            // Two dispatchers so the client can gate on `readOnlyHint`: `exec` is safe to
            // always-allow, `exec-write` keeps prompting for confirmation on mutations.
            expect(result.tools.map((t) => t.name)).toEqual(['exec', 'exec-write'])
            expect(result.tools[0]!.annotations?.readOnlyHint).toBe(true)
            expect(result.tools[1]!.annotations?.readOnlyHint).toBe(false)
        })

        // Env-context (active project metadata + tool-domain index) must reach the model
        // on the exec `command` for clients that don't otherwise receive the `instructions`
        // payload: Codex reports `supportsInstructions: false` so never gets it, and Claude
        // web/desktop report `true` but silently ignore it. Claude Code and Cowork strip
        // it here because it arrives via `instructions` instead.
        it.each([
            {
                label: 'Claude web/desktop (ignores instructions)',
                supportsInstructions: true,
                isClaudeChatHost: true,
                expectEnv: true,
            },
            {
                label: 'Codex (supportsInstructions: false)',
                supportsInstructions: false,
                isClaudeChatHost: false,
                expectEnv: true,
            },
            {
                label: 'Claude Code / Cowork (consume instructions)',
                supportsInstructions: true,
                isClaudeChatHost: false,
                expectEnv: false,
            },
        ])(
            'injects project metadata into the exec command for $label → $expectEnv',
            async ({ supportsInstructions, isClaudeChatHost, expectEnv }) => {
                const tools = catalog
                    .getPreBuiltEntries()
                    .slice(0, 5)
                    .map((e) => ({ name: e.name }))
                const metadataMarker = 'CURRENT PROJECT: Acme (timezone America/New_York)'

                const state = makeState(tools, {
                    useSingleExec: true,
                    metadata: metadataMarker,
                    clientProfile: {
                        capabilities: { supportsInstructions },
                        isCliModeEnabled: vi.fn(() => true),
                        isClaudeUiHost: vi.fn(() => false),
                        isInlineExecUiHost: vi.fn(() => false),
                        isClaudeChatHost: vi.fn(() => isClaudeChatHost),
                    } as any,
                })

                const result = await executor.handleToolsList(state)
                const commandDesc = (result.tools[0]!.inputSchema.properties as any).command.description as string
                const compactDomains = buildToolDomainsCompact(
                    tools.map(({ name }) => ({ name, category: getToolDefinition(name).category }))
                )

                expect(commandDesc).toContain('PostHog tools have lowercase kebab-case naming')
                expect(commandDesc.includes('**LEARN FIRST: HARD REQUIREMENT**')).toBe(isClaudeChatHost)
                expect(commandDesc.includes('- analytics:')).toBe(isClaudeChatHost)
                expect(commandDesc.includes('### Retrieving data')).toBe(!isClaudeChatHost)
                expect(commandDesc.includes(compactDomains)).toBe(isClaudeChatHost)
                if (expectEnv) {
                    expect(commandDesc).toContain(metadataMarker)
                } else {
                    expect(commandDesc).not.toContain(metadataMarker)
                }
            }
        )

        it('serves multiple optional guidance topics through exec learn for Claude web/desktop', async () => {
            const state = makeState(
                catalog
                    .getPreBuiltEntries()
                    .slice(0, 5)
                    .map(({ name }) => ({ name })),
                {
                    useSingleExec: true,
                    renderUiEnabled: true,
                    clientProfile: {
                        capabilities: { supportsInstructions: true },
                        isCliModeEnabled: vi.fn(() => true),
                        isClaudeUiHost: vi.fn(() => false),
                        isInlineExecUiHost: vi.fn(() => false),
                        isClaudeChatHost: vi.fn(() => true),
                    } as any,
                }
            )

            const result = (await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'learn analytics visualizations' } },
                state
            )) as { content: { text: string }[] }

            expect(result.content[0]!.text).toContain('## Analytics')
            expect(result.content[0]!.text).toContain('### Retrieving data')
            expect(result.content[0]!.text).toContain('### Examples')
            expect(result.content[0]!.text).toContain('## Visualizations')
            expect(result.content[0]!.text).toContain('### Rendering visualizations')
        })

        it('lists render-ui alongside exec when render-ui is enabled and a UI-app tool is available', async () => {
            const state = makeState([uiAppTool], { useSingleExec: true, renderUiEnabled: true })

            const result = await executor.handleToolsList(state)
            expect(result.tools.map((t) => t.name)).toEqual(['exec', 'exec-write', 'render-ui'])

            // The advertised schema is derived from the zod validation schema —
            // pin the contract the agent writes calls against.
            const renderUiEntry = result.tools[2]!
            const properties = renderUiEntry.inputSchema.properties as Record<string, Record<string, unknown>>
            expect(properties.tool_name!.enum).toEqual(['survey-get'])
            expect(properties.tool_name!.description).toBeTruthy()
            expect(properties.tool_input!.description).toBeTruthy()
            expect(renderUiEntry.inputSchema.required).toEqual(['tool_name'])
        })

        it('omits render-ui when render-ui is disabled, even with a UI-app tool available', async () => {
            const state = makeState([uiAppTool], { useSingleExec: true, renderUiEnabled: false })

            const result = await executor.handleToolsList(state)
            expect(result.tools.map((t) => t.name)).toEqual(['exec', 'exec-write'])
        })
    })

    // Proves the `exec` vs `exec-write` transport name is wired to the read-only flag:
    // a write-capable tool must be refused on `exec` (so an always-allow can't
    // auto-approve a mutation) and pass the gate on `exec-write`.
    describe('exec read/write dispatch', () => {
        function fullToolState(): ResolvedState {
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

        function firstWriteToolName(): string {
            const entry = catalog.getPreBuiltEntries().find((e) => e.annotations?.readOnlyHint === false)
            if (!entry) {
                throw new Error('expected at least one write-capable tool in the catalog')
            }
            return entry.name
        }

        it('refuses a write-tool call on the read-only exec dispatcher', async () => {
            const result = (await executor.handleToolCall(
                { name: 'exec', arguments: { command: `call ${firstWriteToolName()} {}` } },
                fullToolState()
            )) as any
            expect(result.isError).toBe(true)
            expect(result.content[0].text).toContain('exec-write')
        })

        it('lets the same write-tool call past the gate on exec-write', async () => {
            const result = (await executor.handleToolCall(
                { name: 'exec-write', arguments: { command: `call ${firstWriteToolName()} {}` } },
                fullToolState()
            )) as any
            // Whatever happens after the gate (validation / API error) must not be the
            // read-only refusal — otherwise exec-write couldn't run mutations at all.
            const text = result.isError ? result.content[0].text : JSON.stringify(result)
            expect(text).not.toContain('read-only')
        })
    })

    describe('render-ui', () => {
        it('dispatches to the render-ui payload when render-ui is enabled', async () => {
            const state = makeState([uiAppTool], { useSingleExec: true, renderUiEnabled: true })

            const result = (await executor.handleToolCall(
                { name: 'render-ui', arguments: { tool_name: 'survey-get', tool_input: { surveyId: 'abc' } } },
                state
            )) as any

            expect(result._meta.ui.resourceUri).toBe(RENDER_UI_RESOURCE_URI)
            expect(result.structuredContent.tool_name).toBe('survey-get')
            expect(result.structuredContent.app_key).toBe('survey')
        })

        it('rejects a render-ui call when render-ui is disabled', async () => {
            const state = makeState([uiAppTool], { useSingleExec: true, renderUiEnabled: false })

            const result = (await executor.handleToolCall(
                { name: 'render-ui', arguments: { tool_name: 'survey-get', tool_input: { surveyId: 'abc' } } },
                state
            )) as any

            expect(result.isError).toBe(true)
            expect(result.content[0].text).toContain('not found')
        })
    })
})
