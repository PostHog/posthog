import guidelines from '@shared/guidelines.md'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { format } from 'oxfmt'
import { describe, expect, it } from 'vitest'
import { parse as parseYaml } from 'yaml'
import { z } from 'zod'

import { InstructionsFormatter } from '@/lib/instructions-formatter'
import { SessionManager } from '@/lib/SessionManager'
import { getToolsFromContext } from '@/tools'
import { createExecTool, type ExecInnerCallProperties, parseExecCallInnerToolName } from '@/tools/exec'
import { getToolDefinition } from '@/tools/toolDefinitions'
import {
    POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY,
    POSTHOG_META_KEY,
    type Context,
    type Tool,
    type ZodObjectAny,
} from '@/tools/types'

function makeMockTool(overrides: Partial<Tool<ZodObjectAny>> = {}): Tool<ZodObjectAny> {
    return {
        name: 'mock-tool',
        title: 'Mock tool',
        description: 'A mock tool for testing',
        schema: z.object({}),
        scopes: [],
        annotations: {
            destructiveHint: false,
            idempotentHint: true,
            openWorldHint: false,
            readOnlyHint: true,
        },
        handler: async () => ({ id: 1, name: 'test', items: [{ a: 1 }, { a: 2 }] }),
        ...overrides,
    }
}

const mockContext = {
    getDistinctId: async () => 'test-distinct-id',
} as unknown as Context

function createExec(tools: Tool<ZodObjectAny>[] = [makeMockTool()], mcpConsumer?: string): Tool<any> {
    return createExecTool(tools, mockContext, 'test description', 'test command reference', mcpConsumer)
}

