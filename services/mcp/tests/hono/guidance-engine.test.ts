import { describe, expect, it } from 'vitest'

import type { RedisLike } from '@/hono/cache/RedisCache'
import { GuidanceEngine, type GuidanceCall } from '@/hono/guidance/engine'
import { GUIDANCE_RULES, type GuidanceRule } from '@/hono/guidance/rules'
import type { ResolvedState } from '@/hono/request-state-resolver'

import { makeToolExecutorState } from '../shared/test-utils'

function makeRedis(failing = false): RedisLike {
    const store = new Map<string, string>()
    const guard = async <T>(value: T): Promise<T> => {
        if (failing) {
            throw new Error('redis down')
        }
        return value
    }
    return {
        get: (key) => guard(store.get(key) ?? null),
        set: (key, value) => {
            store.set(key, value)
            return guard('OK')
        },
        del: async (...keys) => keys.filter((key) => store.delete(key)).length,
        scan: async () => ['0', []],
        incr: (key) => {
            const next = Number(store.get(key) ?? 0) + 1
            store.set(key, String(next))
            return guard(next)
        },
        expire: () => guard(1),
        ttl: () => guard(-1),
        eval: () => guard(null),
    }
}

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
        const engine = new GuidanceEngine(makeRedis(), [rule])
        await expect(run(engine, makeState(), [replayQuery, otherQuery, replayQuery, replayQuery])).resolves.toEqual([
            undefined,
            undefined,
            'test-rule',
            undefined,
        ])
    })

    it('stays silent once the session has called a suppressing tool', async () => {
        const engine = new GuidanceEngine(makeRedis(), [rule])
        await expect(run(engine, makeState(), [visionCall, replayQuery, replayQuery])).resolves.toEqual([
            undefined,
            undefined,
            undefined,
        ])
    })

    it('keeps sessions apart', async () => {
        const engine = new GuidanceEngine(makeRedis(), [rule])
        const first = makeState()
        const second = makeState({ requestContext: { ...first.requestContext, mcpSessionId: 'sess-2' } })
        await run(engine, first, [replayQuery])
        await expect(run(engine, second, [replayQuery, replayQuery])).resolves.toEqual([undefined, 'test-rule'])
    })

    it.each([
        ['flag off', { toolFeatureFlags: {} }],
        ['impersonated session', { isImpersonated: true }],
        ['analytics suppressed', { suppressAnalytics: true }],
        ['sandbox token', { apiKeyScopes: ['internal_run:read'] }],
        ['scout token', { apiKeyScopes: ['signal_scout_internal:write'] }],
        ['suggested tool not in roster', { allTools: [{ name: 'execute-sql' }] as ResolvedState['allTools'] }],
    ])('shows nothing for %s', async (_label, overrides) => {
        const engine = new GuidanceEngine(makeRedis(), [rule])
        await expect(run(engine, makeState(overrides), [replayQuery, replayQuery])).resolves.toEqual([
            undefined,
            undefined,
        ])
    })

    it('matches only the configured outcome', async () => {
        const errorRule: GuidanceRule = { ...rule, trigger: { ...rule.trigger, outcome: 'error' }, threshold: 1 }
        const engine = new GuidanceEngine(makeRedis(), [errorRule])
        await expect(run(engine, makeState(), [replayQuery, { ...replayQuery, isError: true }])).resolves.toEqual([
            undefined,
            'test-rule',
        ])
    })

    it('shows nothing when Redis fails', async () => {
        const engine = new GuidanceEngine(makeRedis(true), [{ ...rule, threshold: 1 }])
        await expect(engine.evaluate(makeState(), replayQuery)).resolves.toBeUndefined()
    })

    it('ships every rule with a distinct id and flag', () => {
        expect(new Set(GUIDANCE_RULES.map((r) => r.id)).size).toBe(GUIDANCE_RULES.length)
        expect(new Set(GUIDANCE_RULES.map((r) => r.flag)).size).toBe(GUIDANCE_RULES.length)
    })
})
