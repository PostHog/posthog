import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { z } from 'zod'

import { MemoryPlanStore } from '@/lib/code-exec'
import { checkScript } from '@/tools/code-exec/compile-gate'
import { type DiscoveryIndex, TYPES_CHAR_LIMIT } from '@/tools/code-exec/discovery'
import { LocalVmExecutor, type SandboxExecutor, SandboxUnavailableError } from '@/tools/code-exec/executor'
import {
    createCodeExecutionDiscovery,
    createCodeExecutionRuntime,
    type CodeExecutionRuntime,
    type InnerToolDispatcher,
} from '@/tools/code-exec/runtime'
import {
    createExecTool,
    dispatchInnerTool,
    type ExecInnerCallProperties,
    type ExecSchema,
    type ExecVerbMetaUpdate,
} from '@/tools/exec'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

import { FIXTURE_TABLE, stubFetch } from './fixtures'

const FIXED_NOW = 1_700_000_000_000

const mockContext = {
    getDistinctId: async () => 'test-distinct-id',
} as unknown as Context

const DISCOVERY_FIXTURE: DiscoveryIndex = {
    version: 1,
    methods: [
        {
            id: 'annotations.create',
            toolName: 'annotation-create',
            signature: 'annotations.create(params: AnnotationsCreateParams): Promise<Annotation>',
            title: 'Create an annotation',
            description: 'Create an annotation in the current project.',
            category: 'Annotations',
            scopes: ['annotation:write'],
            referencedTypes: ['AnnotationsCreateParams'],
        },
        {
            id: 'featureFlags.update',
            toolName: 'feature-flag-update',
            signature: 'featureFlags.update(params: FeatureFlagsUpdateParams): Promise<FeatureFlag>',
            title: 'Update a feature flag',
            description: 'Update a feature flag by id.',
            category: 'Feature flags',
            scopes: ['feature_flag:write'],
            referencedTypes: ['FeatureFlagsUpdateParams', 'FeatureFlag'],
        },
        {
            id: 'featureFlags.list',
            toolName: 'feature-flag-get-all',
            signature: 'featureFlags.list(params?: FeatureFlagsListParams): Promise<PaginatedFeatureFlagList>',
            title: 'List feature flags',
            description: 'List feature flags in the current project.',
            category: 'Feature flags',
            scopes: ['feature_flag:read'],
            referencedTypes: [],
        },
        {
            id: 'dashboards.delete',
            toolName: 'dashboard-delete',
            signature: 'dashboards.delete(params: DashboardsDeleteParams): Promise<void>',
            title: 'Delete a dashboard',
            description: 'Hard-delete a dashboard.',
            category: 'Dashboards',
            scopes: ['dashboard:write'],
            referencedTypes: [],
        },
        {
            id: 'query.trends',
            toolName: 'query-trends',
            signature: 'query.trends(params: TrendsQueryParams): Promise<unknown>',
            title: 'Run a trends query',
            description: 'Run a trends query.',
            category: 'Query',
            scopes: ['query:read'],
            referencedTypes: [],
        },
    ],
    types: [
        {
            name: 'AnnotationsCreateParams',
            declaration: 'export interface AnnotationsCreateParams { content: string }',
            referencedTypes: [],
            tokens: 15,
        },
        {
            name: 'FeatureFlag',
            declaration: 'export interface FeatureFlag { id: number; key: string }',
            referencedTypes: [],
            tokens: 14,
        },
        {
            name: 'FeatureFlagsUpdateParams',
            declaration: 'export interface FeatureFlagsUpdateParams { id: number; active?: boolean }',
            referencedTypes: ['FeatureFlag'],
            tokens: 19,
        },
        {
            name: 'GiantUnion',
            declaration: `export type GiantUnion = ${'x'.repeat(TYPES_CHAR_LIMIT + 1_000)}`,
            referencedTypes: ['FeatureFlag'],
            tokens: Math.ceil((TYPES_CHAR_LIMIT + 1_000) / 4),
        },
    ],
}

interface Harness {
    exec: Tool<ExecSchema>
    runtime: CodeExecutionRuntime
    responses: Record<string, { status?: number; body: unknown }>
    calls: Array<{ method: string; url: string; body: unknown }>
    clock: { nowMs: number }
    /** Active session project (the tool handlers' source of truth); mutate to simulate switch-project. */
    session: { projectId: string }
    /** Inner tool handler invocations (fast-path dispatches land here). */
    handlerCalls: Array<{ tool: string; params: Record<string, unknown> }>
    trackerCalls: Array<{ toolName: string; properties: ExecInnerCallProperties }>
    /** Verb-dimension analytics updates (spec §4.6 Phase 0). */
    verbUpdates: ExecVerbMetaUpdate[]
}

/** Stub inner tools matching the discovery fixture's `toolName`s. */
function makeInnerTools(handlerCalls: Harness['handlerCalls']): Tool<ZodObjectAny>[] {
    const annotations = { destructiveHint: false, idempotentHint: true, openWorldHint: false, readOnlyHint: true }
    const record =
        (name: string, result: unknown) =>
        async (_ctx: Context, params: unknown): Promise<unknown> => {
            handlerCalls.push({ tool: name, params: params as Record<string, unknown> })
            return result
        }
    return [
        {
            name: 'feature-flag-get-all',
            title: 'List feature flags',
            description: 'List feature flags.',
            schema: z.object({ limit: z.number().optional() }),
            scopes: [],
            annotations,
            handler: record('feature-flag-get-all', { results: [{ id: 1, key: 'alpha', active: true }] }),
        },
        {
            name: 'feature-flag-update',
            title: 'Update a feature flag',
            description: 'Update a feature flag.',
            schema: z.object({ id: z.number(), active: z.boolean().optional(), deleted: z.boolean().optional() }),
            scopes: [],
            annotations,
            handler: record('feature-flag-update', { id: 1, key: 'alpha', active: false }),
        },
        {
            name: 'dashboard-delete',
            title: 'Delete a dashboard',
            description: 'Delete a dashboard.',
            schema: z.object({ id: z.number() }),
            scopes: [],
            annotations,
            handler: record('dashboard-delete', { deleted: true }),
        },
        {
            name: 'query-trends',
            title: 'Run a trends query',
            description: 'Run a trends query.',
            schema: z.object({ interval: z.string().optional() }),
            scopes: [],
            annotations,
            handler: record('query-trends', { results: [] }),
        },
        {
            // No discovery-index mapping — stands in for SSE-backed tools with
            // no SDK counterpart (the honest exception, spec §4.3).
            name: 'session-summarize',
            title: 'Summarize sessions',
            description: 'Summarize session recordings.',
            schema: z.object({}),
            scopes: [],
            annotations,
            handler: record('session-summarize', { summary: 'ok' }),
        },
    ]
}

