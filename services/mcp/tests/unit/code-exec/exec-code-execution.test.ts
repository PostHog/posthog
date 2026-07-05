import { beforeAll, describe, expect, it } from 'vitest'
import { z } from 'zod'

import { createPlanTokenCodec, MemoryPlanStore } from '@/lib/code-exec'
import { NonceLedger } from '@/lib/signed-state'
import { checkScript } from '@/tools/code-exec/compile-gate'
import type { DiscoveryIndex } from '@/tools/code-exec/discovery'
import { LocalVmExecutor } from '@/tools/code-exec/executor'
import { createCodeExecutionRuntime, type CodeExecutionRuntime } from '@/tools/code-exec/runtime'
import { createExecTool } from '@/tools/exec'
import type { Context, Tool } from '@/tools/types'

import { FIXTURE_TABLE, stubFetch } from './fixtures'

const KEY = Buffer.alloc(32, 0x42)
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
    ],
}

/** In-memory redis stub satisfying the NonceLedger surface (`SET NX EX`). */
function makeNonceRedis(): {
    set: (key: string, value: string, ...args: (string | number)[]) => Promise<string | null>
} {
    const store = new Map<string, string>()
    return {
        set: async (key, value, ...args) => {
            if (args.includes('NX') && store.has(key)) {
                return null
            }
            store.set(key, value)
            return 'OK'
        },
    }
}

interface Harness {
    exec: Tool<z.ZodObject<{ command: z.ZodString }>>
    runtime: CodeExecutionRuntime
    responses: Record<string, { status?: number; body: unknown }>
    calls: Array<{ method: string; url: string; body: unknown }>
    clock: { nowMs: number }
}

