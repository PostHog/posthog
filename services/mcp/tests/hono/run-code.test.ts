import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

vi.mock('@/tools/generated', () => ({ GENERATED_TOOL_MAP: {} }))

vi.mock('@/lib/posthog', async () => {
    const { PostHogMCP } = await import('@posthog/mcp-analytics')
    const client = new PostHogMCP('phc_test', { disabled: true })
    return { getPostHogClient: () => client }
})

import { InstructionsBuilder } from '@/hono/instructions'
import { ToolCatalog } from '@/hono/tool-catalog'
import { ToolExecutor } from '@/hono/tool-executor'
import { getPostHogClient } from '@/lib/posthog'
import { CODE_RUN_LIMITS, runCode } from '@/tools/run-code'

import { makeToolExecutorState } from '../shared/test-utils'

const FAKE_TOOLS = {
    flags: {
        name: 'feature-flag-get-all',
        destructive: false,
        result: {
            results: [
                { key: 'new-checkout', rollout: 90 },
                { key: 'old-banner', rollout: 10 },
            ],
        },
    },
    dashboards: { name: 'dashboards-get-all', destructive: false, result: { results: [{ id: 1 }, { id: 2 }] } },
    deleteDashboard: { name: 'dashboard-delete', destructive: true, result: { deleted: true } },
}

type FakeToolKey = keyof typeof FAKE_TOOLS

interface ScriptRun {
    isError: boolean
    body: unknown
    dispatched: Record<FakeToolKey, unknown[]>
}

async function runScript(executor: ToolExecutor, code: string): Promise<ScriptRun> {
    const dispatched: Record<FakeToolKey, unknown[]> = { flags: [], dashboards: [], deleteDashboard: [] }
    const tools = (Object.keys(FAKE_TOOLS) as FakeToolKey[]).map((key) => {
        const { name, destructive, result } = FAKE_TOOLS[key]
        return {
            name,
            title: name,
            description: `Synthetic ${name}`,
            scopes: [],
            annotations: { readOnlyHint: !destructive, destructiveHint: destructive },
            schema: z.object({
                active: z.string().optional(),
                search: z.string().optional(),
                id: z.number().optional(),
            }),
            handler: async (_context: unknown, params: unknown) => {
                dispatched[key].push(params)
                return result
            },
        }
    })
    const state = makeToolExecutorState(tools, {
        useSingleExec: true,
        suppressAnalytics: false,
        requestContext: { ...makeToolExecutorState([]).requestContext, mode: 'code' },
    })
    const response = (await executor.handleToolCall({ name: 'run_code', arguments: { code } }, state)) as {
        content: { text: string }[]
        isError?: boolean
    }
    return { isError: response.isError === true, body: JSON.parse(response.content[0]!.text), dispatched }
}

