import { promises as fs } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { buildCliCodeExecution, parseRunArgs, runCliApply, runCliRun } from '@/cli/code-exec'
import type { Context } from '@/tools/types'

import { stubFetch } from './code-exec/fixtures'

const MUTATING_SCRIPT = [
    "import { client } from '@posthog/sdk'",
    'const flags = await client.featureFlags.list()',
    'for (const flag of flags.results) {',
    '    await client.featureFlags.update({ id: flag.id, active: false })',
    '}',
    'export default { updated: flags.results.map((flag) => flag.key) }',
].join('\n')

function makeResponses(): Record<string, { status?: number; body: unknown }> {
    return {
        'GET /api/users/@me/': { body: { team: { id: 2 }, organization: { id: 'org-1' } } },
        'GET /api/projects/2/feature_flags/': {
            body: { count: 1, next: null, previous: null, results: [{ id: 1, key: 'alpha', active: true }] },
        },
        'PATCH /api/projects/2/feature_flags/1/': { body: { id: 1, key: 'alpha', active: false } },
    }
}

interface CliTestContext {
    context: Context
    calls: Array<{ method: string; url: string; body: unknown }>
    events: Array<{ event: string; properties: Record<string, unknown> }>
}

/** A minimal CLI `Context`: authenticated fetch stub + identity + session scope + analytics recorder. */
function makeCliContext(): CliTestContext {
    const stub = stubFetch(makeResponses())
    const events: CliTestContext['events'] = []
    const context = {
        api: { fetchRaw: stub.fetch },
        getDistinctId: async () => 'cli-user',
        stateManager: {
            getProjectId: async () => '2',
            getOrgID: async () => 'org-1',
        },
        trackEvent: async (event: string, properties: Record<string, unknown> = {}) => {
            events.push({ event, properties })
        },
    } as unknown as Context
    return { context, calls: stub.calls, events }
}

function extractPlanId(planText: string): string {
    const match = /\napply (\S+)/.exec(planText)
    expect(match).not.toBeNull()
    return match![1]!
}