describe('exec tool', () => {
    describe('call command', () => {
        it('returns TOON-formatted output by default', async () => {
            const exec = createExec()
            const result = await exec.handler(mockContext, { command: 'call mock-tool' })
            // TOON format uses "key: value" style, not JSON
            expect(result).toContain('id: 1')
            expect(result).toContain('name: test')
            expect(result).not.toBe(JSON.stringify({ id: 1, name: 'test', items: [{ a: 1 }, { a: 2 }] }))
        })

        it('returns raw JSON when --json flag is passed in command', async () => {
            const exec = createExec()
            const result = await exec.handler(mockContext, { command: 'call --json mock-tool' })
            const parsed = JSON.parse(result as string)
            expect(parsed).toEqual({ id: 1, name: 'test', items: [{ a: 1 }, { a: 2 }] })
        })

        it('returns JSON for tool with outputFormat json even without --json flag', async () => {
            const tool = makeMockTool({ _meta: { [POSTHOG_META_KEY]: { outputFormat: 'json' } } })
            const exec = createExec([tool])
            const result = await exec.handler(mockContext, { command: 'call mock-tool' })
            const parsed = JSON.parse(result as string)
            expect(parsed).toEqual({ id: 1, name: 'test', items: [{ a: 1 }, { a: 2 }] })
        })

        it('returns JSON when both --json flag and tool meta outputFormat=json are present', async () => {
            const tool = makeMockTool({ _meta: { [POSTHOG_META_KEY]: { outputFormat: 'json' } } })
            const exec = createExec([tool])
            const result = await exec.handler(mockContext, { command: 'call --json mock-tool' })
            const parsed = JSON.parse(result as string)
            expect(parsed).toEqual({ id: 1, name: 'test', items: [{ a: 1 }, { a: 2 }] })
        })

        it('returns ONLY the formatted table when result has __formatted_results_override and mode is optimized', async () => {
            const tool = makeMockTool({
                handler: async () => ({
                    results: [{ data: [1, 2, 3], count: 6 }],
                    _posthogUrl: 'http://localhost:8010/insights/new#q=...',
                    [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: 'Date|count\n2026-05-07|6',
                }),
            })
            const exec = createExec([tool])
            const result = await exec.handler(mockContext, { command: 'call mock-tool' })
            expect(result).toBe('Date|count\n2026-05-07|6')
            // Raw fields and the override key itself must not leak into optimized output
            expect(result).not.toContain('_posthogUrl')
            expect(result).not.toContain('results')
            expect(result).not.toContain('__formatted_results_override')
        })

        it('still TOON-encodes when __formatted_results_override is absent', async () => {
            const tool = makeMockTool({
                handler: async () => ({
                    results: [{ data: [1, 2, 3], count: 6 }],
                    _posthogUrl: 'http://localhost:8010/insights/new#q=...',
                }),
            })
            const exec = createExec([tool])
            const result = (await exec.handler(mockContext, { command: 'call mock-tool' })) as string
            expect(result).toContain('_posthogUrl')
            expect(result).toContain('results')
        })

        it('returns raw JSON (with override key) when --json flag is passed even if override is present', async () => {
            const tool = makeMockTool({
                handler: async () => ({
                    results: [{ data: [1, 2, 3] }],
                    [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: 'Date|count\n2026-05-07|6',
                }),
            })
            const exec = createExec([tool])
            const result = await exec.handler(mockContext, { command: 'call --json mock-tool' })
            const parsed = JSON.parse(result as string)
            expect(parsed.results).toEqual([{ data: [1, 2, 3] }])
            expect(parsed[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBe('Date|count\n2026-05-07|6')
        })

        it('throws usage error for bare call', async () => {
            const exec = createExec()
            await expect(exec.handler(mockContext, { command: 'call' })).rejects.toThrow(
                'Usage: call [--json] <tool_name> <json_input>'
            )
        })

        it('throws usage error for call --json with no tool name', async () => {
            const exec = createExec()
            await expect(exec.handler(mockContext, { command: 'call --json' })).rejects.toThrow(
                'Usage: call [--json] <tool_name> <json_input>'
            )
        })

        it('propagates _meta.ui.resourceUri and structuredContent when the inner tool has a UI app and consumer is posthog-code', async () => {
            const tool = makeMockTool({
                _meta: { ui: { resourceUri: 'ui://posthog/mock-app.html' } },
            })
            const exec = createExec([tool], 'posthog-code')
            const result = (await exec.handler(mockContext, { command: 'call mock-tool' })) as {
                content: { type: string; text: string }[]
                structuredContent: { id: number; name: string; _analytics: { distinctId: string; toolName: string } }
                _meta: { ui: { resourceUri: string }; [key: string]: unknown }
                __execBuiltPayload?: true
            }

            // Text content still includes the TOON-formatted result for model context
            expect(result.content[0]!.text).toContain('id: 1')
            // structuredContent carries the raw object plus analytics for the UI app
            expect(result.structuredContent.id).toBe(1)
            expect(result.structuredContent._analytics).toEqual({
                distinctId: 'test-distinct-id',
                toolName: 'mock-tool',
            })
            // _meta on the response exposes the UI resource URI to clients that
            // only see the `exec` tool registered (single-exec mode). Both the
            // new nested key and the legacy flat key are emitted for
            // compatibility with older MCP clients.
            expect(result._meta.ui.resourceUri).toBe('ui://posthog/mock-app.html')
            expect(result._meta['ui/resourceUri']).toBe('ui://posthog/mock-app.html')
            // The nominal brand is what `MCP.registerTool` uses to pass the payload
            // through unchanged; without it the outer wrapper would re-run
            // buildToolResultPayload and object-rest-destructure the content.
            expect(result.__execBuiltPayload).toBe(true)
        })

        it.each([[undefined], ['cline'], ['claude-code'], ['slack'], ['posthog_code']])(
            'returns plain text (no UI payload) when consumer is %s even if the inner tool has a UI app',
            async (consumer) => {
                const tool = makeMockTool({
                    _meta: { ui: { resourceUri: 'ui://posthog/mock-app.html' } },
                })
                const exec = createExec([tool], consumer)
                const result = await exec.handler(mockContext, { command: 'call mock-tool' })
                expect(typeof result).toBe('string')
            }
        )

        it('does not attach UI meta or structuredContent for tools without a UI app', async () => {
            const exec = createExec()
            const result = await exec.handler(mockContext, { command: 'call mock-tool' })
            // Plain text fallback — no CallToolResult shape leaks out
            expect(typeof result).toBe('string')
        })

        it('invokes the inner-call tracker on successful inner tool dispatch', async () => {
            const calls: { toolName: string; properties: ExecInnerCallProperties }[] = []
            const tracker = (toolName: string, properties: ExecInnerCallProperties): void => {
                calls.push({ toolName, properties })
            }
            const exec = createExecTool(
                [makeMockTool()],
                mockContext,
                'test description',
                'test command reference',
                undefined,
                tracker
            )
            await exec.handler(mockContext, { command: 'call --json mock-tool' })
            expect(calls).toHaveLength(1)
            expect(calls[0]!.toolName).toBe('mock-tool')
            expect(calls[0]!.properties.success).toBe(true)
            expect(calls[0]!.properties.output_format).toBe('json')
            expect(typeof calls[0]!.properties.duration_ms).toBe('number')
        })

        it('passes inline JSON arguments to the inner tool', async () => {
            const tool = makeMockTool({
                schema: z.object({ name: z.string(), tags: z.array(z.string()) }),
                handler: async (_ctx, params) => params,
            })
            const exec = createExec([tool])
            const result = await exec.handler(mockContext, {
                command: 'call --json mock-tool {"name":"foo","tags":["a","b"]}',
            })
            expect(JSON.parse(result as string)).toEqual({ name: 'foo', tags: ['a', 'b'] })
        })

        it('preserves quote-heavy and multi-line content in inline JSON', async () => {
            const tool = makeMockTool({
                schema: z.object({ name: z.string(), content: z.string() }),
                handler: async (_ctx, params) => params,
            })
            const exec = createExec([tool])
            const content = '# Title\n\nLine with "double quotes", \'single quotes\', and `backticks` — also unicode ☃.'
            const payload = JSON.stringify({ name: 'skill', content })
            const result = await exec.handler(mockContext, {
                command: `call --json mock-tool ${payload}`,
            })
            expect(JSON.parse(result as string)).toEqual({ name: 'skill', content })
        })

        it('throws a descriptive error when the inline JSON body is malformed', async () => {
            const exec = createExec()
            await expect(
                exec.handler(mockContext, {
                    command: 'call mock-tool {not-json}',
                })
            ).rejects.toThrow(/Invalid JSON input:/)
        })

        it('invokes the inner-call tracker with success=false when the inner tool throws', async () => {
            const calls: { toolName: string; properties: ExecInnerCallProperties }[] = []
            const tracker = (toolName: string, properties: ExecInnerCallProperties): void => {
                calls.push({ toolName, properties })
            }
            const failing = makeMockTool({
                handler: async () => {
                    throw new Error('boom')
                },
            })
            const exec = createExecTool(
                [failing],
                mockContext,
                'test description',
                'test command reference',
                undefined,
                tracker
            )
            await expect(exec.handler(mockContext, { command: 'call mock-tool' })).rejects.toThrow('boom')
            expect(calls).toHaveLength(1)
            expect(calls[0]!.properties.success).toBe(false)
            expect(calls[0]!.properties.error_message).toBe('boom')
            expect(calls[0]!.properties.output_format).toBe('text')
        })
    })

    describe('info command', () => {
        it('returns YAML for the top shape with the input schema embedded as JSON', async () => {
            const tool = makeMockTool({ schema: z.object({ name: z.string().describe('Person name') }) })
            const exec = createExec([tool])
            const result = (await exec.handler(mockContext, { command: 'info mock-tool' })) as string
            expect(typeof result).toBe('string')
            // YAML lines for the top shape
            expect(result).toContain('name: mock-tool')
            expect(result).toContain('title: Mock tool')
            // The whole envelope is not JSON
            expect(() => JSON.parse(result)).toThrow()
            // inputSchema is dumped as a JSON string within the YAML — parse the
            // envelope as YAML, then JSON.parse the inputSchema value.
            const envelope = parseYaml(result) as { inputSchema: string }
            expect(typeof envelope.inputSchema).toBe('string')
            const parsedSchema = JSON.parse(envelope.inputSchema)
            expect(parsedSchema.type).toBe('object')
            expect(parsedSchema.properties.name.description).toBe('Person name')
        })

        it('returns JSON when --json flag is passed in command', async () => {
            const exec = createExec()
            const result = (await exec.handler(mockContext, {
                command: 'info --json mock-tool',
            })) as string
            const parsed = JSON.parse(result)
            expect(parsed.name).toBe('mock-tool')
            expect(parsed.title).toBe('Mock tool')
            expect(parsed.description).toBe('A mock tool for testing')
            // In JSON mode, inputSchema is a real object, not a JSON string
            expect(typeof parsed.inputSchema).toBe('object')
        })

        it('bakes the drill-down imperative into each complex field hint when info is summarized', async () => {
            const wideShape: Record<string, z.ZodType> = {}
            for (let i = 0; i < 1500; i++) {
                wideShape[`field_${i}`] = z.string().describe(`Description for field ${i} with extra padding text`)
            }
            const tool = makeMockTool({
                schema: z.object({
                    name: z.string(),
                    filter: z.object({ key: z.string() }),
                    wide: z.object(wideShape),
                }),
            })
            const exec = createExec([tool])
            const result = (await exec.handler(mockContext, { command: 'info mock-tool' })) as string
            const envelope = parseYaml(result) as { note?: string; inputSchema: string }
            // The directive lives on the field the model is about to populate,
            // not as a separate top-level note it can skim past.
            expect(envelope.note).toBeUndefined()
            const parsedSchema = JSON.parse(envelope.inputSchema)
            expect(parsedSchema.properties.filter.hint).toContain('DO NOT GUESS')
            expect(parsedSchema.properties.filter.hint).toContain('schema mock-tool filter')
            expect(parsedSchema.properties.filter.hint).toContain('before populating this field')
            expect(parsedSchema.properties.wide.hint).toContain('schema mock-tool wide')
            // Scalar fields carry no hint — nothing to drill into.
            expect(parsedSchema.properties.name.hint).toBeUndefined()
        })

        it('throws usage error for bare info', async () => {
            const exec = createExec()
            await expect(exec.handler(mockContext, { command: 'info' })).rejects.toThrow(
                'Usage: info [--json] <tool_name>'
            )
        })

        it('throws usage error for info --json with no tool name', async () => {
            const exec = createExec()
            await expect(exec.handler(mockContext, { command: 'info --json' })).rejects.toThrow(
                'Usage: info [--json] <tool_name>'
            )
        })
    })

    describe('schema command', () => {
        it('throws usage error for bare schema', async () => {
            const exec = createExec()
            await expect(exec.handler(mockContext, { command: 'schema' })).rejects.toThrow(
                'Usage: schema <tool_name> [field_path]'
            )
        })

        it('returns the resolved sub-schema inline when small enough', async () => {
            const tool = makeMockTool({
                schema: z.object({
                    name: z.string(),
                    filter: z.object({ key: z.string(), value: z.number() }),
                }),
            })
            const exec = createExec([tool])
            const result = (await exec.handler(mockContext, { command: 'schema mock-tool filter' })) as string
            const parsed = JSON.parse(result)
            expect(parsed.field).toBe('filter')
            // Small sub-schema: the full resolved JSON Schema is inlined as-is
            expect(parsed.schema.type).toBe('object')
            expect(parsed.schema.properties).toEqual(
                expect.objectContaining({
                    key: expect.objectContaining({ type: 'string' }),
                    value: expect.objectContaining({ type: 'number' }),
                })
            )
            // No drill-down note for an already-inlined schema
            expect(parsed.note).toBeUndefined()
        })

        // The bare `schema <tool>` view is the recursive step where models
        // historically guessed the deeper shape of complex fields (like `series`
        // or `retentionFilter`) rather than running another `schema` for the
        // sub-path. The imperative now rides on each complex field's `hint` —
        // the runtime nudge that pairs with the prompt-side guidance in
        // `cli-schema-drilldown.md`.
        it('bakes the drill-down imperative into each complex field hint of the bare schema view', async () => {
            const tool = makeMockTool({
                schema: z.object({
                    name: z.string(),
                    filter: z.object({ key: z.string() }),
                }),
            })
            const exec = createExec([tool])
            const result = (await exec.handler(mockContext, { command: 'schema mock-tool' })) as string
            const parsed = JSON.parse(result)
            // Flat summary, no separate note wrapper.
            expect(parsed.note).toBeUndefined()
            expect(parsed.schema).toBeUndefined()
            expect(parsed.properties.filter.hint).toContain('DO NOT GUESS')
            expect(parsed.properties.filter.hint).toContain('schema mock-tool filter')
            expect(parsed.properties.filter.hint).toContain('before populating this field')
            // Scalar fields do not earn a hint
            expect(parsed.properties.name.hint).toBeUndefined()
        })

        it('does not attach a drill-down directive when no field carries a hint', async () => {
            const tool = makeMockTool({
                schema: z.object({ name: z.string(), count: z.number() }),
            })
            const exec = createExec([tool])
            const result = (await exec.handler(mockContext, { command: 'schema mock-tool' })) as string
            const parsed = JSON.parse(result)
            // Without hints, the response is just the raw summary — no `note`
            // wrapper to distract the model when there's nothing to drill into.
            expect(parsed.note).toBeUndefined()
            expect(parsed.schema).toBeUndefined()
            expect(parsed.type).toBe('object')
            expect(parsed.properties.name.type).toBe('string')
        })

        it('returns a summary in the same { field, schema } shape when a sub-field overflows the budget', async () => {
            // Build a sub-field large enough to exceed TOKEN_CHAR_LIMIT (~48k chars)
            // once serialized. Each property entry is ~70 chars, so 1500 of them
            // comfortably crosses the threshold.
            const wideShape: Record<string, z.ZodType> = {}
            for (let i = 0; i < 1500; i++) {
                wideShape[`field_${i}`] = z.string().describe(`Description for field ${i} with extra padding text`)
            }
            const tool = makeMockTool({
                schema: z.object({ wide: z.object(wideShape) }),
            })
            const exec = createExec([tool])
            const result = (await exec.handler(mockContext, { command: 'schema mock-tool wide' })) as string
            const parsed = JSON.parse(result)
            expect(parsed.field).toBe('wide')
            // No top-level note — `hint` is the only drill-down signal in the response.
            expect(parsed.note).toBeUndefined()
            // Summary still preserves field names so the model can pick where to drill
            expect(Object.keys(parsed.schema.properties).length).toBeGreaterThan(0)
        })

        it('errors with available paths when the field path is unknown', async () => {
            const tool = makeMockTool({
                schema: z.object({ name: z.string(), filter: z.object({ key: z.string() }) }),
            })
            const exec = createExec([tool])
            await expect(exec.handler(mockContext, { command: 'schema mock-tool nope' })).rejects.toThrow(
                /Unknown path "nope"\. Available: name, filter/
            )
        })

        // Eval case for `query-retention`, the canonical large-schema query tool
        // (>200k chars when fully serialized). Validates the end-to-end drill-down
        // flow against the real tool: bare schema → imperative hints → drill
        // → resolved sub-schema. If the hint imperative ever loosens or the
        // schema-summary pipeline regresses, this test catches it.
        it('eval: query-retention bare schema view produces imperative hints, and a drilled sub-field resolves', async () => {
            const context: Context = {
                api: {} as any,
                cache: {} as any,
                env: {
                    MCP_APPS_BASE_URL: undefined,
                    POSTHOG_ANALYTICS_API_KEY: undefined,
                    POSTHOG_ANALYTICS_HOST: undefined,
                    POSTHOG_API_BASE_URL: undefined,
                    POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
                    POSTHOG_UI_APPS_TOKEN: undefined,
                },
                stateManager: {
                    getApiKey: async () => ({ scopes: ['*'] }),
                    getAiConsentGiven: async () => true,
                } as any,
                sessionManager: new SessionManager({} as any),
                getDistinctId: async () => 'test-distinct-id',
                trackEvent: async () => {},
            }
            const v2Tools = await getToolsFromContext(context)
            const queryRetention = v2Tools.find((t) => t.name === 'query-retention')
            expect(queryRetention).not.toBeUndefined()
            const exec = createExecTool(v2Tools, context, 'test', 'test', undefined)

            // 1. Bare `schema query-retention` returns a flat summary whose
            // complex fields carry the drill-down imperative in their hints.
            const bare = JSON.parse((await exec.handler(context, { command: 'schema query-retention' })) as string) as {
                note?: string
                properties: Record<string, { hint?: string; type?: string }>
            }
            expect(bare.note).toBeUndefined()
            // At least one of retention's complex fields must surface a hint —
            // the exact set varies with schema generation, so we assert by shape
            // (presence of any hint) rather than naming a specific field.
            const hintedFields = Object.entries(bare.properties).filter(([, v]) => v.hint !== undefined)
            expect(hintedFields.length).toBeGreaterThan(0)
            for (const [, v] of hintedFields) {
                expect(v.hint).toMatch(
                    /^DO NOT GUESS — you MUST run `schema query-retention [\w.]+` before populating this field$/
                )
            }

            // 2. Drill into the first hinted sub-field. The follow-up always
            // returns the same `{ field, schema }` shape — either with the full
            // resolved JSON Schema (small enough to inline) or with a summary
            // whose complex sub-fields carry their own hints. No top-level note
            // distinguishes the two; the model reads the hints either way.
            const [firstHintedField] = hintedFields[0]!
            const drilled = JSON.parse(
                (await exec.handler(context, {
                    command: `schema query-retention ${firstHintedField}`,
                })) as string
            ) as { field?: string; note?: string; schema?: unknown }
            expect(drilled.field).toBe(firstHintedField)
            expect(drilled.note).toBeUndefined()
            expect(drilled.schema).not.toBeUndefined()
        })
    })

    describe('deprecated tool redirects', () => {
        it.each([
            ['entity-search', 'execute-sql'],
            ['event-definitions-list', 'read-data-schema'],
            ['properties-list', 'read-data-schema'],
            ['property-definitions', 'read-data-schema'],
            ['query-generate-hogql-from-question', 'execute-sql'],
            ['query-run', 'execute-sql'],
        ])('throws redirect when calling deprecated %s', async (deprecated, replacement) => {
            const exec = createExec()
            await expect(exec.handler(mockContext, { command: `call ${deprecated} {}` })).rejects.toThrow(
                new RegExp(`was removed[\\s\\S]*${replacement}`)
            )
        })

        it('lists available query-* tools when query-run is called', async () => {
            const queryTrends = makeMockTool({ name: 'query-trends', description: 'Run a trends query' })
            const exec = createExec([queryTrends])
            await expect(exec.handler(mockContext, { command: 'call query-run {}' })).rejects.toThrow(/query-trends/)
        })
    })

    describe('parseExecCallInnerToolName', () => {
        it.each([
            ['call my-tool {}', 'my-tool'],
            ['call my-tool', 'my-tool'],
            ['call --json my-tool {}', 'my-tool'],
            ['  call   my-tool   {}  ', 'my-tool'],
        ])('extracts inner tool name from "%s"', (command, expected) => {
            expect(parseExecCallInnerToolName(command)).toBe(expected)
        })

        // Non-call verbs (info/schema/search/tools) are intentionally undefined —
        // the resolver only fires for real invocations, not for browsing/inspection.
        it.each([
            ['info my-tool'],
            ['schema my-tool'],
            ['search query-'],
            ['tools'],
            ['call'],
            ['call '],
            ['call --json'],
            [''],
            ['   '],
        ])('returns undefined for "%s"', (command) => {
            expect(parseExecCallInnerToolName(command)).toBeUndefined()
        })
    })

    describe('schema snapshot', () => {
        function createSnapshotContext(): Context {
            return {
                api: {} as any,
                cache: {} as any,
                env: {
                    MCP_APPS_BASE_URL: undefined,
                    POSTHOG_ANALYTICS_API_KEY: undefined,
                    POSTHOG_ANALYTICS_HOST: undefined,
                    POSTHOG_API_BASE_URL: undefined,
                    POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
                    POSTHOG_UI_APPS_TOKEN: undefined,
                },
                stateManager: {
                    getApiKey: async () => ({ scopes: ['*'] }),
                    getAiConsentGiven: async () => true,
                } as any,
                sessionManager: new SessionManager({} as any),
                getDistinctId: async () => 'test-distinct-id',
                trackEvent: async () => {},
            }
        }

        // Claude Code truncates tool descriptions after 2048 characters, so the
        // exec tool's description must fit within that budget or clients will
        // silently drop the tail of the instructions.
        it('keeps the tool description within 2048 characters', async () => {
            const context = createSnapshotContext()
            const v2Tools = await getToolsFromContext(context)
            const toolInfos = v2Tools.map((t) => ({
                name: t.name,
                category: getToolDefinition(t.name).category,
            }))
            const queryToolInfos = v2Tools
                .filter((t) => t.name.startsWith('query-'))
                .map((t) => {
                    const def = getToolDefinition(t.name)
                    return {
                        name: t.name,
                        title: def.title,
                        ...(def.system_prompt_hint ? { systemPromptHint: def.system_prompt_hint } : {}),
                    }
                })
            const formatter = new InstructionsFormatter()
            const commandReference = formatter.buildExecCommandReference(
                { guidelines, tools: toolInfos, queryTools: queryToolInfos },
                { stripEnvContext: false }
            )
            const execTool = createExecTool(
                v2Tools,
                context,
                formatter.buildExecToolDescription(),
                commandReference,
                undefined
            )

            expect(execTool.description.length).toBeLessThanOrEqual(2048)
        })

        // Snapshots the full exec tool definition built from the real v2 tool set:
        // description (the `exec-tool-blurb` subprompt), annotations, and input schema
        // including the `command` field description — which embeds the generated
        // `tool_domains` block. Because `buildToolDomainsBlock` relies on tool-name conventions
        // (CRUD suffixes, prefix actions, plural collapsing), this snapshot is the
        // canary for any drift in naming or in the domain-extraction logic.
        //
        // Snapshots the Codex (`supportsInstructions: false`) wiring, where every
        // placeholder is filled. That's the only path where `{tool_domains}` and
        // `{query_tools}` actually appear in the `command` parameter description,
        // so the snapshot has to follow it to keep catching drift in those blocks.
        it('matches the full exec tool schema', async () => {
            const context = createSnapshotContext()
            const v2Tools = [...(await getToolsFromContext(context))].sort((a, b) =>
                a.name.localeCompare(b.name)
            )
            const toolInfos = v2Tools.map((t) => ({
                name: t.name,
                category: getToolDefinition(t.name).category,
            }))
            const queryToolInfos = v2Tools
                .filter((t) => t.name.startsWith('query-'))
                .map((t) => {
                    const def = getToolDefinition(t.name)
                    return {
                        name: t.name,
                        title: def.title,
                        ...(def.system_prompt_hint ? { systemPromptHint: def.system_prompt_hint } : {}),
                    }
                })
            const formatter = new InstructionsFormatter()
            const commandReference = formatter.buildExecCommandReference(
                { guidelines, tools: toolInfos, queryTools: queryToolInfos },
                { stripEnvContext: false }
            )
            const execTool = createExecTool(
                v2Tools,
                context,
                formatter.buildExecToolDescription(),
                commandReference,
                undefined
            )

            const snapshot = {
                name: execTool.name,
                title: execTool.title,
                description: execTool.description,
                annotations: execTool.annotations,
                scopes: execTool.scopes,
                inputSchema: z.toJSONSchema(execTool.schema, { io: 'input', reused: 'inline' }),
            }

            const __dirname = path.dirname(fileURLToPath(import.meta.url))
            const snapshotPath = path.resolve(__dirname, '__snapshots__', 'exec-tool.json')
            // Format via oxfmt so the snapshot matches repo-wide formatting rules
            // (lint-staged reformats *.json and would otherwise flip this file on save).
            const content = `${JSON.stringify(snapshot, null, 4)}\n`
            const result = await format(snapshotPath, content, { tabWidth: 4, printWidth: 120 })
            if (result.errors.length > 0) {
                throw new Error(
                    `Failed formatting snapshot: ${result.errors.map((e) => e.message ?? 'unknown').join('; ')}`
                )
            }
            await expect(result.code).toMatchFileSnapshot(snapshotPath)
        })
    })
})
