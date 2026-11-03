import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import { GuidanceEngine, triggerMatches, type GuidanceCall } from '@/hono/guidance/engine'
import { GUIDANCE_RULES, MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG, type GuidanceRule } from '@/hono/guidance/rules'
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

    it('offers on every handleless call and retains the cap when a minted handle is later echoed', async () => {
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
        expect(await engine.evaluate(state, issueCall)).toMatchObject({ outcome: 'shown' })
        expect(state.context.api.request).toHaveBeenCalledTimes(2)
        state.carriedContextHandle = true
        state.carriedContextSessionKey = 'minted-2'
        expect(await engine.evaluate(state, issueCall)).toBeUndefined()
        expect(state.context.api.request).toHaveBeenCalledTimes(2)
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

    it('cancels readiness with a one-second overall deadline without consuming the session allowance', async () => {
        vi.spyOn(console, 'warn').mockImplementation(() => {})
        const controller = new AbortController()
        const timeout = vi.spyOn(AbortSignal, 'timeout').mockReturnValue(controller.signal)
        const state = activationState()
        let requestStarted: (() => void) | undefined
        const started = new Promise<void>((resolve) => {
            requestStarted = resolve
        })
        vi.mocked(state.context.api.request).mockImplementationOnce(async ({ signal }) => {
            requestStarted?.()
            return await new Promise<never>((_resolve, reject) =>
                signal?.addEventListener('abort', () => reject(signal.reason))
            )
        })
        const engine = new GuidanceEngine(makeGuidanceRedis())
        const pending = engine.evaluate(state, issueCall)
        await started
        controller.abort(new DOMException('deadline', 'TimeoutError'))
        expect(await pending).toBeUndefined()
        expect(timeout).toHaveBeenCalledWith(1000)
        expect(await engine.evaluate(state, issueCall)).toMatchObject({ outcome: 'shown' })
    })
})