function makeHarness(
    options: {
        sessionScopes?: string[]
        withCompileGate?: boolean
        executor?: SandboxExecutor
        withInnerTools?: boolean
        codeFirst?: boolean
        /** false mimics a discovery-only session (e.g. the keyless CLI catalog): run/apply unwired. */
        withRuntime?: boolean
        /** false mimics a fast-path-only server (spec §4.2): runtime wired, no sandbox executor. */
        withExecutor?: boolean
    } = {}
): Harness {
    const clock = { nowMs: FIXED_NOW }
    const session = { projectId: '2' }
    const responses: Record<string, { status?: number; body: unknown }> = {
        'GET /api/users/@me/': { body: { team: { id: 2 }, organization: { id: 'org-1' } } },
        'GET /api/projects/2/feature_flags/': {
            body: { count: 1, next: null, previous: null, results: [{ id: 1, key: 'alpha', active: true }] },
        },
        'PATCH /api/projects/2/feature_flags/1/': { body: { id: 1, key: 'alpha', active: false } },
    }
    const stub = stubFetch(responses)

    const handlerCalls: Harness['handlerCalls'] = []
    const trackerCalls: Harness['trackerCalls'] = []
    const trackInnerCall = (toolName: string, properties: ExecInnerCallProperties): void => {
        trackerCalls.push({ toolName, properties })
    }
    const innerTools = options.withInnerTools ? makeInnerTools(handlerCalls) : []
    // Mirrors the tool-executor wiring: canDispatch pre-checks so a fast-path
    // miss falls through, dispatch runs the shared `call` pipeline.
    const toolDispatcher: InnerToolDispatcher | undefined = options.withInnerTools
        ? {
              canDispatch: (toolName, input) => {
                  const tool = innerTools.find((t) => t.name === toolName)
                  return tool !== undefined && tool.schema.safeParse(input).success
              },
              dispatch: async (toolName, input, opts) =>
                  dispatchInnerTool({
                      tool: innerTools.find((t) => t.name === toolName)!,
                      context: mockContext,
                      input,
                      mcpConsumer: undefined,
                      isInlineExecUiHost: false,
                      trackInnerCall,
                      suppressUiPayload: opts?.suppressUiPayload,
                  }),
          }
        : undefined

    const discovery = createCodeExecutionDiscovery({
        sessionScopes: options.sessionScopes ?? ['feature_flag:write'],
        discoveryIndex: DISCOVERY_FIXTURE,
    })
    const runtime = createCodeExecutionRuntime({
        realFetch: stub.fetch,
        getSub: async () => 'test-distinct-id',
        getProjectId: async () => session.projectId,
        getOrgId: async () => 'org-1',
        planStore: new MemoryPlanStore({ now: () => clock.nowMs }),
        ...(options.withExecutor === false ? {} : { executor: options.executor ?? new LocalVmExecutor() }),
        classifierTable: FIXTURE_TABLE,
        compileGate: options.withCompileGate === false ? undefined : { check: checkScript },
        toolDispatcher,
        discoveryIndex: DISCOVERY_FIXTURE,
    })
    const verbUpdates: ExecVerbMetaUpdate[] = []
    const exec = createExecTool(innerTools, mockContext, 'desc', 'cmd', undefined, trackInnerCall, [], {
        codeExecutionDiscovery: discovery,
        ...(options.withRuntime === false ? {} : { codeExecutionRuntime: runtime }),
        ...(options.codeFirst !== undefined ? { codeFirst: options.codeFirst } : {}),
        trackVerb: (update) => verbUpdates.push(update),
    })
    return { exec, runtime, responses, calls: stub.calls, clock, session, handlerCalls, trackerCalls, verbUpdates }
}

const READ_ONLY_SCRIPT = [
    "import { client } from '@posthog/sdk'",
    'const flags = await client.featureFlags.list()',
    "console.log('flag count', flags.results.length)",
    'export default { keys: flags.results.map((flag) => flag.key) }',
].join('\n')

const MUTATING_SCRIPT = [
    "import { client } from '@posthog/sdk'",
    'const flags = await client.featureFlags.list()',
    'for (const flag of flags.results) {',
    '    await client.featureFlags.update({ id: flag.id, active: false })',
    '}',
    'export default { updated: flags.results.map((flag) => flag.key) }',
].join('\n')

const FAST_READ_SCRIPT = [
    "import { client } from '@posthog/sdk'",
    'export default await client.featureFlags.list({ limit: 2 })',
].join('\n')

const FAST_UPDATE_SCRIPT = [
    "import { client } from '@posthog/sdk'",
    'export default await client.featureFlags.update({ id: 1, active: false })',
].join('\n')

async function runCommand(harness: Harness, command: string): Promise<string> {
    return (await harness.exec.handler(mockContext, { command })) as string
}

function extractPlanId(planText: string): string {
    const match = /\napply (\S+)/.exec(planText)
    expect(match).not.toBeNull()
    // A plan id is a filename-safe dash-joined three-word phrase.
    expect(match![1]).toMatch(/^[a-z]+(-[a-z]+){2}$/)
    return match![1]!
}

