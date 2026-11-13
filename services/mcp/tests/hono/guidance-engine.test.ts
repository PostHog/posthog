import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import { GuidanceEngine, triggerMatches, type GuidanceCall } from '@/hono/guidance/engine'
import { GUIDANCE_RULES, MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG, type GuidanceRule } from '@/hono/guidance/rules'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { MCPClientProfile } from '@/lib/client-detection'

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
        const state = makeState({
            aiConsentGiven,
            ...(aiConsentGiven === true ? {} : { allTools: [{ name: 'execute-sql' }] as ResolvedState['allTools'] }),
        })
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

        describe('with a notice that fires on the first match', () => {
            const firstMatchRule: GuidanceRule = { ...rule, threshold: 1 }

            it.each([
                ['after the caller counters expire', [31]],
                ['after the first day of a busy conversation', Array.from({ length: 80 }, () => 20)],
            ])('keeps the per-conversation cap %s', async (_label, gapsInMinutes) => {
                const redis = makeGuidanceRedis()
                const engine = new GuidanceEngine(redis, [firstMatchRule])
                const outcomes = await run(engine, withHandle('minted-1', false), [replayQuery])
                for (const minutes of gapsInMinutes) {
                    redis.advance(minutes * 60)
                    outcomes.push(...(await run(engine, withHandle('minted-1', true), [replayQuery])))
                }
                expect(outcomes.filter(Boolean)).toEqual(['test-rule:shown'])
            })

            it('gives a second conversation its own notice once it echoes its handle', async () => {
                const engine = new GuidanceEngine(makeGuidanceRedis(), [firstMatchRule])
                await run(engine, withHandle('minted-1', false), [replayQuery])
                await expect(run(engine, withHandle('minted-2', false), [replayQuery])).resolves.toEqual([undefined])
                await expect(run(engine, withHandle('minted-2', true), [replayQuery, replayQuery])).resolves.toEqual([
                    'test-rule:shown',
                    undefined,
                ])
            })

            it('does not repeat in the conversation that already got the notice from the caller counters', async () => {
                const engine = new GuidanceEngine(makeGuidanceRedis(), [firstMatchRule])
                await run(engine, withHandle('minted-1', false), [replayQuery])
                await run(engine, withHandle('minted-2', false), [replayQuery])
                await expect(run(engine, withHandle('minted-1', true), [replayQuery])).resolves.toEqual([undefined])
            })

            it('caps a client that never echoes under the caller', async () => {
                const engine = new GuidanceEngine(makeGuidanceRedis(), [firstMatchRule])
                await run(engine, withHandle('minted-1', false), [replayQuery])
                await expect(run(engine, withHandle('minted-2', false), [replayQuery])).resolves.toEqual([undefined])
            })
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
        ['Claude artifact page', { clientProfile: new MCPClientProfile({ vendorClient: 'ClaudeArtifacts' }) }],
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

    it.each([
        ['an empty result', true, true],
        ['a populated result', false, false],
        ['a result of unknown size', undefined, false],
    ])('a resultEmpty rule handles %s', (_label, resultEmpty, expected) => {
        const emptyRule: GuidanceRule = {
            ...rule,
            trigger: { tool: 'execute-sql', resultEmpty: true, outcome: 'any', presets: ['user'] },
        }
        expect(triggerMatches(emptyRule, { ...otherQuery, resultEmpty })).toBe(expected)
    })

    describe('a rule with a condition', () => {
        const conditionalRule = (condition: GuidanceRule['condition']): GuidanceRule => ({
            ...rule,
            threshold: 1,
            condition,
        })

        it('does not spend the session cap on a call the condition rejects', async () => {
            const condition = vi.fn().mockResolvedValueOnce(false).mockResolvedValue(true)
            const engine = new GuidanceEngine(makeGuidanceRedis(), [conditionalRule(condition)])
            await expect(run(engine, makeState(), [replayQuery, replayQuery])).resolves.toEqual([
                undefined,
                'test-rule:shown',
            ])
        })

        it('skips the condition once the rule reaches its cap and keeps its counters alive', async () => {
            const condition = vi.fn().mockResolvedValue(true)
            const redis = makeGuidanceRedis()
            const engine = new GuidanceEngine(redis, [conditionalRule(condition)])
            await run(engine, makeState(), [replayQuery, replayQuery])
            expect(condition).toHaveBeenCalledTimes(1)
            expect(redis.evalCalls.at(-1)?.[6]).toBe('touch')
        })

        it('counts an admitted match when an earlier rule wins the call', async () => {
            const first: GuidanceRule = { ...conditionalRule(vi.fn().mockResolvedValue(true)), id: 'first-rule' }
            const second: GuidanceRule = {
                ...conditionalRule(vi.fn().mockResolvedValue(true)),
                id: 'second-rule',
                threshold: 2,
            }
            const engine = new GuidanceEngine(makeGuidanceRedis(), [first, second])
            await expect(run(engine, makeState(), [replayQuery, replayQuery])).resolves.toEqual([
                'first-rule:shown',
                'second-rule:shown',
            ])
        })

        it('reserves no notice when the gate finishes after the budget', async () => {
            vi.useFakeTimers()
            try {
                const redis = makeGuidanceRedis()
                const evaluateScript = redis.eval.bind(redis)
                const lateEval = vi.spyOn(redis, 'eval').mockImplementation(async (script, keys, ...args) => {
                    await new Promise((resolve) => setTimeout(resolve, 400))
                    return evaluateScript(script, keys, ...args)
                })
                const engine = new GuidanceEngine(redis, [conditionalRule(vi.fn().mockResolvedValue(true))])
                const pending = engine.evaluate(makeState(), replayQuery)
                await vi.advanceTimersByTimeAsync(1000)
                await expect(pending).resolves.toBeUndefined()
                expect(lateEval.mock.calls.map((call) => call[8])).toEqual(['touch'])
            } finally {
                vi.useRealTimers()
            }
        })

        it.each(['touch', 'match'])('holds the tool result to the budget when Redis stalls on %s', async (stalled) => {
            vi.useFakeTimers()
            try {
                const redis = makeGuidanceRedis()
                vi.spyOn(redis, 'eval').mockImplementation((_script, _keys, ...args) =>
                    args[6] === 'touch' && stalled === 'match' ? Promise.resolve(0) : new Promise(() => {})
                )
                const admitted = (id: string): GuidanceRule => ({
                    ...conditionalRule(vi.fn().mockResolvedValue(true)),
                    id,
                })
                const engine = new GuidanceEngine(redis, [admitted('a'), admitted('b'), admitted('c')])
                const pending = engine.evaluate(makeState(), replayQuery)
                await vi.advanceTimersByTimeAsync(310)
                await expect(pending).resolves.toBeUndefined()
            } finally {
                vi.useRealTimers()
            }
        })

        it('applies the condition to a caller with the flag off', async () => {
            const condition = vi.fn().mockResolvedValueOnce(false).mockResolvedValue(true)
            const engine = new GuidanceEngine(makeGuidanceRedis(), [conditionalRule(condition)])
            const state = makeState({ toolFeatureFlags: {} })
            await expect(run(engine, state, [replayQuery, replayQuery])).resolves.toEqual([
                undefined,
                'test-rule:flag_off',
            ])
        })

        it('records suppression without reading the condition', async () => {
            const condition = vi.fn().mockResolvedValue(true)
            const engine = new GuidanceEngine(makeGuidanceRedis(), [conditionalRule(condition)])
            await expect(run(engine, makeState(), [visionCall, replayQuery])).resolves.toEqual([
                undefined,
                'test-rule:suppressed',
            ])
            expect(condition).toHaveBeenCalledTimes(1)
        })
    })

    it('builds function text from the call, only when the notice is shown', async () => {
        const text = vi.fn((call: GuidanceCall) => `Used ${call.toolName}.`)
        const engine = new GuidanceEngine(makeGuidanceRedis(), [{ ...rule, threshold: 1, text }])
        await expect(engine.evaluate(makeState({ toolFeatureFlags: {} }), replayQuery)).resolves.toEqual({
            ruleId: 'test-rule',
            outcome: 'flag_off',
        })
        expect(text).not.toHaveBeenCalled()
        const shown = await new GuidanceEngine(makeGuidanceRedis(), [{ ...rule, threshold: 1, text }]).evaluate(
            makeState(),
            replayQuery
        )
        expect(shown?.text).toBe('Used execute-sql.')
    })

    it('shows each result notice once per session while new notices from the source still show', async () => {
        const noticeRule: GuidanceRule = {
            ...rule,
            trigger: { noticeSource: 'warehouse', outcome: 'success', presets: ['user'] },
            threshold: 1,
            maxPerSession: 5,
            text: (call) => (call.resultNotices ?? []).map((notice) => notice.text).join(' | '),
        }
        const withNotices = (...keys: string[]): GuidanceCall => ({
            ...otherQuery,
            resultNotices: [
                ...keys.map((key) => ({ source: 'warehouse', key, text: `note ${key}` })),
                { source: 'elsewhere', key: 'x', text: 'not mine' },
            ],
        })
        const engine = new GuidanceEngine(makeGuidanceRedis(), [noticeRule])
        const state = makeState({ toolFeatureFlags: { [noticeRule.flag]: true } })
        const texts = []
        for (const call of [withNotices('a'), withNotices('a'), withNotices('a', 'b'), otherQuery]) {
            texts.push((await engine.evaluate(state, call))?.text)
        }
        expect(texts).toEqual(['note a', undefined, 'note b', undefined])
    })

    it('shows nothing and logs when Redis fails', async () => {
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
        const engine = new GuidanceEngine(makeGuidanceRedis(true), [{ ...rule, threshold: 1 }])
        await expect(engine.evaluate(makeState(), replayQuery)).resolves.toBeUndefined()
        expect(warn).toHaveBeenCalledWith('[Guidance] evaluation failed:', expect.any(String))
        warn.mockRestore()
    })

    it.each([
        ['replay-sql-to-vision', 'select 1 from session_replay_events', true],
        ['replay-sql-to-vision', 'select 1 from raw_session_replay_events', true],
        ['replay-sql-to-vision', 'select 1 from session_replay_features', true],
        ['replay-sql-to-vision', 'select 1 from console_logs_log_entries', true],
        ['replay-sql-to-vision', 'select 1 from system.session_recordings', true],
        ['replay-sql-to-vision', 'select 1 from log_entries', false],
        ['replay-sql-to-vision', 'select 1 from batch_export_log_entries', false],
        ['replay-sql-to-vision', 'select 1 from sessions', false],
        ['replay-sql-to-vision', 'select 1 from events', false],
        [
            'sql-aggregate-to-typed-runner',
            "SELECT toDate(timestamp) AS day, count() FROM events WHERE event = 'signup' GROUP BY day",
            true,
        ],
        ['sql-aggregate-to-typed-runner', 'select properties.$browser, uniq(person_id)\nfrom events\ngroup by 1', true],
        ['sql-aggregate-to-typed-runner', "SELECT countIf(event = 'a') FROM events", true],
        ['sql-aggregate-to-typed-runner', 'SELECT event, timestamp FROM events LIMIT 10', false],
        ['sql-aggregate-to-typed-runner', 'SELECT count() FROM events e JOIN persons p ON e.person_id = p.id', false],
        ['sql-aggregate-to-typed-runner', 'WITH x AS (SELECT 1) SELECT count() FROM events', false],
        ['sql-aggregate-to-typed-runner', 'SELECT count() OVER (PARTITION BY event) FROM events', false],
        ['sql-aggregate-to-typed-runner', 'SELECT count() FROM (SELECT person_id FROM events)', false],
        [
            'sql-aggregate-to-typed-runner',
            'SELECT count() FROM events WHERE person_id IN (SELECT id FROM persons)',
            false,
        ],
        [
            'sql-aggregate-to-typed-runner',
            'SELECT event, count(), max(timestamp) AS last_seen FROM events GROUP BY event',
            true,
        ],
        [
            'sql-aggregate-to-typed-runner',
            'SELECT event, uniq(person_id) FROM events GROUP BY event ORDER BY uniq(person_id) DESC',
            true,
        ],
        ['sql-aggregate-to-typed-runner', "SELECT max(timestamp), count() FROM events WHERE event = 'a'", false],
        ['sql-aggregate-to-typed-runner', 'SELECT person_id, count() FROM events GROUP BY person_id', false],
        ['sql-aggregate-to-typed-runner', 'SELECT uniq(person_id), groupArray(event) FROM events', false],
        ['sql-aggregate-to-typed-runner', "SELECT count(), avg(dateDiff('hour', timestamp, now())) FROM events", false],
        [
            'sql-aggregate-to-typed-runner',
            'SELECT event, count() FROM events GROUP BY event HAVING count() > 10',
            false,
        ],
        ['sql-aggregate-to-typed-runner', 'SELECT count() FROM events e, persons p WHERE e.person_id = p.id', false],
        ['sql-aggregate-to-typed-runner', 'SELECT person_id, count() FROM events GROUP BY 1', false],
        [
            'sql-aggregate-to-typed-runner',
            'SELECT properties.$session_id AS sid, count() FROM events GROUP BY sid',
            false,
        ],
        ['sql-aggregate-to-typed-runner', 'SELECT count(), max(e.timestamp) FROM events e', false],
        ['sql-aggregate-to-typed-runner', 'SELECT count() FROM system.insights', false],
        ['sql-aggregate-to-typed-runner', 'SELECT count() FROM posthog.ai_events', false],
        ['sql-aggregate-to-typed-runner', 'SELECT count() FROM events_archive', false],
    ])('the %s rule matches %j: %s', (ruleId, query, expected) => {
        const rule = GUIDANCE_RULES.find((r) => r.id === ruleId)!
        const call: GuidanceCall = { toolName: 'execute-sql', args: { query }, isError: false }
        expect(triggerMatches(rule, call)).toBe(expected)
    })

    it.each([
        ['a direct warehouse connection', { query: 'SELECT count() FROM events', connectionId: 'conn-1' }],
        ['a query longer than the cap', { query: `SELECT count() FROM events /* ${'x'.repeat(5000)} */` }],
    ])('the sql-aggregate-to-typed-runner rule skips %s', (_label, args) => {
        const rule = GUIDANCE_RULES.find((r) => r.id === 'sql-aggregate-to-typed-runner')!
        expect(triggerMatches(rule, { toolName: 'execute-sql', args, isError: false })).toBe(false)
    })

    it('ships every rule with a distinct id and flag', () => {
        expect(new Set(GUIDANCE_RULES.map((r) => r.id)).size).toBe(GUIDANCE_RULES.length)
        expect(new Set(GUIDANCE_RULES.map((r) => r.flag)).size).toBe(GUIDANCE_RULES.length)
    })
})

