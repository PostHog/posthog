import { describe, expect, it, vi } from 'vitest'

import { GuidanceEngine, triggerMatches, type GuidanceCall } from '@/hono/guidance/engine'
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
    requiresTool: ['vision-scanners-inline-scan', 'vision-requests-get'],
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
    return makeToolExecutorState(
        [{ name: 'execute-sql' }, { name: 'vision-scanners-inline-scan' }, { name: 'vision-requests-get' }],
        {
            toolFeatureFlags: { [rule.flag]: true },
            suppressAnalytics: false,
            ...overrides,
        }
    )
}

async function run(
    engine: GuidanceEngine,
    state: ResolvedState,
    calls: GuidanceCall[]
): Promise<(string | undefined)[]> {
    const shown: (string | undefined)[] = []
    for (const call of calls) {
        const notice = await engine.evaluate(state, call)
        shown.push(notice && `${notice.ruleId}:${notice.outcome}`)
    }
    return shown
}

describe('GuidanceEngine', () => {
    it('shows the notice once the session reaches the threshold, and only once', async () => {
        const engine = new GuidanceEngine(makeGuidanceRedis(), [rule])
        await expect(run(engine, makeState(), [replayQuery, otherQuery, replayQuery, replayQuery])).resolves.toEqual([
            undefined,
            undefined,
            'test-rule:shown',
            undefined,
        ])
    })

    it('stamps a suppressed outcome once when the session already called a suggested tool', async () => {
        const engine = new GuidanceEngine(makeGuidanceRedis(), [rule])
        await expect(run(engine, makeState(), [visionCall, replayQuery, replayQuery, replayQuery])).resolves.toEqual([
            undefined,
            undefined,
            'test-rule:suppressed',
            undefined,
        ])
    })

    it.each([
        ['without org consent', false, 'no_consent'],
        ['when consent is unknown', undefined, 'no_consent'],
        ['with org consent', true, 'shown'],
    ])('stamps the consent outcome %s for a rule that needs it', async (_label, aiConsentGiven, outcome) => {
        const engine = new GuidanceEngine(makeGuidanceRedis(), [{ ...rule, requiresAiConsent: true }])
        const state = makeState({ aiConsentGiven })
        await engine.evaluate(state, replayQuery)
        const notice = await engine.evaluate(state, replayQuery)
        expect(notice).toMatchObject({ ruleId: 'test-rule', outcome })
        expect(notice?.text === undefined).toBe(outcome !== 'shown')
    })

    it('stamps a flag_off outcome without text when the flag is off', async () => {
        const engine = new GuidanceEngine(makeGuidanceRedis(), [rule])
        const state = makeState({ toolFeatureFlags: {} })
        await engine.evaluate(state, replayQuery)
        await expect(engine.evaluate(state, replayQuery)).resolves.toEqual({
            ruleId: 'test-rule',
            outcome: 'flag_off',
        })
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
        await expect(run(engine, second, [replayQuery, replayQuery])).resolves.toEqual([undefined, 'test-rule:shown'])
    })

    describe('a client that sends no handle', () => {
        const withHandle = (id: string, carriedContextHandle: boolean): ResolvedState =>
            makeState({
                carriedContextHandle,
                requestContext: { ...makeState().requestContext, mcpConversationId: id },
            })

        it('counts minted handles under the caller', async () => {
            const engine = new GuidanceEngine(makeGuidanceRedis(), [rule])
            await run(engine, withHandle('minted-1', false), [replayQuery])
            await expect(run(engine, withHandle('minted-2', false), [replayQuery])).resolves.toEqual([
                'test-rule:shown',
            ])
        })

        it.each([
            ['the match count', replayQuery, ['test-rule:shown', undefined]],
            ['suppression', visionCall, [undefined, 'test-rule:suppressed']],
        ])('keeps %s when the client later echoes the minted handle', async (_label, firstCall, expected) => {
            const engine = new GuidanceEngine(makeGuidanceRedis(), [rule])
            await run(engine, withHandle('minted-1', false), [firstCall])
            await expect(run(engine, withHandle('minted-1', true), [replayQuery, replayQuery])).resolves.toEqual(
                expected
            )
        })
    })

    it('reports a suppressed outcome on a later call when another rule wins the threshold call', async () => {
        const second: GuidanceRule = {
            ...rule,
            id: 'second-rule',
            flag: 'mcp-guidance-second',
            suppressIfCalled: ['read-data-schema'],
        }
        const engine = new GuidanceEngine(makeGuidanceRedis(), [rule, second])
        const state = makeState({ toolFeatureFlags: { [rule.flag]: true, [second.flag]: true } })
        const schemaCall: GuidanceCall = { toolName: 'read-data-schema', args: {}, isError: false }
        await expect(run(engine, state, [schemaCall, replayQuery, replayQuery, replayQuery])).resolves.toEqual([
            undefined,
            undefined,
            'test-rule:shown',
            'second-rule:suppressed',
        ])
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
        ['impersonated session', { isImpersonated: true }],
        ['analytics suppressed', { suppressAnalytics: true }],
        ['sandbox token', { apiKeyScopes: ['internal_run:read'] }],
        ['scout token', { apiKeyScopes: ['signal_scout_internal:write'] }],
        ['suggested tool not in roster', { allTools: [{ name: 'execute-sql' }] as ResolvedState['allTools'] }],
        [
            'one named tool missing from roster',
            {
                allTools: [
                    { name: 'execute-sql' },
                    { name: 'vision-scanners-inline-scan' },
                ] as ResolvedState['allTools'],
            },
        ],
    ])('shows nothing for %s', async (_label, overrides) => {
        const engine = new GuidanceEngine(makeGuidanceRedis(), [rule])
        await expect(run(engine, makeState(overrides), [replayQuery, replayQuery])).resolves.toEqual([
            undefined,
            undefined,
        ])
    })

    it('shows the notice to a scout when the rule lists the scout preset', async () => {
        const scoutRule: GuidanceRule = { ...rule, trigger: { ...rule.trigger, presets: ['user', 'scout'] } }
        const engine = new GuidanceEngine(makeGuidanceRedis(), [scoutRule])
        const state = makeState({ apiKeyScopes: ['signal_scout_internal:write', 'internal_run:read'] })
        await expect(run(engine, state, [replayQuery, replayQuery])).resolves.toEqual([undefined, 'test-rule:shown'])
    })

    it('matches only the configured outcome', async () => {
        const errorRule: GuidanceRule = { ...rule, trigger: { ...rule.trigger, outcome: 'error' }, threshold: 1 }
        const engine = new GuidanceEngine(makeGuidanceRedis(), [errorRule])
        await expect(run(engine, makeState(), [replayQuery, { ...replayQuery, isError: true }])).resolves.toEqual([
            undefined,
            'test-rule:shown',
        ])
    })

    it('shows nothing and logs when Redis fails', async () => {
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
        const engine = new GuidanceEngine(makeGuidanceRedis(true), [{ ...rule, threshold: 1 }])
        await expect(engine.evaluate(makeState(), replayQuery)).resolves.toBeUndefined()
        expect(warn).toHaveBeenCalledWith('[Guidance] evaluation failed:', expect.any(String))
        warn.mockRestore()
    })

    it.each([
        ['session_replay_events', true],
        ['raw_session_replay_events', true],
        ['session_replay_features', true],
        ['console_logs_log_entries', true],
        ['system.session_recordings', true],
        ['log_entries', false],
        ['batch_export_log_entries', false],
        ['sessions', false],
        ['events', false],
    ])('the replay rule matches SQL over %s: %s', (table, expected) => {
        const replayRule = GUIDANCE_RULES.find((r) => r.id === 'replay-sql-to-vision')!
        const call: GuidanceCall = {
            toolName: 'execute-sql',
            args: { query: `select 1 from ${table}` },
            isError: false,
        }
        expect(triggerMatches(replayRule, call)).toBe(expected)
    })

    it('ships every rule with a distinct id and flag', () => {
        expect(new Set(GUIDANCE_RULES.map((r) => r.id)).size).toBe(GUIDANCE_RULES.length)
        expect(new Set(GUIDANCE_RULES.map((r) => r.flag)).size).toBe(GUIDANCE_RULES.length)
    })
})