describe('CLI code execution (spec §4.8)', () => {
    describe('parseRunArgs', () => {
        it.each([
            {
                case: 'inline source words',
                args: ['export', 'default', '1'],
                tty: true,
                expected: { yes: false, source: { kind: 'inline', source: 'export default 1' } },
            },
            {
                case: '--yes with inline source',
                args: ['--yes', 'export default 1'],
                tty: true,
                expected: { yes: true, source: { kind: 'inline', source: 'export default 1' } },
            },
            {
                case: '--file',
                args: ['--file', 'script.ts'],
                tty: true,
                expected: { yes: false, source: { kind: 'file', path: 'script.ts' } },
            },
            {
                case: '--file with --yes after it',
                args: ['--file', 'script.ts', '--yes'],
                tty: true,
                expected: { yes: true, source: { kind: 'file', path: 'script.ts' } },
            },
            {
                case: 'a lone dash (explicit stdin)',
                args: ['-'],
                tty: true,
                expected: { yes: false, source: { kind: 'stdin' } },
            },
            {
                case: 'no args with piped stdin',
                args: [],
                tty: false,
                expected: { yes: false, source: { kind: 'stdin' } },
            },
        ])('parses $case', ({ args, tty, expected }) => {
            expect(parseRunArgs(args, { stdinIsTty: tty })).toEqual(expected)
        })

        it.each([
            { case: 'no source on a TTY', args: [], tty: true, message: 'Usage: posthog-cli api run' },
            {
                case: '--file combined with inline source',
                args: ['--file', 'a.ts', 'export default 1'],
                tty: true,
                message: 'not both',
            },
        ])('rejects $case', ({ args, tty, message }) => {
            expect(() => parseRunArgs(args, { stdinIsTty: tty })).toThrow(message)
        })
    })

    describe('run → plan file → apply', () => {
        const ORIG_POSTHOG_HOME = process.env.POSTHOG_HOME
        let tmpHome: string

        beforeEach(async () => {
            tmpHome = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-cli-test-'))
            process.env.POSTHOG_HOME = tmpHome
        })

        afterEach(async () => {
            if (ORIG_POSTHOG_HOME === undefined) {
                delete process.env.POSTHOG_HOME
            } else {
                process.env.POSTHOG_HOME = ORIG_POSTHOG_HOME
            }
            await fs.rm(tmpHome, { recursive: true, force: true })
        })

        it('run persists the plan under $POSTHOG_HOME and a separate invocation applies it once', async () => {
            const { context, calls, events } = makeCliContext()
            const printed: unknown[] = []
            const print = (result: unknown): void => {
                printed.push(result)
            }

            const first = buildCliCodeExecution(context, ['*'])
            await runCliRun({ context, print }, first.runtime, { source: MUTATING_SCRIPT, yes: false })

            const planText = printed[0] as string
            expect(planText).toContain('Nothing has been applied yet')
            // The CLI wires no compile gate, so the contract-lints fallback flags the skipped typecheck.
            expect(planText).toContain('typecheck was skipped')
            expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(0)

            // The plan survives process exit as a private hex-named JSON record.
            const planDir = path.join(tmpHome, 'code-exec', 'plans')
            const files = await fs.readdir(planDir)
            expect(files).toHaveLength(1)
            expect(files[0]).toMatch(/^[0-9a-f]{32}\.json$/)

            // A fresh wiring simulates the separate one-shot `apply` invocation.
            const second = buildCliCodeExecution(context, ['*'])
            const planId = extractPlanId(planText)
            await runCliApply({ context, print }, second.runtime, planId)
            expect(printed[1]).toContain('Applied.')
            expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(1)

            // Reuse across yet another invocation hits the tombstone, not the API.
            await runCliApply({ context, print }, buildCliCodeExecution(context, ['*']).runtime, planId)
            expect(printed[2]).toContain('already been applied')
            expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(1)

            // Verb-labelled analytics parity with the hosted exec dimensions (spec §4.6 Phase 0).
            expect(events.map((e) => e.properties.$mcp_exec_verb)).toEqual(['run', 'apply', 'apply'])
            expect(events[0]!.properties).toMatchObject({
                tool_name: 'exec',
                $mcp_tool_name: 'exec',
                $mcp_is_error: false,
                $mcp_exec_run_status: 'plan_issued',
                $mcp_exec_plan_mutations: 1,
                $mcp_exec_fast_path: false,
            })
            expect(events[1]!.properties).toMatchObject({ $mcp_exec_run_status: 'applied' })
            expect(events[2]!.properties).toMatchObject({ $mcp_exec_run_status: 'already_applied' })
        })

        it('--yes applies the issued plan in the same invocation: plan first, then the receipt', async () => {
            const { context, calls, events } = makeCliContext()
            const printed: unknown[] = []
            const { runtime } = buildCliCodeExecution(context, ['*'])

            await runCliRun({ context, print: (r) => printed.push(r) }, runtime, {
                source: MUTATING_SCRIPT,
                yes: true,
            })

            expect(printed).toHaveLength(2)
            expect(printed[0]).toContain('Nothing has been applied yet')
            expect(printed[1]).toContain('Applied.')
            expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(1)
            expect(events.map((e) => e.properties.$mcp_exec_verb)).toEqual(['run', 'apply'])
        })

        it('--yes with a read-only script prints only the output — there is no plan to apply', async () => {
            const { context, calls, events } = makeCliContext()
            const printed: unknown[] = []
            const { runtime } = buildCliCodeExecution(context, ['*'])

            await runCliRun({ context, print: (r) => printed.push(r) }, runtime, {
                source: 'export default 41 + 1',
                yes: true,
            })

            expect(printed).toHaveLength(1)
            expect(printed[0]).toContain('42')
            expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(0)
            expect(events.map((e) => e.properties.$mcp_exec_verb)).toEqual(['run'])
            expect(events[0]!.properties).toMatchObject({ $mcp_exec_run_status: 'read_only' })
        })
    })
})