describe('Self-driving activation guidance', () => {
    const issueCall: GuidanceCall = {
        toolName: 'query-error-tracking-issue',
        args: { issueId: '019a0000-0000-7000-8000-000000000001' },
        isError: false,
    }

    const listCall: GuidanceCall = { toolName: 'query-error-tracking-issues-list', args: {}, isError: false }

    function activationState(overrides: Partial<ResolvedState> = {}): ResolvedState {
        const state = makeToolExecutorState(
            [
                'self-driving-status-get',
                'inbox-reports-list',
                'inbox-reports-retrieve',
                'inbox-report-artefacts-list',
            ].map((name) => ({ name })),
            {
                suppressAnalytics: false,
                aiConsentGiven: true,
                carriedContextHandle: true,
                carriedContextSessionKey: 'sess-1',
                toolFeatureFlags: { [MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG]: true },
                ...overrides,
            }
        )
        state.context.api = new ApiClient({
            apiToken: 'synthetic-credential',
            baseUrl: 'https://api.example.com',
            publicBaseUrl: 'https://example.com',
        })
        state.context.api.request = vi.fn().mockResolvedValue({ completed_at: null, draft: null })
        state.context.stateManager.getProjectId = vi.fn().mockResolvedValue('2')
        return state
    }

    afterEach(() => {
        vi.restoreAllMocks()
        vi.useRealTimers()
    })

    it.each([
        [issueCall, true, false],
        [issueCall, true, true],
        [issueCall, true, undefined],
        [issueCall, false, true],
        [listCall, true, false],
        [listCall, true, true],
        [listCall, false, true],
    ] as const)(
        'records exposure for %j with experiment flag %s and GitHub-optional setup %s',
        async (call, enabled, githubOptional) => {
            const state = activationState({
                toolFeatureFlags: { [MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG]: enabled },
            })
            vi.mocked(state.context.api.request).mockResolvedValue({
                completed_at: null,
                draft: null,
                github_optional_available: githubOptional,
            })
            const notice = await new GuidanceEngine(makeGuidanceRedis()).evaluate(state, call)

            expect(notice).toMatchObject({
                ruleId: 'error-tracking-sd-activation',
                outcome: enabled ? 'shown' : 'flag_off',
            })
            expect(notice?.text).toEqual(
                enabled ? expect.stringContaining('https://example.com/project/2/inbox/activate') : undefined
            )
            if (enabled) {
                expect(notice?.text).toContain(
                    'poll `self-driving-status-get` for the same project every 10 seconds for up to five minutes'
                )
                expect(notice?.text).toContain('Continue helping with the current task')
                expect(notice?.text?.includes('https://example.com/project/2/inbox/activate/without-github')).toBe(
                    githubOptional === true
                )
                expect(notice?.text).not.toContain('api.example.com')
                expect(notice?.text).not.toContain('self-driving-activate')
            }
            expect(state.context.api.request).toHaveBeenCalledWith({
                method: 'GET',
                path: '/api/projects/2/signals/onboarding/',
                signal: expect.any(AbortSignal),
            })
        }
    )

    it.each([
        [true, 'error-tracking-sd-activation:shown'],
        [false, 'empty-hint:shown'],
    ])(
        'lets an empty-result hint fire when the activation flag is %s only if activation sends no text',
        async (enabled, expected) => {
            const emptyHint: GuidanceRule = {
                id: 'empty-hint',
                flag: 'mcp-guidance-empty-hint',
                trigger: { tool: listCall.toolName, resultEmpty: true, outcome: 'success', presets: ['user'] },
                threshold: 1,
                maxPerSession: 1,
                suppressIfCalled: [],
                requiresTool: [listCall.toolName],
                text: 'Loosen the filters.',
            }
            const state = activationState({
                allTools: [
                    'self-driving-status-get',
                    'inbox-reports-list',
                    'inbox-reports-retrieve',
                    'inbox-report-artefacts-list',
                    listCall.toolName,
                ].map((name) => ({ name })) as ResolvedState['allTools'],
                toolFeatureFlags: { [MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG]: enabled, [emptyHint.flag]: true },
            })
            const engine = new GuidanceEngine(makeGuidanceRedis(), [emptyHint])
            await expect(run(engine, state, [{ ...listCall, resultEmpty: true }])).resolves.toEqual([expected])
        }
    )

    it.each([
        ['impersonation', { isImpersonated: true }],
        ['analytics suppression', { suppressAnalytics: true }],
        ['a task-bound request', { isTaskBound: true }],
        ['a sandbox task', { sandboxTaskId: 'synthetic-task' }],
        ['an internal token', { apiKeyScopes: ['internal_run:read'] }],
        ['a scout token', { apiKeyScopes: ['signal_scout_internal:write'] }],
        ['missing consent', { aiConsentGiven: false }],
        ['unknown consent', { aiConsentGiven: undefined }],
        ['an unavailable experiment flag', { toolFeatureFlags: {} }],
        ['unavailable reports tools', { allTools: [] }],
        ['a first-party assistant', { oauthClientId: 'N6UgOECSl98ag1xajxPphGApQXYEVvJIwzCXotKu' }],
        ['a first-party app that declares no consumer', { oauthClientId: 'HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W' }],
    ] satisfies [string, Partial<ResolvedState>][])('does not fetch readiness for %s', async (_label, overrides) => {
        const state = activationState(overrides)
        expect(await new GuidanceEngine(makeGuidanceRedis()).evaluate(state, issueCall)).toBeUndefined()
        expect(state.context.api.request).not.toHaveBeenCalled()
    })

    it.each([
        { ...issueCall, isError: true },
        { ...listCall, isError: true },
        { ...issueCall, toolName: 'query-error-tracking-issue-events' },
        { ...issueCall, args: {} },
    ])('does not fetch readiness outside a successful issue list or detail: %j', async (call) => {
        const state = activationState()
        expect(await new GuidanceEngine(makeGuidanceRedis()).evaluate(state, call)).toBeUndefined()
        expect(state.context.api.request).not.toHaveBeenCalled()
    })

    it.each([
        { completed_at: '2026-01-01T00:00:00Z', draft: null },
        { completed_at: null, draft: { setup_mode: 'guided' } },
    ])('briefly caches existing setup without consuming the session allowance: %j', async (preview) => {
        vi.useFakeTimers({ toFake: ['Date'] })
        const state = activationState()
        vi.mocked(state.context.api.request).mockResolvedValueOnce(preview)
        const engine = new GuidanceEngine(makeGuidanceRedis())
        expect(await engine.evaluate(state, issueCall)).toBeUndefined()
        expect(await engine.evaluate(state, issueCall)).toBeUndefined()
        vi.advanceTimersByTime(29_999)
        expect(await engine.evaluate(state, issueCall)).toBeUndefined()
        expect(state.context.api.request).toHaveBeenCalledTimes(1)
        vi.advanceTimersByTime(1)
        expect(await engine.evaluate(state, issueCall)).toMatchObject({ outcome: 'shown' })
        expect(state.context.api.request).toHaveBeenCalledTimes(2)
    })

    it.each([
        [
            'project',
            (state: ResolvedState) => vi.mocked(state.context.stateManager.getProjectId).mockResolvedValue('3'),
        ],
        ['caller', (state: ResolvedState) => (state.distinctId = 'another-user')],
        ['credential', (state: ResolvedState) => (state.context.api.config.apiToken = 'another-synthetic-credential')],
        ['permissions', (state: ResolvedState) => (state.apiKeyScopes = ['task:read'])],
        ['region', (state: ResolvedState) => (state.context.api.config.baseUrl = 'https://other.example.com')],
    ] satisfies [string, (state: ResolvedState) => unknown][])(
        'does not share negative readiness across a different %s',
        async (_label, change) => {
            const engine = new GuidanceEngine(makeGuidanceRedis())
            const blocked = activationState()
            vi.mocked(blocked.context.api.request).mockResolvedValue({ completed_at: null, draft: {} })
            expect(await engine.evaluate(blocked, issueCall)).toBeUndefined()

            const eligible = activationState()
            change(eligible)
            expect(await engine.evaluate(eligible, issueCall)).toMatchObject({ outcome: 'shown' })
        }
    )

    it.each([
        undefined,
        {},
        { completed_at: null },
        { completed_at: null, draft: null, github_optional_available: 'true' },
    ])('does not cache malformed readiness: %j', async (preview) => {
        const state = activationState()
        vi.mocked(state.context.api.request).mockResolvedValueOnce(preview)
        const engine = new GuidanceEngine(makeGuidanceRedis())
        expect(await engine.evaluate(state, issueCall)).toBeUndefined()
        expect(await engine.evaluate(state, issueCall)).toMatchObject({ outcome: 'shown' })
    })

    it('offers once across list/detail tools and projects, reserving concurrent eligible calls atomically', async () => {
        const state = activationState()
        const engine = new GuidanceEngine(makeGuidanceRedis())
        const notices = await Promise.all([engine.evaluate(state, listCall), engine.evaluate(state, issueCall)])
        expect(notices.filter(Boolean)).toHaveLength(1)
        const otherProject = activationState()
        vi.mocked(otherProject.context.stateManager.getProjectId).mockResolvedValue('3')
        expect(await engine.evaluate(otherProject, listCall)).toBeUndefined()
        expect(otherProject.context.api.request).not.toHaveBeenCalled()
    })

    it.each([{ carriedContextSessionKey: 'sess-2' }, { distinctId: 'another-user' }])(
        'keeps different users and sessions separate: %j',
        async (overrides) => {
            const engine = new GuidanceEngine(makeGuidanceRedis())
            await engine.evaluate(activationState(), issueCall)
            expect(await engine.evaluate(activationState(overrides), issueCall)).toMatchObject({ outcome: 'shown' })
        }
    )

    it('caps handleless calls and retains suppression when a minted handle is later echoed', async () => {
        const engine = new GuidanceEngine(makeGuidanceRedis())
        const state = activationState({ carriedContextHandle: false, carriedContextSessionKey: undefined })
        state.requestContext = {
            ...state.requestContext,
            mcpSessionId: undefined,
            sessionId: 'wrapper-only',
            mcpConversationId: 'minted-1',
        }
        expect(await engine.evaluate(state, issueCall)).toMatchObject({ outcome: 'shown' })
        state.requestContext.mcpConversationId = 'minted-2'
        expect(await engine.evaluate(state, issueCall)).toBeUndefined()
        expect(state.context.api.request).toHaveBeenCalledTimes(1)
        state.carriedContextHandle = true
        state.carriedContextSessionKey = 'minted-1'
        expect(await engine.evaluate(state, issueCall)).toBeUndefined()
        state.carriedContextSessionKey = 'minted-2'
        expect(await engine.evaluate(state, issueCall)).toMatchObject({ outcome: 'shown' })
        expect(await engine.evaluate(state, issueCall)).toBeUndefined()
        expect(state.context.api.request).toHaveBeenCalledTimes(2)
    })

    it('refreshes the handleless caller cap until thirty minutes of inactivity', async () => {
        const redis = makeGuidanceRedis()
        const engine = new GuidanceEngine(redis)
        const state = activationState({ carriedContextHandle: false, carriedContextSessionKey: undefined })
        expect(await engine.evaluate(state, issueCall)).toMatchObject({ outcome: 'shown' })
        redis.advance(1799)
        expect(await engine.evaluate(state, listCall)).toBeUndefined()
        redis.advance(1799)
        expect(await engine.evaluate(state, issueCall)).toBeUndefined()
        redis.advance(1801)
        expect(await engine.evaluate(state, listCall)).toMatchObject({ outcome: 'shown' })
    })

    it.each(['readiness', 'redis'])('silently leaves the tool result alone after %s fails', async (failure) => {
        vi.spyOn(console, 'warn').mockImplementation(() => {})
        const state = activationState()
        if (failure === 'readiness') {
            vi.mocked(state.context.api.request).mockRejectedValueOnce(new Error('readiness unavailable'))
        }
        const engine = new GuidanceEngine(makeGuidanceRedis(failure === 'redis'))
        expect(await engine.evaluate(state, issueCall)).toBeUndefined()
        if (failure === 'readiness') {
            expect(await engine.evaluate(state, issueCall)).toMatchObject({ outcome: 'shown' })
        }
    })

    it.each([
        ['redis', true],
        ['project', true],
        ['readiness', true],
        ['reservation', true],
        ['mirror', true],
        ['redis', false],
        ['project', false],
        ['readiness', false],
        ['reservation', false],
        ['mirror', false],
    ] as const)('bounds a slow %s lookup with flag %s without consuming the allowance', async (phase, enabled) => {
        vi.useFakeTimers()
        const state = activationState({
            toolFeatureFlags: { [MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG]: enabled },
        })
        const redis = makeGuidanceRedis()
        let release!: () => void
        const stalled = new Promise<void>((resolve) => {
            release = resolve
        })
        if (phase === 'redis') {
            vi.spyOn(redis, 'get').mockImplementationOnce(async () => {
                await stalled
                return null
            })
        } else if (phase === 'project') {
            vi.mocked(state.context.stateManager.getProjectId).mockImplementationOnce(async () => {
                await stalled
                return '2'
            })
        } else if (phase === 'readiness') {
            vi.mocked(state.context.api.request).mockImplementationOnce(async () => {
                await stalled
                return { completed_at: null, draft: null }
            })
        } else {
            if (phase === 'mirror') {
                state.carriedContextHandle = false
                state.carriedContextSessionKey = undefined
                state.requestContext.mcpConversationId = 'minted-deadline'
            }
            const set = redis.set
            let writes = 0
            vi.spyOn(redis, 'set').mockImplementation(async (...args) => {
                const result = await set(...args)
                if (++writes === (phase === 'reservation' ? 1 : 2)) {
                    await stalled
                }
                return result
            })
        }
        const engine = new GuidanceEngine(redis)
        const pending = engine.evaluate(state, issueCall)
        await vi.advanceTimersByTimeAsync(300)
        expect(await pending).toBeUndefined()
        release()
        await vi.advanceTimersByTimeAsync(0)
        expect(redis.store.size).toBe(0)
        expect(await engine.evaluate(state, issueCall)).toMatchObject({ outcome: enabled ? 'shown' : 'flag_off' })
    })
})