function makeHarness(options: { sessionScopes?: string[] } = {}): Harness {
    const clock = { nowMs: FIXED_NOW }
    const responses: Record<string, { status?: number; body: unknown }> = {
        'GET /api/users/@me/': { body: { team: { id: 2 }, organization: { id: 'org-1' } } },
        'GET /api/projects/2/feature_flags/': {
            body: { count: 1, next: null, previous: null, results: [{ id: 1, key: 'alpha', active: true }] },
        },
        'PATCH /api/projects/2/feature_flags/1/': { body: { id: 1, key: 'alpha', active: false } },
    }
    const stub = stubFetch(responses)
    const runtime = createCodeExecutionRuntime({
        realFetch: stub.fetch,
        getSub: async () => 'test-distinct-id',
        codec: createPlanTokenCodec(KEY, { now: () => clock.nowMs }),
        planStore: new MemoryPlanStore({ now: () => clock.nowMs }),
        nonceLedger: new NonceLedger(makeNonceRedis()),
        sessionScopes: options.sessionScopes ?? ['feature_flag:write'],
        executor: new LocalVmExecutor(),
        classifierTable: FIXTURE_TABLE,
        discoveryIndex: DISCOVERY_FIXTURE,
    })
    const exec = createExecTool([], mockContext, 'desc', 'cmd', undefined, undefined, [], {
        codeExecution: runtime,
    })
    return { exec, runtime, responses, calls: stub.calls, clock }
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

async function runCommand(harness: Harness, command: string): Promise<string> {
    return (await harness.exec.handler(mockContext, { command })) as string
}

function extractApplyToken(planText: string): string {
    const match = /\napply (\S+)/.exec(planText)
    expect(match).not.toBeNull()
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

        it('with a runtime, the unknown-command error advertises types, run, and apply', async () => {
            const harness = makeHarness()
            await expect(runCommand(harness, 'nonsense')).rejects.toThrow(
                'Unknown command: "nonsense". Supported commands: tools, search, info, schema, call, types, run, apply'
            )
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

        it('falls back to substring matching when the pattern is not a valid regex', async () => {
            const harness = makeHarness()
            // Unbalanced paren: invalid regex, but a literal substring of the signature.
            const result = await runCommand(harness, 'types update(')
            expect(result).toContain('featureFlags.update')
            expect(result).not.toContain('annotations.create')
        })

        it('show expands a type declaration and BFS-fills its referenced types', async () => {
            const harness = makeHarness()
            const result = await runCommand(harness, 'types show FeatureFlagsUpdateParams')
            expect(result).toContain('export interface FeatureFlagsUpdateParams { id: number; active?: boolean }')
            expect(result).toContain('export interface FeatureFlag { id: number; key: string }')
        })

        it('show with a bare domain lists every method of the resource', async () => {
            const harness = makeHarness()
            const result = await runCommand(harness, 'types show featureFlags')
            expect(result).toContain('featureFlags.update(params: FeatureFlagsUpdateParams): Promise<FeatureFlag>')
            expect(result).toContain('export interface FeatureFlagsUpdateParams')
        })

        it('show rejects an unknown symbol with a search hint', async () => {
            const harness = makeHarness()
            await expect(runCommand(harness, 'types show NoSuchThing')).rejects.toThrow('Unknown symbol "NoSuchThing"')
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

    describe('run (read-only)', () => {
        it('executes directly, returning output and console with no plan token', async () => {
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

        it('reports a thrown script error without issuing a token', async () => {
            const harness = makeHarness()
            const script = "throw new Error('boom')\nexport default 1"
            const result = await runCommand(harness, `run ${script}`)
            expect(result).toContain('Script failed: boom')
            expect(result).not.toContain('apply ')
        })
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

            const token = extractApplyToken(planText)
            const receipt = await runCommand(harness, `apply ${token}`)
            expect(receipt).toContain('Applied.')
            expect(receipt).toContain('[applied] PATCH /api/projects/2/feature_flags/1/')
            const patches = harness.calls.filter((c) => c.method === 'PATCH')
            expect(patches).toHaveLength(1)
            expect(patches[0]!.body).toEqual({ active: false })
        })

        it('rejects a reused token — a plan token is single-use', async () => {
            const harness = makeHarness()
            const token = extractApplyToken(await runCommand(harness, `run ${MUTATING_SCRIPT}`))
            await runCommand(harness, `apply ${token}`)
            const second = await runCommand(harness, `apply ${token}`)
            expect(second).toContain('already been applied')
            // Only the first apply reached the API.
            expect(harness.calls.filter((c) => c.method === 'PATCH')).toHaveLength(1)
        })

        it('refuses an expired token and instructs a re-plan instead of auto-applying', async () => {
            const harness = makeHarness()
            const token = extractApplyToken(await runCommand(harness, `run ${MUTATING_SCRIPT}`))
            harness.clock.nowMs += 601_000
            const result = await runCommand(harness, `apply ${token}`)
            expect(result).toContain('Plan expired')
            expect(result).toContain('Re-run the script')
            expect(harness.calls.filter((c) => c.method === 'PATCH')).toHaveLength(0)
        })

        it('rejects a tampered token without applying anything', async () => {
            const harness = makeHarness()
            await runCommand(harness, `run ${MUTATING_SCRIPT}`)
            const result = await runCommand(harness, 'apply not-a-real-token')
            expect(result).toContain('Plan token rejected')
            expect(harness.calls.filter((c) => c.method === 'PATCH')).toHaveLength(0)
        })

        it('aborts with a divergence message when the world changed between plan and apply', async () => {
            const harness = makeHarness()
            const token = extractApplyToken(await runCommand(harness, `run ${MUTATING_SCRIPT}`))

            // Another actor replaced the flag: the list now returns a different
            // target, so the re-run script mutates an id that is not in the plan.
            harness.responses['GET /api/projects/2/feature_flags/'] = {
                body: { count: 1, next: null, previous: null, results: [{ id: 9, key: 'beta', active: true }] },
            }

            const result = await runCommand(harness, `apply ${token}`)
            expect(result).toContain('The world changed since you confirmed')
            expect(result).toContain('PATCH /api/projects/2/feature_flags/9/')
            expect(result).toContain('[skipped]')
            expect(harness.calls.filter((c) => c.method === 'PATCH')).toHaveLength(0)
        })
    })
})
