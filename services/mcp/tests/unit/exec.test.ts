import guidelines from '@shared/guidelines.md'
import { describe, expect, it } from 'vitest'
import { parse as parseYaml } from 'yaml'
import { z } from 'zod'

import { ToolInputValidationError } from '@/lib/errors'
import { estimateTokens } from '@/lib/estimate-tokens'
import { buildQueryToolsBlock, buildToolDomainsCompact } from '@/lib/instructions'
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
import { APP_DATA_META_KEY } from '@/ui-apps/types'

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

function createExec(
    tools: Tool<ZodObjectAny>[] = [makeMockTool()],
    mcpConsumer?: string,
    options?: { isInlineExecUiHost?: boolean }
): Tool<any> {
    return createExecTool(
        tools,
        mockContext,
        'test description',
        'test command reference',
        mcpConsumer,
        undefined,
        [],
        options ?? {}
    )
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
                'Usage: call [--json] [--confirm] <tool_name> <json_input>'
            )
        })

        it('throws usage error for call --json with no tool name', async () => {
            const exec = createExec()
            await expect(exec.handler(mockContext, { command: 'call --json' })).rejects.toThrow(
                'Usage: call [--json] [--confirm] <tool_name> <json_input>'
            )
        })

        it('allows --confirm before --json when dispatching a call', async () => {
            const exec = createExec()
            const result = await exec.handler(mockContext, { command: 'call --confirm --json mock-tool' })
            const parsed = JSON.parse(result as string)
            expect(parsed).toEqual({ id: 1, name: 'test', items: [{ a: 1 }, { a: 2 }] })
        })

        it('requires --confirm for destructive tools when enabled', async () => {
            const destructive = makeMockTool({
                annotations: {
                    destructiveHint: true,
                    idempotentHint: true,
                    openWorldHint: false,
                    readOnlyHint: false,
                },
            })
            const exec = createExecTool(
                [destructive],
                mockContext,
                'test description',
                'test command reference',
                undefined,
                undefined,
                [],
                { requireDestructiveConfirmation: true }
            )

            await expect(exec.handler(mockContext, { command: 'call mock-tool' })).rejects.toThrow(
                'Tool "mock-tool" is destructive'
            )
            await expect(exec.handler(mockContext, { command: 'call --confirm --json mock-tool' })).resolves.toEqual(
                JSON.stringify({ id: 1, name: 'test', items: [{ a: 1 }, { a: 2 }] })
            )
        })

        it('propagates the UI resource URI and exec brand when the inner tool has a UI app and consumer is posthog-code', async () => {
            const tool = makeMockTool({
                _meta: { ui: { resourceUri: 'ui://posthog/mock-app.html' } },
            })
            const exec = createExec([tool], 'posthog-code')
            const result = (await exec.handler(mockContext, { command: 'call mock-tool' })) as {
                content: { type: string; text: string }[]
                structuredContent?: Record<string, unknown>
                _meta: { ui: { resourceUri: string }; [key: string]: unknown }
                __execBuiltPayload?: true
            }

            // Text content still includes the TOON-formatted result for model context
            expect(result.content[0]!.text).toContain('id: 1')
            // structuredContent is dropped; the UI data (with analytics) rides on _meta.
            expect(result.structuredContent).toBeUndefined()
            const appData = result._meta[APP_DATA_META_KEY] as {
                id: number
                _analytics: { distinctId: string; toolName: string }
            }
            expect(appData.id).toBe(1)
            expect(appData._analytics).toEqual({
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

        // Inline-exec UI-app hosts: PostHog Code (via consumer) plus Claude Code and
        // Cowork (via the client-profile flag). All three surface structuredContent to
        // the model, so it must be dropped and the UI data re-homed onto _meta.
        it.each([
            ['posthog-code consumer', 'posthog-code', undefined],
            ['claude-code client', undefined, { isInlineExecUiHost: true }],
            ['cowork client', undefined, { isInlineExecUiHost: true }],
        ])(
            'suppresses structuredContent toward the model but re-homes UI data onto _meta for %s (with a formatted override)',
            async (_label, consumer, options) => {
                const tool = makeMockTool({
                    _meta: { ui: { resourceUri: 'ui://posthog/mock-app.html' } },
                    handler: async () => ({
                        results: [{ data: [1, 2, 3], count: 6 }],
                        _posthogUrl: 'http://localhost:8010/insights/new#q=...',
                        [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: 'Date|count\n2026-05-07|6',
                    }),
                })
                const exec = createExec([tool], consumer, options)
                const result = (await exec.handler(mockContext, { command: 'call mock-tool' })) as {
                    content: { type: string; text: string }[]
                    structuredContent?: Record<string, unknown>
                    _meta: { ui: { resourceUri: string }; [key: string]: unknown }
                }

                // Model sees ONLY the compact table, not the raw results JSON.
                expect(result.content[0]!.text).toBe('Date|count\n2026-05-07|6')
                // Top-level structuredContent is dropped so coding agents don't surface it.
                expect(result.structuredContent).toBeUndefined()
                // The UI app's data (with analytics) rides on _meta instead.
                const appData = result._meta[APP_DATA_META_KEY] as {
                    results: unknown
                    _analytics: { distinctId: string; toolName: string }
                }
                expect(appData.results).toEqual([{ data: [1, 2, 3], count: 6 }])
                expect(appData._analytics).toEqual({ distinctId: 'test-distinct-id', toolName: 'mock-tool' })
                expect(result._meta.ui.resourceUri).toBe('ui://posthog/mock-app.html')
            }
        )

        it('re-homes UI data onto _meta and gives the model TOON text even when there is no formatted override', async () => {
            const tool = makeMockTool({
                _meta: { ui: { resourceUri: 'ui://posthog/mock-app.html' } },
                handler: async () => ({
                    results: [{ data: [1, 2, 3], count: 6 }],
                    _posthogUrl: 'http://localhost:8010/insights/new#q=...',
                }),
            })
            const exec = createExec([tool], 'posthog-code')
            const result = (await exec.handler(mockContext, { command: 'call mock-tool' })) as {
                content: { type: string; text: string }[]
                structuredContent?: Record<string, unknown>
                _meta: { [key: string]: unknown }
            }

            // Without a compact table the model reads TOON text, never verbose structuredContent.
            expect(result.structuredContent).toBeUndefined()
            expect(result.content[0]!.text).toContain('_posthogUrl')
            const appData = result._meta[APP_DATA_META_KEY] as { results: unknown }
            expect(appData.results).toEqual([{ data: [1, 2, 3], count: 6 }])
        })

        // posthog_ai is sent as its own consumer for attribution but is NOT a UI-apps host.
        it.each([[undefined], ['cline'], ['claude-code'], ['slack'], ['posthog_code'], ['posthog_ai']])(
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
                [makeMockTool({ schema: z.object({ query: z.string() }) })],
                mockContext,
                'test description',
                'test command reference',
                undefined,
                tracker
            )
            await exec.handler(mockContext, { command: 'call --json mock-tool {"query":"SELECT 1"}' })
            expect(calls).toHaveLength(1)
            expect(calls[0]!.toolName).toBe('mock-tool')
            expect(calls[0]!.properties.success).toBe(true)
            expect(calls[0]!.properties.output_format).toBe('json')
            expect(typeof calls[0]!.properties.duration_ms).toBe('number')
            expect(calls[0]!.properties.input_tokens).toBeGreaterThan(0)
            expect(calls[0]!.properties.output_tokens).toBeGreaterThan(0)
            expect(calls[0]!.properties.input).toEqual({ query: 'SELECT 1' })
        })

        it('estimates inner output tokens from the serialized output (TOON vs JSON)', async () => {
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

            const toonOutput = await exec.handler(mockContext, { command: 'call mock-tool' })
            const jsonOutput = await exec.handler(mockContext, { command: 'call --json mock-tool' })

            // Each estimate matches the text actually returned, not a re-stringified object.
            expect(calls[0]!.properties.output_tokens).toBe(estimateTokens(toonOutput))
            expect(calls[1]!.properties.output_tokens).toBe(estimateTokens(jsonOutput))
            // TOON and JSON serialize to different sizes — the estimate tracks the wire format.
            expect(calls[0]!.properties.output_tokens).not.toBe(calls[1]!.properties.output_tokens)
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

        it.each([
            {
                case: 'a missing required parameter, naming the field',
                input: '{}',
                expected: /Invalid input for "action-get": missing required parameter: id/,
            },
            {
                case: 'a parameter of the wrong type, naming the expected type',
                input: '{"id":"not-a-number"}',
                expected: /parameter "id" must be of type number/,
            },
            {
                // Plain z.object strips unknown keys at parse time (Zod v4), so the
                // actionable signal is the absent required `id`, not the stray key.
                case: 'an unexpected property displacing the required field',
                input: '{"actionId":277664}',
                expected: /missing required parameter: id/,
            },
        ])('rejects a call with $case', async ({ input, expected }) => {
            const tool = makeMockTool({
                name: 'action-get',
                schema: z.object({ id: z.number() }),
                handler: async (_ctx, params) => params,
            })
            const exec = createExec([tool])
            const error: unknown = await exec.handler(mockContext, { command: `call action-get ${input}` }).then(
                () => null,
                (e: unknown) => e
            )
            // Typed rejection — the executor relies on it to skip exception
            // capture and classify the failure as `validation`.
            expect(error).toBeInstanceOf(ToolInputValidationError)
            expect((error as Error).message).toMatch(expected)
        })

        it('passes validated output — with defaults applied — to the inner handler', async () => {
            const tool = makeMockTool({
                schema: z.object({ id: z.number(), limit: z.number().default(10) }),
                handler: async (_ctx, params) => params,
            })
            const exec = createExec([tool])
            const result = await exec.handler(mockContext, { command: 'call --json mock-tool {"id":5}' })
            expect(JSON.parse(result as string)).toEqual({ id: 5, limit: 10 })
        })

        it('does not dispatch to the handler when validation fails', async () => {
            let called = false
            const tool = makeMockTool({
                name: 'action-get',
                schema: z.object({ id: z.number() }),
                handler: async () => {
                    called = true
                    return {}
                },
            })
            const exec = createExec([tool])
            await expect(exec.handler(mockContext, { command: 'call action-get {}' })).rejects.toThrow(
                /missing required parameter: id/
            )
            expect(called).toBe(false)
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
            // Token estimates are success-only — nothing useful to measure on a throw.
            expect(calls[0]!.properties.input_tokens).toBeUndefined()
            expect(calls[0]!.properties.output_tokens).toBeUndefined()
        })

        it('invokes the inner-call tracker with validation_error=true when input fails validation', async () => {
            const calls: { toolName: string; properties: ExecInnerCallProperties }[] = []
            const tracker = (toolName: string, properties: ExecInnerCallProperties): void => {
                calls.push({ toolName, properties })
            }
            const tool = makeMockTool({
                name: 'action-get',
                schema: z.object({ id: z.number() }),
                handler: async (_ctx, params) => params,
            })
            const exec = createExecTool(
                [tool],
                mockContext,
                'test description',
                'test command reference',
                undefined,
                tracker
            )
            await expect(exec.handler(mockContext, { command: 'call action-get {}' })).rejects.toThrow(
                /missing required parameter: id/
            )
            expect(calls).toHaveLength(1)
            expect(calls[0]!.toolName).toBe('action-get')
            expect(calls[0]!.properties.success).toBe(false)
            expect(calls[0]!.properties.validation_error).toBe(true)
            expect(calls[0]!.properties.duration_ms).toBe(0)
            expect(calls[0]!.properties.error_message).toMatch(/missing required parameter: id/)
        })
    })

    describe('output_format suppression', () => {
        // Mirrors the generated query wrappers / insight-query: `output_format`
        // toggles whether the handler surfaces the server-side formatted table.
        function makeFormatterTool(received: Record<string, unknown>[]): Tool<ZodObjectAny> {
            return makeMockTool({
                schema: z.object({
                    series: z.string().optional().describe('Query series'),
                    output_format: z.enum(['optimized', 'json']).default('optimized').optional(),
                }),
                handler: async (_ctx, params) => {
                    received.push(params as Record<string, unknown>)
                    const optimized = (params as { output_format?: string }).output_format !== 'json'
                    return {
                        results: [{ count: 6 }],
                        ...(optimized ? { [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: 'Date|count\n2026-05-07|6' } : {}),
                    }
                },
            })
        }

        it.each(['info mock-tool', 'schema mock-tool'])(
            'hides output_format from the schema rendered by "%s"',
            async (command) => {
                const exec = createExec([makeFormatterTool([])])
                const result = (await exec.handler(mockContext, { command })) as string
                expect(result).toContain('series')
                expect(result).not.toContain('output_format')
            }
        )

        it('returns raw JSON when output_format:"json" is passed in the call input', async () => {
            const exec = createExec([makeFormatterTool([])])
            const result = (await exec.handler(mockContext, {
                command: 'call mock-tool {"output_format":"json"}',
            })) as string
            const parsed = JSON.parse(result)
            expect(parsed.results).toEqual([{ count: 6 }])
            expect(parsed[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBeUndefined()
        })

        it('folds --json into the dispatched output_format so the handler skips the formatter', async () => {
            const received: Record<string, unknown>[] = []
            const exec = createExec([makeFormatterTool(received)])
            const result = (await exec.handler(mockContext, { command: 'call --json mock-tool' })) as string
            expect(received[0]!.output_format).toBe('json')
            expect(JSON.parse(result).results).toEqual([{ count: 6 }])
        })

        it('still dispatches the schema default "optimized" so the formatted table wins by default', async () => {
            const received: Record<string, unknown>[] = []
            const exec = createExec([makeFormatterTool(received)])
            const result = await exec.handler(mockContext, { command: 'call mock-tool' })
            expect(received[0]!.output_format).toBe('optimized')
            expect(result).toBe('Date|count\n2026-05-07|6')
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
                    POSTHOG_PUBLIC_URL: undefined,
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

        // Regression for the reported bug: `schema query-trends series` resolves to an
        // array-of-union node that overflows the inline budget. The summarizer used to
        // walk only `properties`, so it returned `{ type: 'array', properties: {} }` —
        // an empty schema that hid the EventsNode/ActionsNode/GroupNode variants and
        // forced callers onto the prose examples instead. The series item shapes must
        // now be visible in the summary.
        it('eval: query-trends series drill-down exposes the item variant shapes (not an empty array)', async () => {
            const context: Context = {
                api: {} as any,
                cache: {} as any,
                env: {
                    MCP_APPS_BASE_URL: undefined,
                    POSTHOG_ANALYTICS_API_KEY: undefined,
                    POSTHOG_ANALYTICS_HOST: undefined,
                    POSTHOG_API_BASE_URL: undefined,
                    POSTHOG_PUBLIC_URL: undefined,
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
            const exec = createExecTool(v2Tools, context, 'test', 'test', undefined)

            const drilled = JSON.parse(
                (await exec.handler(context, { command: 'schema query-trends series' })) as string
            ) as {
                field?: string
                schema?: {
                    type?: string
                    items?: { variants?: Array<{ properties?: Record<string, unknown> }> }
                }
            }

            expect(drilled.field).toBe('series')
            expect(drilled.schema?.type).toBe('array')
            // The historical bug returned `{ type: "array", properties: {} }` with no
            // `items` at all. The item schema — here a summarized union of variants —
            // must now be present, and the variants must carry real field names. The old
            // empty output exposes none of these keys, so this fails on a regression.
            const variants = drilled.schema?.items?.variants
            expect(variants?.length).toBeGreaterThan(0)
            const variantFields = variants!.flatMap((v) => Object.keys(v.properties ?? {}))
            expect(variantFields).toContain('kind')
            expect(variantFields).toContain('event')
        })
    })

    describe('search command', () => {
        it('returns a plain array of matching tool names', async () => {
            const flagTool = makeMockTool({ name: 'feature-flag-get-all', title: 'List feature flags' })
            const exec = createExec([flagTool])
            const result = await exec.handler(mockContext, { command: 'search feature-flag' })
            expect(JSON.parse(result as string)).toEqual(['feature-flag-get-all'])
        })

        it('rejects an overly long search pattern before compiling the regex', async () => {
            const exec = createExec([makeMockTool()])
            const longPattern = 'a'.repeat(401)
            await expect(exec.handler(mockContext, { command: `search ${longPattern}` })).rejects.toThrow(
                /pattern too long/i
            )
        })

        it('hints scope-gated tools that match but are hidden by missing scopes', async () => {
            const exec = createExecTool([makeMockTool()], mockContext, 'desc', 'cmd', undefined, undefined, [
                {
                    name: 'external-data-sources-refresh-schemas',
                    title: 'Refresh available schemas',
                    description: 'Fetch the latest table list from the remote database',
                    missingScopes: ['external_data_source:write'],
                },
                {
                    name: 'external-data-schemas-list',
                    title: 'List data import schemas',
                    description: 'List all table schemas',
                    missingScopes: ['external_data_source:read'],
                },
            ])
            const result = JSON.parse(
                (await exec.handler(mockContext, {
                    command: 'search external-data-sources|external-data-schemas',
                })) as string
            )
            expect(result.matches).toEqual([])
            expect(result.scope_gated_matches).toEqual([
                { name: 'external-data-sources-refresh-schemas', missing_scopes: ['external_data_source:write'] },
                { name: 'external-data-schemas-list', missing_scopes: ['external_data_source:read'] },
            ])
            expect(result.hint).toContain('external_data_source:read')
            expect(result.hint).toContain('external_data_source:write')
        })

        it('does not hint scope-gated tools that do not match the query', async () => {
            const flagTool = makeMockTool({ name: 'feature-flag-get-all', title: 'List feature flags' })
            const exec = createExecTool([flagTool], mockContext, 'desc', 'cmd', undefined, undefined, [
                {
                    name: 'external-data-schemas-list',
                    title: 'List data import schemas',
                    description: 'List all table schemas',
                    missingScopes: ['external_data_source:read'],
                },
            ])
            const result = await exec.handler(mockContext, { command: 'search feature-flag' })
            expect(JSON.parse(result as string)).toEqual(['feature-flag-get-all'])
        })

        it('ranks tools for a multi-word plain-language query that a single regex would miss', async () => {
            // /create dashboard insight/i matches no tool literally; routing to
            // ranked search is the whole point of this command.
            const tools = [
                makeMockTool({ name: 'dashboard-create', title: 'Create dashboard' }),
                makeMockTool({ name: 'insight-create', title: 'Create insight' }),
                makeMockTool({ name: 'feature-flag-get-all', title: 'List feature flags' }),
            ]
            const exec = createExec(tools)
            const result = JSON.parse(
                (await exec.handler(mockContext, { command: 'search create dashboard insight' })) as string
            )
            expect(Array.isArray(result)).toBe(true)
            expect(result.slice(0, 2)).toEqual(['dashboard-create', 'insight-create'])
        })

        it('surfaces scope-gated tools for a plain-language query', async () => {
            const exec = createExecTool([makeMockTool()], mockContext, 'desc', 'cmd', undefined, undefined, [
                {
                    name: 'experiment-create',
                    title: 'Create experiment',
                    description: 'Create a new experiment',
                    missingScopes: ['experiment:write'],
                },
            ])
            const result = JSON.parse(
                (await exec.handler(mockContext, { command: 'search create experiment' })) as string
            )
            expect(result.scope_gated_matches).toEqual([
                { name: 'experiment-create', missing_scopes: ['experiment:write'] },
            ])
            expect(result.hint).toContain('experiment:write')
        })

        it('caps ranked results and notes truncation', async () => {
            const tools = Array.from({ length: 30 }, (_, i) =>
                makeMockTool({ name: `dashboard-tool-${i}`, title: `Dashboard tool ${i}` })
            )
            const exec = createExec(tools)
            const result = JSON.parse((await exec.handler(mockContext, { command: 'search dashboard' })) as string)
            expect(result.truncated).toBe(true)
            expect(result.matches).toHaveLength(25)
            expect(result.hint).toContain('30')
        })

        it('reports an invalid regex gracefully', async () => {
            const exec = createExec([makeMockTool()])
            await expect(exec.handler(mockContext, { command: 'search [invalid' })).rejects.toThrow(
                /invalid regex pattern/i
            )
        })
    })

    describe('deprecated tool redirects', () => {
        it.each([
            ['read-data-warehouse-schema', 'execute-sql'],
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
            ['call --confirm my-tool {}', 'my-tool'],
            ['call --json --confirm my-tool {}', 'my-tool'],
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

    describe('exec tool description', () => {
        function createExecContext(): Context {
            return {
                api: {} as any,
                cache: {} as any,
                env: {
                    MCP_APPS_BASE_URL: undefined,
                    POSTHOG_ANALYTICS_API_KEY: undefined,
                    POSTHOG_ANALYTICS_HOST: undefined,
                    POSTHOG_API_BASE_URL: undefined,
                    POSTHOG_PUBLIC_URL: undefined,
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
            const context = createExecContext()
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

        // The `{tool_domains}` and `{query_tools}` placeholders in the exec
        // tool's `command` description are filled from the passed tool set. A
        // fixed fake set keeps this hermetic — adding or renaming a real tool
        // can't flip it.
        it('interpolates the tool-domain and query-tool blocks into the command description', () => {
            const toolInfos = [
                { name: 'experiment-create', category: 'Experiments' },
                { name: 'experiment-delete', category: 'Experiments' },
                { name: 'query-trends', category: 'Query' },
            ]
            const queryToolInfos = [{ name: 'query-trends', title: 'Trends', systemPromptHint: 'time series' }]

            const formatter = new InstructionsFormatter()
            const commandReference = formatter.buildExecCommandReference(
                { guidelines, tools: toolInfos, queryTools: queryToolInfos },
                { stripEnvContext: false }
            )
            const execTool = createExecTool(
                [],
                createExecContext(),
                formatter.buildExecToolDescription(),
                commandReference,
                undefined
            )
            const commandDescription = execTool.schema.shape.command.description ?? ''

            expect(commandDescription).not.toContain('{tool_domains}')
            expect(commandDescription).not.toContain('{query_tools}')

            // The command reference renders domains in the compact pipe form (size budget).
            const domainsBlock = buildToolDomainsCompact(toolInfos)
            const queryToolsBlock = buildQueryToolsBlock(queryToolInfos)
            expect(domainsBlock).toContain('experiment')
            expect(domainsBlock).toContain('query')
            expect(commandDescription).toContain(domainsBlock)
            expect(commandDescription).toContain(queryToolsBlock)
        })
    })
})
