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

import { MCP_EXEC_SKILLS_FEATURE_FLAG } from '@/hono/constants'
import { InstructionsBuilder } from '@/hono/instructions'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { ToolCatalog } from '@/hono/tool-catalog'
import { ToolExecutor } from '@/hono/tool-executor'
import { buildToolDomainsCompact } from '@/lib/instructions'
import { RENDER_UI_RESOURCE_URI, URI_MAP } from '@/resources/ui-apps.generated'
import { SkillCatalog } from '@/skills/skill-catalog'
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

        it('returns single exec tool entry when useSingleExec is true', async () => {
            const state = makeState(
                catalog
                    .getPreBuiltEntries()
                    .slice(0, 5)
                    .map((e) => ({ name: e.name })),
                { useSingleExec: true }
            )

            const result = await executor.handleToolsList(state)
            expect(result.tools).toHaveLength(1)
            expect(result.tools[0]!.name).toBe('exec')
        })

        it.each([
            {
                label: 'Claude web/desktop with flag off',
                isClaudeChatHost: true,
                skillsEnabled: false,
                pluginConsumer: false,
                expectGuides: true,
                expectSkills: false,
            },
            {
                label: 'Claude web/desktop with flag on',
                isClaudeChatHost: true,
                skillsEnabled: true,
                pluginConsumer: false,
                expectGuides: true,
                expectSkills: true,
            },
            {
                label: 'Claude Code with flag off',
                isClaudeChatHost: false,
                skillsEnabled: false,
                pluginConsumer: false,
                expectGuides: false,
                expectSkills: false,
            },
            {
                label: 'Claude Code with flag on',
                isClaudeChatHost: false,
                skillsEnabled: true,
                pluginConsumer: false,
                expectGuides: false,
                expectSkills: true,
            },
            {
                label: 'plugin consumer with flag on',
                isClaudeChatHost: true,
                skillsEnabled: true,
                pluginConsumer: true,
                expectGuides: false,
                expectSkills: false,
            },
        ])(
            'advertises and serves the expected learn capabilities for $label',
            async ({ isClaudeChatHost, skillsEnabled, pluginConsumer, expectGuides, expectSkills }) => {
                const skills = new SkillCatalog([
                    {
                        name: 'sample-skill',
                        description: 'A sample skill.',
                        files: [
                            {
                                path: 'SKILL.md',
                                content: '# Sample skill',
                                lineCount: 1,
                                charCount: 14,
                                kind: 'markdown',
                            },
                        ],
                    },
                ])
                const skillExecutor = new ToolExecutor(catalog, new InstructionsBuilder(''), {
                    getCatalog: () => skills,
                } as any)
                const state = makeState([], {
                    useSingleExec: true,
                    toolFeatureFlags: { [MCP_EXEC_SKILLS_FEATURE_FLAG]: skillsEnabled },
                    clientProfile: {
                        capabilities: { supportsInstructions: true },
                        isCliModeEnabled: vi.fn(() => true),
                        isClaudeUiHost: vi.fn(() => isClaudeChatHost),
                        isInlineExecUiHost: vi.fn(() => false),
                        isClaudeChatHost: vi.fn(() => isClaudeChatHost),
                    } as any,
                    ...(pluginConsumer
                        ? {
                              sessionContext: {
                                  mcpClientName: 'claude-ai',
                                  mcpClientVersion: '1.0',
                                  mcpProtocolVersion: '2025-03-26',
                                  mcpConsumer: 'plugin',
                                  mcpVendorClient: undefined,
                              },
                          }
                        : {}),
                })

                const listed = await skillExecutor.handleToolsList(state)
                const commandDescription = (listed.tools[0]!.inputSchema.properties as any).command
                    .description as string
                const advertisesSkills =
                    commandDescription.includes('learn posthog:<skill>') ||
                    commandDescription.includes('(posthog|project):<skill>')
                expect(commandDescription.includes('- analytics:')).toBe(expectGuides)
                expect(advertisesSkills).toBe(expectSkills)
                expect(commandDescription.includes('**SKILLS FIRST: HARD REQUIREMENT**')).toBe(expectSkills)
                expect(commandDescription.includes('never batch or parallelize it')).toBe(expectSkills)
                expect(commandDescription.includes('learn <topic...>')).toBe(expectGuides)

                const result = (await skillExecutor.handleToolCall(
                    { name: 'exec', arguments: { command: 'learn' } },
                    state
                )) as { content: { text: string }[]; isError?: boolean }
                if (!expectGuides && !expectSkills) {
                    expect(result.isError).toBe(true)
                    expect(result.content[0]!.text).toContain('learn command is not available')
                    return
                }

                const catalogResult = JSON.parse(result.content[0]!.text)
                expect(catalogResult.guides.length > 0).toBe(expectGuides)
                expect('skills' in catalogResult).toBe(expectSkills)

                if (!expectSkills) {
                    const skillResult = (await skillExecutor.handleToolCall(
                        { name: 'exec', arguments: { command: 'learn skills' } },
                        state
                    )) as { content: { text: string }[]; isError?: boolean }
                    expect(skillResult.isError).toBeFalsy()
                    expect(JSON.parse(skillResult.content[0]!.text)).toEqual({
                        available: false,
                        reason: 'Skill discovery is not enabled for this connection.',
                    })
                }
            }
        )

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

        it('serves the runtime product skill catalog to non-plugin consumers', async () => {
            const skills = new SkillCatalog([
                {
                    name: 'sample-skill',
                    description: 'A sample skill.',
                    files: [
                        {
                            path: 'SKILL.md',
                            content: '# Sample skill',
                            lineCount: 1,
                            charCount: 14,
                            kind: 'markdown',
                        },
                    ],
                },
            ])
            const skillExecutor = new ToolExecutor(catalog, new InstructionsBuilder(''), {
                getCatalog: () => skills,
            } as any)
            const state = makeState([], { useSingleExec: true })
            state.toolFeatureFlags = { [MCP_EXEC_SKILLS_FEATURE_FLAG]: true }

            const result = (await skillExecutor.handleToolCall(
                { name: 'exec', arguments: { command: 'learn skills' } },
                state
            )) as { content: { text: string }[] }

            expect(result.content[0]!.text).toContain('sample-skill')
        })

        it('discovers and searches current-project skills when the connection has read scope', async () => {
            const apiRequest = vi.fn().mockImplementation(async ({ path }: { path: string }) => {
                if (path.endsWith('/search/')) {
                    return {
                        count: 1,
                        results: [
                            {
                                name: 'team-retention',
                                description: 'Project-specific retention guidance.',
                                matches: [
                                    {
                                        matched_field: 'body',
                                        path: 'SKILL.md',
                                        line: 3,
                                        excerpt: 'Use weekly retention cohorts.',
                                    },
                                ],
                            },
                        ],
                    }
                }
                return { count: 1, results: [{ name: 'team-retention' }] }
            })
            const state = makeState([], {
                useSingleExec: true,
                toolFeatureFlags: { [MCP_EXEC_SKILLS_FEATURE_FLAG]: true },
                apiKeyScopes: ['llm_skill:read'],
                context: {
                    api: { request: apiRequest },
                    stateManager: { getProjectId: vi.fn().mockResolvedValue(12) },
                } as any,
            })

            const result = (await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'learn -s retention' } },
                state
            )) as { content: { text: string }[] }

            expect(result.content[0]!.text).toContain('## project:team-retention')
            expect(apiRequest).toHaveBeenCalledWith({
                method: 'GET',
                path: '/api/projects/12/llm_skills/search/',
                query: { query: 'retention' },
            })

            const listResult = (await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'learn skills' } },
                state
            )) as { content: { text: string }[] }
            expect(listResult.content[0]!.text).toContain('project:team-retention')
            expect(apiRequest).toHaveBeenCalledWith({
                method: 'GET',
                path: '/api/projects/12/llm_skills/',
                query: { category: '', limit: 100, offset: 0, order_by: 'name' },
            })
        })

        it('does not advertise or serve learn for the effective plugin consumer', async () => {
            const state = makeState(
                catalog
                    .getPreBuiltEntries()
                    .slice(0, 5)
                    .map(({ name }) => ({ name })),
                {
                    useSingleExec: true,
                    toolFeatureFlags: { [MCP_EXEC_SKILLS_FEATURE_FLAG]: true },
                    sessionContext: {
                        mcpClientName: 'claude-ai',
                        mcpClientVersion: '1.0',
                        mcpProtocolVersion: '2025-03-26',
                        mcpConsumer: 'plugin',
                        mcpVendorClient: undefined,
                    },
                }
            )

            const listed = await executor.handleToolsList(state)
            const commandDescription = (listed.tools[0]!.inputSchema.properties as any).command.description as string
            expect(commandDescription).not.toContain('learn <')

            const result = (await executor.handleToolCall(
                { name: 'exec', arguments: { command: 'learn' } },
                state
            )) as { content: { text: string }[]; isError?: boolean }
            expect(result.isError).toBe(true)
            expect(result.content[0]!.text).toContain('learn command is not available')
        })

        it('lists render-ui alongside exec when render-ui is enabled and a UI-app tool is available', async () => {
            const state = makeState([uiAppTool], { useSingleExec: true, renderUiEnabled: true })

            const result = await executor.handleToolsList(state)
            expect(result.tools.map((t) => t.name)).toEqual(['exec', 'render-ui'])

            // The advertised schema is derived from the zod validation schema —
            // pin the contract the agent writes calls against.
            const renderUiEntry = result.tools[1]!
            const properties = renderUiEntry.inputSchema.properties as Record<string, Record<string, unknown>>
            expect(properties.tool_name!.enum).toEqual(['survey-get'])
            expect(properties.tool_name!.description).toBeTruthy()
            expect(properties.tool_input!.description).toBeTruthy()
            expect(renderUiEntry.inputSchema.required).toEqual(['tool_name'])
        })

        it('omits render-ui when render-ui is disabled, even with a UI-app tool available', async () => {
            const state = makeState([uiAppTool], { useSingleExec: true, renderUiEnabled: false })

            const result = await executor.handleToolsList(state)
            expect(result.tools.map((t) => t.name)).toEqual(['exec'])
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