describe('run_code', () => {
    let executor: ToolExecutor

    beforeAll(() => {
        executor = new ToolExecutor(new ToolCatalog(), new InstructionsBuilder(''))
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    it.each([
        {
            label: 'returns a value filtered from two tool calls',
            code: `
                const flags = await posthog.call('feature-flag-get-all', { active: 'true' })
                const dashboards = await posthog.call('dashboards-get-all', { search: 'growth' })
                console.log('flags', flags.results.length)
                return {
                    rolledOut: flags.results.filter((flag) => flag.rollout > 50).map((flag) => flag.key),
                    dashboards: dashboards.results.length,
                }`,
            isError: false,
            body: { result: { rolledOut: ['new-checkout'], dashboards: 2 }, logs: ['flags 2'], calls: 2 },
            dispatched: { flags: [{ active: 'true' }], dashboards: [{ search: 'growth' }], deleteDashboard: [] },
        },
        {
            label: 'reports a guest exception as a tool error',
            code: `await posthog.call('dashboards-get-all', {}); throw new TypeError('no dashboards matched')`,
            isError: true,
            body: { error: 'TypeError: no dashboards matched', logs: [], calls: 1 },
            dispatched: { flags: [], dashboards: [{}], deleteDashboard: [] },
        },
        {
            label: 'runs a destructive tool the way hosted exec does',
            code: `return await posthog.call('dashboard-delete', { id: 7 })`,
            isError: false,
            body: { result: { deleted: true }, logs: [], calls: 1 },
            dispatched: { flags: [], dashboards: [], deleteDashboard: [{ id: 7 }] },
        },
        {
            label: 'runs any exec command through posthog.exec',
            code: `return await posthog.exec('call --json dashboards-get-all {}')`,
            isError: false,
            body: { result: { results: [{ id: 1 }, { id: 2 }] }, logs: [], calls: 1 },
            dispatched: { flags: [], dashboards: [{}], deleteDashboard: [] },
        },
        {
            label: 'refuses a tool name that smuggles the confirm flag',
            code: `await posthog.call('--confirm dashboard-delete', { id: 7 })`,
            isError: true,
            body: { error: 'Error: Invalid tool name: "--confirm dashboard-delete"', logs: [], calls: 1 },
            dispatched: { flags: [], dashboards: [], deleteDashboard: [] },
        },
        {
            label: 'stops the run at the call limit even when the script catches the error',
            code: `
                for (let i = 0; i < ${CODE_RUN_LIMITS.maxCalls + 10}; i++) {
                    try { await posthog.call('dashboards-get-all', {}) } catch {}
                }
                return 'finished'`,
            isError: true,
            body: {
                error: `Call limit reached: a run may make at most ${CODE_RUN_LIMITS.maxCalls} posthog.call or posthog.exec invocations.`,
                logs: [],
                calls: CODE_RUN_LIMITS.maxCalls,
            },
            dispatched: {
                flags: [],
                dashboards: Array.from({ length: CODE_RUN_LIMITS.maxCalls }, () => ({})),
                deleteDashboard: [],
            },
        },
    ])('$label', async ({ code, isError, body, dispatched }) => {
        expect(await runScript(executor, code)).toEqual({ isError, body, dispatched })
    })

    it.each([
        { label: 'a busy guest', code: 'while (true) {}', callsHost: false },
        {
            label: 'a guest waiting on a host call that never returns',
            code: `await posthog.call('slow', {})`,
            callsHost: true,
        },
    ])('times out $label', async ({ code, callsHost }) => {
        const host = {
            search: vi.fn(),
            schema: vi.fn(),
            exec: vi.fn(),
            call: vi.fn(() => new Promise<never>(() => {})),
        }

        const outcome = await runCode(code, host, { ...CODE_RUN_LIMITS, timeoutMs: 200 })

        expect(outcome).toEqual({
            ok: false,
            error: 'Timed out after 0.2 seconds.',
            logs: [],
            calls: callsHost ? 1 : 0,
        })
        expect(await runCode('return 1 + 1', host)).toEqual({ ok: true, result: 2, logs: [], calls: 0 })
    })

    it('stamps one code run id on a run and every call it makes, and a new id on the next run', async () => {
        const captureToolCall = vi.spyOn(getPostHogClient(), 'captureToolCall').mockImplementation(() => {})
        const script = `
            await posthog.call('feature-flag-get-all', {})
            await posthog.call('dashboards-get-all', {})
            return 'done'`

        await runScript(executor, script)
        await runScript(executor, script)
        await new Promise((resolve) => setImmediate(resolve))

        const events = captureToolCall.mock.calls.map(([event]) => ({
            tool: event.toolName,
            mode: event.properties?.$mcp_mode,
            runId: event.properties?.mcp_code_run_id as string,
        }))
        const runIds = [...new Set(events.map((event) => event.runId))]
        expect(runIds).toHaveLength(2)
        expect(events.map(({ tool, mode, runId }) => ({ tool, mode, run: runIds.indexOf(runId) }))).toEqual([
            { tool: 'feature-flag-get-all', mode: 'code', run: 0 },
            { tool: 'dashboards-get-all', mode: 'code', run: 0 },
            { tool: 'run_code', mode: 'code', run: 0 },
            { tool: 'feature-flag-get-all', mode: 'code', run: 1 },
            { tool: 'dashboards-get-all', mode: 'code', run: 1 },
            { tool: 'run_code', mode: 'code', run: 1 },
        ])
    })
})