describe('exec code-execution verbs', () => {
    // The first compile-gate call builds a TS language service over the full
    // SDK declarations — warm it once so individual tests stay within budget.
    beforeAll(async () => {
        await checkScript('export default 1')
    }, 120_000)

    describe('verb gating', () => {
        it.each([['types query'], ['run export default 1'], ['apply token'], ['nonsense']])(
            'without a runtime, %s stays an unknown command that does not mention the new verbs',
            async (command) => {
                const exec = createExecTool([], mockContext, 'desc', 'cmd', undefined)
                const error: unknown = await exec.handler(mockContext, { command }).then(
                    () => null,
                    (e: unknown) => e
                )
                expect((error as Error).message).toBe(
                    `Unknown command: "${command.split(' ')[0]}". Supported commands: tools, search, info, schema, call`
                )
            }
        )

        it('with a runtime, the unknown-command error advertises types, run, apply, and sql', async () => {
            const harness = makeHarness()
            await expect(runCommand(harness, 'nonsense')).rejects.toThrow(
                'Unknown command: "nonsense". Supported commands: tools, search, info, schema, call, types, run, apply, sql'
            )
        })

        describe('with discovery but no executor-backed runtime (spec §4.4)', () => {
            it.each([['run export default 1'], ['apply some-plan-id']])(
                '"%s" reads as unknown, with a roster advertising only the discovery subset',
                async (command) => {
                    const harness = makeHarness({ withRuntime: false })
                    await expect(runCommand(harness, command)).rejects.toThrow(
                        `Unknown command: "${command.split(' ')[0]}". Supported commands: tools, search, info, schema, call, types, sql`
                    )
                }
            )

            it('types still serves declarations from the static index', async () => {
                const harness = makeHarness({ withRuntime: false })
                const result = await runCommand(harness, 'types FeatureFlag')
                expect(result).toContain('export interface FeatureFlag { id: number; key: string }')
            })
        })
    })

    describe('types', () => {
        it('annotates signatures with the session scope standing', async () => {
            const harness = makeHarness({ sessionScopes: ['feature_flag:write'] })
            const result = await runCommand(harness, 'types .')
            expect(result).toContain('featureFlags.update(params: FeatureFlagsUpdateParams): Promise<FeatureFlag>')
            expect(result).toContain('[requires feature_flag:write ✓]')
            expect(result).toContain('[requires annotation:write — missing on this token]')
        })

        it('search resolves legacy MCP tool names to their SDK methods (spec §4.3)', async () => {
            const harness = makeHarness()
            const result = await runCommand(harness, 'types feature-flag-update')
            // Matches only via the method's `toolName` — no other indexed field
            // carries the legacy name.
            expect(result).toContain('featureFlags.update(params: FeatureFlagsUpdateParams): Promise<FeatureFlag>')
            expect(result).not.toContain('No SDK methods or types matched')
        })

        it('falls back to substring matching when the pattern is not a valid regex', async () => {
            const harness = makeHarness()
            // Unbalanced paren: invalid regex, but a literal substring of the signature.
            const result = await runCommand(harness, 'types update(')
            expect(result).toContain('featureFlags.update')
            expect(result).not.toContain('annotations.create')
        })

        it.each([
            {
                case: 'an exact type name returns only its declaration, references as a fetch hint',
                command: 'types FeatureFlagsUpdateParams',
                contains: [
                    'export interface FeatureFlagsUpdateParams { id: number; active?: boolean }',
                    'References — run "types FeatureFlag" for declarations',
                ],
                notContains: ['export interface FeatureFlag {'],
            },
            {
                case: 'several exact names return each declaration',
                command: 'types FeatureFlagsUpdateParams, FeatureFlag',
                contains: [
                    'export interface FeatureFlagsUpdateParams { id: number; active?: boolean }',
                    'export interface FeatureFlag { id: number; key: string }',
                ],
                notContains: [],
            },
            {
                case: 'an exact method id returns signature, description, and references',
                command: 'types featureFlags.update',
                contains: [
                    'featureFlags.update(params: FeatureFlagsUpdateParams): Promise<FeatureFlag>',
                    'Update a feature flag by id.',
                    'References — run "types FeatureFlagsUpdateParams FeatureFlag" for declarations',
                ],
                notContains: ['export interface FeatureFlagsUpdateParams {'],
            },
            {
                case: 'a bare domain lists method signatures without type bodies',
                command: 'types featureFlags',
                contains: ['featureFlags.update(params: FeatureFlagsUpdateParams): Promise<FeatureFlag>'],
                notContains: ['export interface FeatureFlagsUpdateParams {'],
            },
            {
                case: 'the retired "show" prefix still works as an alias',
                command: 'types show FeatureFlag',
                contains: ['export interface FeatureFlag { id: number; key: string }'],
                notContains: [],
            },
        ])('fetch mode: $case', async ({ command, contains, notContains }) => {
            const harness = makeHarness()
            const result = await runCommand(harness, command)
            for (const expected of contains) {
                expect(result).toContain(expected)
            }
            for (const unexpected of notContains) {
                expect(result).not.toContain(unexpected)
            }
        })

        it('an input with any non-exact token falls through to search as a whole', async () => {
            const harness = makeHarness()
            const result = await runCommand(harness, 'types NoSuchThing FeatureFlag')
            expect(result).toContain('No SDK methods or types matched')
        })

        it('search results list matching type names for exact follow-up fetches', async () => {
            const harness = makeHarness()
            const result = await runCommand(harness, 'types Params')
            expect(result).toContain('Types:')
            expect(result).toContain('AnnotationsCreateParams')
        })

        it('hard-truncates an oversized declaration at the char cap, pointing at its referenced types', async () => {
            const harness = makeHarness()
            const result = await runCommand(harness, 'types GiantUnion')
            expect(result.length).toBeLessThanOrEqual(TYPES_CHAR_LIMIT + 200)
            expect(result).toContain(
                `…[declaration truncated at ${TYPES_CHAR_LIMIT} chars — fetch its parts via the referenced types: FeatureFlag]`
            )
        })

        it('omits declarations that exceed the cap, naming them in the hint', async () => {
            const harness = makeHarness()
            const result = await runCommand(harness, 'types FeatureFlag GiantUnion')
            expect(result).toContain('export interface FeatureFlag { id: number; key: string }')
            expect(result).not.toContain('xxxx')
            expect(result).toContain(
                `Omitted (${TYPES_CHAR_LIMIT} char cap): GiantUnion — request them in a separate "types" call.`
            )
        })
    })

    describe('compile gate', () => {
        it.each([
            {
                case: 'a type error, anchored to its line and column',
                script: "const x: number = 'nope'\nexport default x",
                messagePart: "'string'",
                line: 1,
            },
            {
                case: 'a missing export default',
                script: 'const answer = 42',
                messagePart: 'export default',
                line: 1,
            },
            {
                case: 'a require() call',
                script: "const fs = require('node:fs')\nexport default fs",
                messagePart: 'require() is not available',
                line: 1,
            },
        ])('rejects a script with $case before any execution', async ({ script, messagePart, line }) => {
            const harness = makeHarness()
            const result = JSON.parse(await runCommand(harness, `run ${script}`)) as {
                status: string
                diagnostics: Array<{ line: number; character: number; message: string; code: number }>
            }
            expect(result.status).toBe('compile_error')
            const diagnostic = result.diagnostics.find((d) => d.message.includes(messagePart))
            expect(diagnostic).not.toBeUndefined()
            expect(diagnostic!.line).toBe(line)
            expect(diagnostic!.character).toBeGreaterThan(0)
            // Nothing may reach the transport when the gate rejects.
            expect(harness.calls).toHaveLength(0)
        })
    })

    describe('without a compile gate (the CLI bundle never injects one)', () => {
        it.each([
            {
                case: 'a missing export default',
                script: 'const answer = 42',
                messagePart: 'export default',
            },
            {
                case: 'a require() call',
                script: "const fs = require('node:fs')\nexport default fs",
                messagePart: 'require() is not available',
            },
        ])('the contract lints still reject $case before any execution', async ({ script, messagePart }) => {
            const harness = makeHarness({ withCompileGate: false })
            const result = JSON.parse(await runCommand(harness, `run ${script}`)) as {
                status: string
                diagnostics: Array<{ message: string }>
            }
            expect(result.status).toBe('compile_error')
            expect(result.diagnostics.some((d) => d.message.includes(messagePart))).toBe(true)
            expect(harness.calls).toHaveLength(0)
        })

        it('executes a lint-clean script, noting that the typecheck was skipped', async () => {
            const harness = makeHarness({ withCompileGate: false })
            const result = await runCommand(harness, `run ${READ_ONLY_SCRIPT}`)
            expect(result).toContain('"alpha"')
            expect(result).toContain('typecheck was skipped')
        })
    })

    describe('executor trusted-local gating', () => {
        const ORIG_NODE_ENV = process.env.NODE_ENV

        afterEach(() => {
            process.env.NODE_ENV = ORIG_NODE_ENV
        })

        it('fails closed outside development/test unless trustedLocal is set', () => {
            process.env.NODE_ENV = 'production'
            expect(() => new LocalVmExecutor()).toThrow(SandboxUnavailableError)
            expect(() => new LocalVmExecutor({ trustedLocal: true })).not.toThrow()
        })
    })

    describe('run (read-only)', () => {
        it('executes directly, returning output and console with no plan id', async () => {
            const harness = makeHarness()
            const result = await runCommand(harness, `run ${READ_ONLY_SCRIPT}`)
            expect(result).toContain('"keys"')
            expect(result).toContain('"alpha"')
            expect(result).toContain('[log] flag count 1')
            expect(result).not.toContain('apply ')
            // Reads passed through; no mutation was ever sent.
            expect(harness.calls.map((c) => c.method)).not.toContain('PATCH')
        })

        it.each([
            { case: 'a plain value', script: 'export default 41 + 1' },
            { case: 'a promise', script: 'export default Promise.resolve(42)' },
            { case: 'a function', script: 'export default () => 42' },
        ])('resolves an export default that is $case', async ({ script }) => {
            const harness = makeHarness()
            const result = await runCommand(harness, `run ${script}`)
            expect(result).toContain('42')
        })

        it('reports a thrown script error without issuing a plan id', async () => {
            const harness = makeHarness()
            const script = "throw new Error('boom')\nexport default 1"
            const result = await runCommand(harness, `run ${script}`)
            expect(result).toContain('Script failed: boom')
            expect(result).not.toContain('apply ')
        })
    })

    describe('fast path (call-shaped scripts)', () => {
        const throwingExecutor: SandboxExecutor = {
            execute: async () => {
                throw new Error('the sandbox must not run for a call-shaped script')
            },
        }

        it('dispatches a read-only call-shaped script through the tool handler, byte-identical to `call`', async () => {
            const viaRun = makeHarness({ withInnerTools: true, executor: throwingExecutor })
            const viaCall = makeHarness({ withInnerTools: true, executor: throwingExecutor })

            const runResult = await runCommand(viaRun, `run ${FAST_READ_SCRIPT}`)
            const callResult = await runCommand(viaCall, 'call feature-flag-get-all {"limit":2}')

            expect(runResult).toBe(callResult)
            expect(viaRun.handlerCalls).toEqual(viaCall.handlerCalls)
            // Same inner-tool analytics attribution as `call`.
            expect(viaRun.trackerCalls).toHaveLength(1)
            expect(viaRun.trackerCalls[0]!.toolName).toBe('feature-flag-get-all')
            expect(viaRun.trackerCalls[0]!.properties.input).toEqual(viaCall.trackerCalls[0]!.properties.input)
            expect(viaRun.trackerCalls[0]!.properties.output_format).toBe(
                viaCall.trackerCalls[0]!.properties.output_format
            )
        })

        it('issues a degenerate plan for a mutating call-shaped script; apply replays it through the handler once', async () => {
            const harness = makeHarness({ withInnerTools: true, executor: throwingExecutor })

            const planText = await runCommand(harness, `run ${FAST_UPDATE_SCRIPT}`)
            expect(planText).toContain('Nothing has been applied yet')
            expect(planText).toContain('UPDATE feature flag — Update a feature flag (featureFlags.update)')
            expect(planText).toContain('"active": false')
            // The user must see which project they are confirming changes to.
            expect(planText).toContain('Plan created against project 2')
            // Degenerate plans carry no synthetic responses (spec §4.2).
            expect(planText).not.toContain('Provisional output')
            expect(harness.handlerCalls).toHaveLength(0)

            const planId = extractPlanId(planText)
            const receipt = await runCommand(harness, `apply ${planId}`)
            expect(receipt).toContain('Applied.')
            expect(receipt).toContain('[applied] PATCH /api/projects/2/feature_flags/1/')
            expect(harness.handlerCalls).toEqual([{ tool: 'feature-flag-update', params: { id: 1, active: false } }])

            const second = await runCommand(harness, `apply ${planId}`)
            expect(second).toContain('already been applied')
            expect(harness.handlerCalls).toHaveLength(1)
        })

        it.each([
            {
                case: 'a soft delete renders as DELETE',
                script: 'export default await client.featureFlags.update({ id: 1, deleted: true })',
                contains: ['DELETE feature flag — Update a feature flag'],
                notContains: ['!! DESTRUCTIVE'],
            },
            {
                case: 'a destructive hard delete carries the loud marker',
                script: 'export default await client.dashboards.delete({ id: 7 })',
                contains: ['DELETE dashboard — Delete a dashboard (dashboards.delete)', '!! DESTRUCTIVE'],
                notContains: [],
            },
        ])('degenerate plan rendering: $case', async ({ script, contains, notContains }) => {
            const harness = makeHarness({ withInnerTools: true, executor: throwingExecutor })
            const planText = await runCommand(harness, `run import { client } from '@posthog/sdk'\n${script}`)
            for (const expected of contains) {
                expect(planText).toContain(expected)
            }
            for (const unexpected of notContains) {
                expect(planText).not.toContain(unexpected)
            }
            expect(harness.handlerCalls).toHaveLength(0)
        })

        it('treats a query.* wrapper missing from the classifier table as a read', async () => {
            const harness = makeHarness({ withInnerTools: true, executor: throwingExecutor })
            const result = await runCommand(
                harness,
                `run import { client } from '@posthog/sdk'\nexport default await client.query.trends({ interval: 'day' })`
            )
            // Dispatched directly — no plan id issued, no sandbox.
            expect(harness.handlerCalls).toEqual([{ tool: 'query-trends', params: { interval: 'day' } }])
            expect(result).not.toContain('apply ')
        })

        // Matcher-rejection shapes are pinned unit-level in fast-path.test.ts;
        // one representative row proves the runtime wiring (matcher null →
        // executor). The other rows exercise misses past the matcher.
        it.each([
            {
                case: 'a matcher miss (identifier argument)',
                script: 'export default await client.featureFlags.update({ id: flagId })',
            },
            {
                case: 'a method without a discovery entry',
                script: 'export default await client.nonexistent.method({ id: 1 })',
            },
            {
                case: 'input that fails the tool schema',
                script: "export default await client.featureFlags.update({ id: 'one' })",
            },
        ])('falls through to the sandbox for $case', async ({ script }) => {
            const executed: string[] = []
            const recordingExecutor: SandboxExecutor = {
                execute: async (request) => {
                    executed.push(request.source)
                    return { output: null, consoleOutput: [] }
                },
            }
            const harness = makeHarness({
                withInnerTools: true,
                executor: recordingExecutor,
                withCompileGate: false,
            })
            await runCommand(harness, `run import { client } from '@posthog/sdk'\n${script}`)
            // The script reached the executor and never dispatched a tool handler.
            expect(executed).toHaveLength(1)
            expect(harness.handlerCalls).toHaveLength(0)
        })
    })

    describe('without a sandbox executor (fast-path-only server, spec §4.2)', () => {
        it('serves a call-shaped read through the fast path', async () => {
            const harness = makeHarness({ withInnerTools: true, withExecutor: false })
            const result = await runCommand(harness, `run ${FAST_READ_SCRIPT}`)
            expect(harness.handlerCalls).toEqual([{ tool: 'feature-flag-get-all', params: { limit: 2 } }])
            expect(result).toContain('alpha')
        })

        it('plans and applies a call-shaped mutation end to end', async () => {
            const harness = makeHarness({ withInnerTools: true, withExecutor: false })
            const planId = extractPlanId(await runCommand(harness, `run ${FAST_UPDATE_SCRIPT}`))
            const receipt = await runCommand(harness, `apply ${planId}`)
            expect(receipt).toContain('Applied.')
            expect(harness.handlerCalls).toEqual([{ tool: 'feature-flag-update', params: { id: 1, active: false } }])
        })

        it.each([
            {
                case: 'answers a sandbox-requiring script with a targeted redirect',
                script: MUTATING_SCRIPT,
                status: 'sandbox_unavailable',
                messagePart: 'single-call scripts',
            },
            // The compile gate still runs first: a broken script gets its type
            // error, not a misleading "needs the sandbox".
            {
                case: 'reports a compile error before the sandbox check',
                script: 'const x = 1',
                status: 'compile_error',
                messagePart: 'export default',
            },
        ])('$case', async ({ script, status, messagePart }) => {
            const harness = makeHarness({ withInnerTools: true, withExecutor: false })
            const outcome = await harness.runtime.run(script)
            expect(outcome.output).toContain(messagePart)
            expect(outcome.meta.status).toBe(status)
            expect(harness.calls).toHaveLength(0)
        })
    })

    describe('session project scoping (the two execution stacks must agree)', () => {
        it('sandboxed scripts resolve the session project, never the @me current team', async () => {
            const harness = makeHarness()
            harness.session.projectId = '3'
            harness.responses['GET /api/projects/3/feature_flags/'] = {
                body: { count: 1, next: null, previous: null, results: [{ id: 7, key: 'gamma', active: true }] },
            }
            const result = await runCommand(harness, `run ${READ_ONLY_SCRIPT}`)
            expect(result).toContain('gamma')
            // The @me fallback (whose current team is project 2) must never be consulted.
            expect(harness.calls.some((call) => call.url.includes('/api/users/@me'))).toBe(false)
        })

        it.each([
            { kind: 'a fast-path call plan', options: { withInnerTools: true }, script: FAST_UPDATE_SCRIPT },
            { kind: 'a script plan', options: {}, script: MUTATING_SCRIPT },
        ] as const)(
            'apply refuses $kind when the active project changed since the plan',
            async ({ options, script }) => {
                const harness = makeHarness(options)
                const planId = extractPlanId(await runCommand(harness, `run ${script}`))
                harness.session.projectId = '3'
                const outcome = await harness.runtime.apply(planId)
                expect(outcome.output).toContain(
                    'The active project changed since this plan was created (project 2 → 3)'
                )
                expect(outcome.meta.status).toBe('diverged')
                // Neither dispatch stack may have executed the mutation.
                expect(harness.handlerCalls).toHaveLength(0)
                expect(harness.calls.filter((call) => call.method === 'PATCH')).toHaveLength(0)
            }
        )
    })

    describe('run + apply (mutating)', () => {
        it('returns a plan with provisional output, then apply forwards the mutations and reports a receipt', async () => {
            const harness = makeHarness()

            const planText = await runCommand(harness, `run ${MUTATING_SCRIPT}`)
            expect(planText).toContain('Nothing has been applied yet')
            expect(planText).toContain('UPDATE feature flag')
            expect(planText).toContain('Provisional output')
            expect(planText).toContain('"alpha"')
            // The plan pass must not forward the mutation.
            expect(harness.calls.filter((c) => c.method === 'PATCH')).toHaveLength(0)

            const planId = extractPlanId(planText)
            const receipt = await runCommand(harness, `apply ${planId}`)
            expect(receipt).toContain('Applied.')
            expect(receipt).toContain('[applied] PATCH /api/projects/2/feature_flags/1/')
            const patches = harness.calls.filter((c) => c.method === 'PATCH')
            expect(patches).toHaveLength(1)
            expect(patches[0]!.body).toEqual({ active: false })
        })

        it('rejects a reused plan id — a plan id is single-use', async () => {
            const harness = makeHarness()
            const planId = extractPlanId(await runCommand(harness, `run ${MUTATING_SCRIPT}`))
            await runCommand(harness, `apply ${planId}`)
            const second = await runCommand(harness, `apply ${planId}`)
            expect(second).toContain('already been applied')
            // Only the first apply reached the API.
            expect(harness.calls.filter((c) => c.method === 'PATCH')).toHaveLength(1)
        })

        it('refuses an expired plan id and instructs a re-plan instead of auto-applying', async () => {
            const harness = makeHarness()
            const planId = extractPlanId(await runCommand(harness, `run ${MUTATING_SCRIPT}`))
            harness.clock.nowMs += 601_000
            const result = await runCommand(harness, `apply ${planId}`)
            expect(result).toContain('Plan not found')
            expect(result).toContain('Re-run the script')
            expect(harness.calls.filter((c) => c.method === 'PATCH')).toHaveLength(0)
        })

        it('rejects a mistyped plan id without applying anything', async () => {
            const harness = makeHarness()
            await runCommand(harness, `run ${MUTATING_SCRIPT}`)
            const result = await runCommand(harness, 'apply not-a-real-token')
            expect(result).toContain('Plan not found')
            expect(harness.calls.filter((c) => c.method === 'PATCH')).toHaveLength(0)
        })

        it('aborts with a divergence message when the world changed between plan and apply', async () => {
            const harness = makeHarness()
            const planId = extractPlanId(await runCommand(harness, `run ${MUTATING_SCRIPT}`))

            // Another actor replaced the flag: the list now returns a different
            // target, so the re-run script mutates an id that is not in the plan.
            harness.responses['GET /api/projects/2/feature_flags/'] = {
                body: { count: 1, next: null, previous: null, results: [{ id: 9, key: 'beta', active: true }] },
            }

            const result = await runCommand(harness, `apply ${planId}`)
            expect(result).toContain('The world changed since you confirmed')
            expect(result).toContain('PATCH /api/projects/2/feature_flags/9/')
            expect(result).toContain('[skipped]')
            expect(harness.calls.filter((c) => c.method === 'PATCH')).toHaveLength(0)
        })
    })

    describe('verb analytics metadata (spec §4.6 Phase 0)', () => {
        // The rendered text and the structured meta are separate surfaces: a
        // branch can keep its message while returning the wrong status, and
        // every text-asserting test above stays green — these lock the mapping.
        it.each([
            { case: 'a compile error', script: 'const x = 1', meta: { fastPath: false, status: 'compile_error' } },
            { case: 'a read-only script', script: READ_ONLY_SCRIPT, meta: { fastPath: false, status: 'read_only' } },
            {
                case: 'a script failure',
                script: "throw new Error('boom')\nexport default 1",
                meta: { fastPath: false, status: 'failed' },
            },
            {
                case: 'an issued plan',
                script: MUTATING_SCRIPT,
                // `planId` rides on the meta (never on analytics) so the CLI's
                // `--yes` can apply without scraping the rendered text.
                meta: {
                    fastPath: false,
                    status: 'plan_issued',
                    planMutations: 1,
                    planId: expect.stringMatching(/^[a-z]+(-[a-z]+){2}$/) as unknown as string,
                },
            },
        ])('run reports $case structurally', async ({ script, meta }) => {
            const harness = makeHarness()
            const outcome = await harness.runtime.run(script)
            expect(outcome.meta).toEqual(meta)
        })

        it.each([
            {
                case: 'read dispatch',
                script: FAST_READ_SCRIPT,
                meta: { fastPath: true, innerToolName: 'feature-flag-get-all', status: 'read_only' },
            },
            {
                case: 'mutation plan',
                script: FAST_UPDATE_SCRIPT,
                meta: {
                    fastPath: true,
                    innerToolName: 'feature-flag-update',
                    status: 'plan_issued',
                    planMutations: 1,
                    planId: expect.stringMatching(/^[a-z]+(-[a-z]+){2}$/) as unknown as string,
                },
            },
        ])('a fast-pathed $case carries the fast-path flag and inner tool name', async ({ script, meta }) => {
            const harness = makeHarness({ withInnerTools: true })
            const outcome = await harness.runtime.run(script)
            expect(outcome.meta).toEqual(meta)
        })

        it('apply reports applied, then already_applied on the reused plan id', async () => {
            const harness = makeHarness()
            const planId = extractPlanId((await harness.runtime.run(MUTATING_SCRIPT)).output as string)
            expect((await harness.runtime.apply(planId)).meta.status).toBe('applied')
            expect((await harness.runtime.apply(planId)).meta.status).toBe('already_applied')
        })

        it.each([
            {
                case: 'a mistyped plan id',
                prepare: async (_harness: Harness): Promise<string> => 'no-such-plan',
                status: 'not_found',
            },
            {
                case: 'an expired plan id',
                prepare: async (harness: Harness): Promise<string> => {
                    const planId = extractPlanId((await harness.runtime.run(MUTATING_SCRIPT)).output as string)
                    harness.clock.nowMs += 601_000
                    return planId
                },
                status: 'not_found',
            },
            {
                case: 'a divergent world',
                prepare: async (harness: Harness): Promise<string> => {
                    const planId = extractPlanId((await harness.runtime.run(MUTATING_SCRIPT)).output as string)
                    harness.responses['GET /api/projects/2/feature_flags/'] = {
                        body: { count: 1, next: null, previous: null, results: [{ id: 9, key: 'beta', active: true }] },
                    }
                    return planId
                },
                status: 'diverged',
            },
            {
                case: 'a partway failure',
                prepare: async (harness: Harness): Promise<string> => {
                    const planId = extractPlanId((await harness.runtime.run(MUTATING_SCRIPT)).output as string)
                    harness.responses['PATCH /api/projects/2/feature_flags/1/'] = {
                        status: 500,
                        body: { detail: 'upstream boom' },
                    }
                    return planId
                },
                status: 'failed',
            },
        ])('apply reports $case as $status', async ({ prepare, status }) => {
            const harness = makeHarness()
            const planId = await prepare(harness)
            expect((await harness.runtime.apply(planId)).meta.status).toBe(status)
        })

        it.each([
            { command: 'tools', expected: 'tools' },
            { command: 'types FeatureFlag', expected: 'types' },
            { command: 'nonsense do-thing', expected: 'unknown' },
        ])(
            'the dispatcher reports the normalized verb "$expected" for "$command" before dispatch',
            async ({ command, expected }) => {
                const harness = makeHarness()
                // The unknown command throws — the verb must have been reported anyway.
                await harness.exec.handler(mockContext, { command }).catch(() => undefined)
                expect(harness.verbUpdates[0]).toEqual({ verb: expected, deprecatedVerb: false })
            }
        )

        it('run and apply propagate their structured outcome through trackVerb', async () => {
            const harness = makeHarness()
            const planText = await runCommand(harness, `run ${MUTATING_SCRIPT}`)
            expect(Object.assign({}, ...harness.verbUpdates)).toEqual({
                verb: 'run',
                deprecatedVerb: false,
                runStatus: 'plan_issued',
                planMutations: 1,
                fastPath: false,
            })

            harness.verbUpdates.length = 0
            await runCommand(harness, `apply ${extractPlanId(planText)}`)
            expect(Object.assign({}, ...harness.verbUpdates)).toEqual({
                verb: 'apply',
                deprecatedVerb: false,
                runStatus: 'applied',
            })
        })
    })

    describe('code-first arm (mcp-code-first, spec §4.3)', () => {
        it.each([
            {
                case: 'info aliases to the types fetch rendering of the mapped method',
                command: 'info feature-flag-update',
                contains: [
                    'Deprecated: `info` — use `types featureFlags.update` instead.',
                    'featureFlags.update(params: FeatureFlagsUpdateParams): Promise<FeatureFlag>',
                ],
            },
            {
                case: 'schema ignores the drill-down path with a note to follow named types',
                command: 'schema feature-flag-update filters.groups',
                contains: [
                    'Deprecated: `schema` — use `types featureFlags.update` instead. Drill-down paths are ignored — follow the named types instead.',
                    'featureFlags.update(params: FeatureFlagsUpdateParams): Promise<FeatureFlag>',
                ],
            },
            {
                case: 'search aliases to the types search rendering',
                command: 'search feature flag',
                contains: [
                    'Deprecated: `search` — use `types feature flag` instead.',
                    'featureFlags.update(params: FeatureFlagsUpdateParams): Promise<FeatureFlag>',
                ],
            },
        ])('$case', async ({ command, contains }) => {
            const harness = makeHarness({ withInnerTools: true, codeFirst: true })
            const result = await runCommand(harness, command)
            for (const expected of contains) {
                expect(result).toContain(expected)
            }
            // The alias replaces the legacy rendering — no JSON-schema payload rides along.
            expect(result).not.toContain('inputSchema')
        })

        it.each([
            {
                case: 'code-first with full script execution',
                options: { codeFirst: true },
                expected: 'types, run, apply, sql',
            },
            // Discovery-only session (no runtime): code-first is inert, run/apply unwired.
            {
                case: 'code-first without a runtime',
                options: { codeFirst: true, withRuntime: false },
                expected: 'tools, search, info, schema, call, types, sql',
            },
            // Fast-path-only server: the legacy instruction arm serves there, so
            // dispatch stays legacy too — but run/apply still dispatch (spec §4.2).
            {
                case: 'code-first without a sandbox executor',
                options: { codeFirst: true, withExecutor: false },
                expected: 'tools, search, info, schema, call, types, run, apply, sql',
            },
            {
                case: 'legacy with full script execution',
                options: { codeFirst: false },
                expected: 'tools, search, info, schema, call, types, run, apply, sql',
            },
        ] as const)('the unknown-command roster for $case lists exactly: $expected', async ({ options, expected }) => {
            const harness = makeHarness({ withInnerTools: true, ...options })
            await expect(runCommand(harness, 'nonsense')).rejects.toThrow(
                `Unknown command: "nonsense". Supported commands: ${expected}`
            )
        })

        // The instructions formatter only serves the code-first arm where full
        // script execution exists; dispatch must apply the same conjunction, or
        // agents reading the legacy prompt would get aliased responses and
        // footers steering to scripts this server rejects.
        it.each([
            { case: 'without a runtime', options: { withInnerTools: true, codeFirst: true, withRuntime: false } },
            {
                case: 'without a sandbox executor',
                options: { withInnerTools: true, codeFirst: true, withExecutor: false },
            },
        ] as const)('code-first stays inert $case — legacy renderings, no footers', async ({ options }) => {
            const harness = makeHarness(options)
            // `info` keeps the legacy YAML rendering instead of aliasing to `types`.
            const info = await runCommand(harness, 'info feature-flag-update')
            expect(info).toContain('inputSchema')
            expect(info).not.toContain('Deprecated')
            // `call` gets no footer recommending a `run` this server would reject.
            const call = await runCommand(harness, 'call feature-flag-get-all {"limit":2}')
            expect(call).not.toContain('Deprecated')
            // And the legacy arm must not contaminate the §4.6 deprecation A/B.
            expect(harness.verbUpdates.every((update) => update.deprecatedVerb !== true)).toBe(true)
        })

        it('tools keeps its JSON payload and gains the types footer', async () => {
            const harness = makeHarness({ withInnerTools: true, codeFirst: true })
            const result = await runCommand(harness, 'tools')
            const [payload, footer] = result.split('\n\n')
            expect(JSON.parse(payload!)).toContain('feature-flag-update')
            expect(footer).toBe(
                'Deprecated command — use `types <query | TypeName | domain.method | domain>` for SDK discovery instead.'
            )
        })

        it('call still dispatches and its footer carries the exact run equivalent with the input as a literal', async () => {
            const harness = makeHarness({ withInnerTools: true, codeFirst: true })
            const result = await runCommand(harness, 'call feature-flag-get-all {"limit":2}')
            expect(harness.handlerCalls).toEqual([{ tool: 'feature-flag-get-all', params: { limit: 2 } }])
            expect(result).toContain(
                `Deprecated: \`call\` — the code-first equivalent: run import { client } from '@posthog/sdk'; export default await client.featureFlags.list({"limit":2})`
            )
        })

        it('a call to a tool with no SDK method gets a generic footer, never a client.null equivalent', async () => {
            const harness = makeHarness({ withInnerTools: true, codeFirst: true })
            const result = await runCommand(harness, 'call session-summarize {}')
            expect(harness.handlerCalls).toEqual([{ tool: 'session-summarize', params: {} }])
            expect(result).toContain('this tool has no SDK method yet, so `call` keeps working for it')
            expect(result).not.toContain('client.null')
        })

        it('an info target with no SDK method falls back to the legacy rendering plus the types footer', async () => {
            const harness = makeHarness({ withInnerTools: true, codeFirst: true })
            const result = await runCommand(harness, 'info session-summarize')
            expect(result).toContain('name: session-summarize')
            expect(result).toContain('Deprecated command — use `types')
        })

        it.each([
            { command: 'tools', codeFirst: true, deprecated: true, verb: 'tools' },
            { command: 'call feature-flag-get-all {}', codeFirst: true, deprecated: true, verb: 'call' },
            { command: 'types FeatureFlag', codeFirst: true, deprecated: false, verb: 'types' },
            { command: 'tools', codeFirst: false, deprecated: false, verb: 'tools' },
        ])(
            'stamps deprecatedVerb=$deprecated for "$command" under codeFirst=$codeFirst',
            async ({ command, codeFirst, deprecated, verb }) => {
                const harness = makeHarness({ withInnerTools: true, codeFirst })
                await runCommand(harness, command)
                expect(harness.verbUpdates[0]).toEqual({ verb, deprecatedVerb: deprecated })
            }
        )

        it.each([
            { verb: 'tools', command: 'tools', jsonPayload: true },
            { verb: 'search', command: 'search feature-flag', jsonPayload: true },
            { verb: 'info', command: 'info feature-flag-update', jsonPayload: false },
            { verb: 'schema', command: 'schema feature-flag-update', jsonPayload: true },
            { verb: 'call', command: 'call feature-flag-get-all {"limit":2}', jsonPayload: false },
        ])('codeFirst=off leaves the legacy $verb response unchanged', async ({ command, jsonPayload }) => {
            const explicitOff = makeHarness({ withInnerTools: true, codeFirst: false })
            const unwired = makeHarness({ withInnerTools: true })
            const offResult = await runCommand(explicitOff, command)
            // Off must mean off: byte-identical to an exec with no code-first
            // option at all, and free of alias/footer text.
            expect(offResult).toBe(await runCommand(unwired, command))
            expect(offResult).not.toContain('Deprecated')
            if (jsonPayload) {
                // An appended footer would corrupt the JSON contract of these verbs.
                expect(() => JSON.parse(offResult)).not.toThrow()
            }
        })
    })

    describe('script parameter', () => {
        it('run accepts the source via the script parameter, byte-identical to inline source', async () => {
            const inline = makeHarness()
            const viaParam = makeHarness()
            const inlineResult = await runCommand(inline, `run ${READ_ONLY_SCRIPT}`)
            const paramResult = (await viaParam.exec.handler(mockContext, {
                command: 'run',
                script: READ_ONLY_SCRIPT,
            })) as string
            expect(paramResult).toBe(inlineResult)
        })

        it.each([
            { case: 'inline source in the command', command: 'run export default 1' },
            { case: 'a non-run verb', command: 'types FeatureFlag' },
        ])('rejects the script parameter combined with $case', async ({ command }) => {
            const harness = makeHarness()
            await expect(harness.exec.handler(mockContext, { command, script: 'export default 2' })).rejects.toThrow(
                '`command` must be exactly "run"'
            )
            expect(harness.calls).toHaveLength(0)
        })

        it('bare run with neither inline source nor script still throws the usage error', async () => {
            const harness = makeHarness()
            await expect(runCommand(harness, 'run')).rejects.toThrow('Usage: run <typescript source>')
        })
    })
})
