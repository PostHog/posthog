import { describe, expect, it } from 'vitest'

import { GuidanceEngine, type GuidanceCall } from '@/hono/guidance/engine'
import { GUIDANCE_RULES, type GuidanceRule } from '@/hono/guidance/rules'
import type { ResolvedState } from '@/hono/request-state-resolver'

import { makeToolExecutorState } from '../shared/test-utils'
import { makeGuidanceRedis } from './helpers/guidance-redis-stubs'

const rule: GuidanceRule = {
    id: 'test-rule',
    flag: 'mcp-guidance-test',
    trigger: {
        tool: 'execute-sql',
        argPath: 'query',
        argPattern: /session_replay_events/i,
        outcome: 'any',
        presets: ['user'],
    },
    threshold: 2,
    maxPerSession: 1,
    suppressIfCalled: ['vision-*'],
    requiresTool: ['vision-scanners-inline-scan'],
    text: 'Try Replay Vision.',
}

const replayQuery: GuidanceCall = {
    toolName: 'execute-sql',
    args: { query: 'select session_id from session_replay_events' },
    isError: false,
}
const otherQuery: GuidanceCall = { toolName: 'execute-sql', args: { query: 'select 1 from events' }, isError: false }
const visionCall: GuidanceCall = { toolName: 'vision-scanners-inline-scan', args: {}, isError: false }

function makeState(overrides: Partial<ResolvedState> = {}): ResolvedState {
    return makeToolExecutorState([{ name: 'execute-sql' }, { name: 'vision-scanners-inline-scan' }], {
        toolFeatureFlags: { [rule.flag]: true },
        suppressAnalytics: false,
        ...overrides,
    })
}

async function run(
    engine: GuidanceEngine,
    state: ResolvedState,
    calls: GuidanceCall[]
): Promise<(string | undefined)[]> {
    const shown: (string | undefined)[] = []
    for (const call of calls) {
        shown.push((await engine.evaluate(state, call))?.ruleId)
    }
    return shown
}

describe('GuidanceEngine', () => {
    it('shows the notice once the session reaches the threshold, and only once', async () => {
        const engine = new GuidanceEngine(makeGuidanceRedis(), [rule])
        await expect(run(engine, makeState(), [replayQuery, otherQuery, replayQuery, replayQuery])).resolves.toEqual([
            undefined,
            undefined,
            'test-rule',
            undefined,
        ])
    })

    it('stays silent once the session has called a suppressing tool', async () => {
        const engine = new GuidanceEngine(makeGuidanceRedis(), [rule])
        await expect(run(engine, makeState(), [visionCall, replayQuery, replayQuery])).resolves.toEqual([
            undefined,
            undefined,
            undefined,
        ])
    })

    it.each([
        [
            'sessions',
            (first: ResolvedState): Partial<ResolvedState> => ({
                requestContext: { ...first.requestContext, mcpSessionId: 'sess-2' },
            }),
        ],
        ['callers echoing the same session handle', (): Partial<ResolvedState> => ({ distinctId: 'other-caller' })],
    ])('keeps %s apart', async (_label, overrides) => {
        const engine = new GuidanceEngine(makeGuidanceRedis(), [rule])
        const first = makeState({ requestContext: { ...makeState().requestContext, mcpSessionId: 'sess-1' } })
        const second = makeState({ ...first, ...overrides(first) })
        await run(engine, first, [replayQuery])
        await expect(run(engine, second, [replayQuery, replayQuery])).resolves.toEqual([undefined, 'test-rule'])
    })

    it('reserves the allowance once when matching calls run concurrently', async () => {
        const engine = new GuidanceEngine(makeGuidanceRedis(), [rule])
        const state = makeState()
        await engine.evaluate(state, replayQuery)
        const shown = await Promise.all([engine.evaluate(state, replayQuery), engine.evaluate(state, replayQuery)])
        expect(shown.filter(Boolean)).toHaveLength(1)
    })

    it('lets a later rule keep its allowance when an earlier rule fires on the same call', async () => {
        const second: GuidanceRule = { ...rule, id: 'second-rule', flag: 'mcp-guidance-second' }
        const redis = makeGuidanceRedis()
        const engine = new GuidanceEngine(redis, [rule, second])
        const state = makeState({ toolFeatureFlags: { [rule.flag]: true, [second.flag]: true } })
        await run(engine, state, [replayQuery, replayQuery])
        expect([...redis.store.keys()].filter((key) => key.endsWith(':shown'))).toEqual([
            expect.stringContaining(':test-rule:shown'),
        ])
    })

    it.each([
        ['flag off', { toolFeatureFlags: {} }],
        ['impersonated session', { isImpersonated: true }],
        ['analytics suppressed', { suppressAnalytics: true }],
        ['sandbox token', { apiKeyScopes: ['internal_run:read'] }],
        ['scout token', { apiKeyScopes: ['signal_scout_internal:write'] }],
        ['suggested tool not in roster', { allTools: [{ name: 'execute-sql' }] as ResolvedState['allTools'] }],
    ])('shows nothing for %s', async (_label, overrides) => {
        const engine = new GuidanceEngine(makeGuidanceRedis(), [rule])
        await expect(run(engine, makeState(overrides), [replayQuery, replayQuery])).resolves.toEqual([
            undefined,
            undefined,
        ])
    })

    it('matches only the configured outcome', async () => {
        const errorRule: GuidanceRule = { ...rule, trigger: { ...rule.trigger, outcome: 'error' }, threshold: 1 }
        const engine = new GuidanceEngine(makeGuidanceRedis(), [errorRule])
        await expect(run(engine, makeState(), [replayQuery, { ...replayQuery, isError: true }])).resolves.toEqual([
            undefined,
            'test-rule',
        ])
    })

    it('shows nothing when Redis fails', async () => {
        const engine = new GuidanceEngine(makeGuidanceRedis(true), [{ ...rule, threshold: 1 }])
        await expect(engine.evaluate(makeState(), replayQuery)).resolves.toBeUndefined()
    })

    it('ships every rule with a distinct id and flag', () => {
        expect(new Set(GUIDANCE_RULES.map((r) => r.id)).size).toBe(GUIDANCE_RULES.length)
        expect(new Set(GUIDANCE_RULES.map((r) => r.flag)).size).toBe(GUIDANCE_RULES.length)
    })
})
