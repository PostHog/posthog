import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import {
    FirstDataWatch,
    MCPOnboardingSignals,
    mcpAnalyticsOnboardingLogic,
    nextFirstDataWatch,
} from './mcpAnalyticsOnboardingLogic'

jest.mock('lib/api')

const mockApi = api as jest.Mocked<typeof api>

// Signal row shape: [has_initialize, tool_calls_total, tool_calls_7d, first_call_at]
describe('mcpAnalyticsOnboardingLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        jest.clearAllMocks()
        initKeaTests()
    })

    function mountWith(results: unknown[][]): ReturnType<typeof mcpAnalyticsOnboardingLogic.build> {
        jest.spyOn(mockApi, 'query').mockResolvedValue({ results } as any)
        const logic = mcpAnalyticsOnboardingLogic()
        logic.mount()
        return logic
    }

    it('forces a fresh calculation so an ingestion-gap cached [0,0] never sticks', async () => {
        const logic = mountWith([[1, 1, 1, '2026-07-01T00:00:00Z']])
        await expectLogic(logic).toFinishAllListeners()
        // The onboarding poll must bypass the cache (force_blocking). Otherwise a
        // pre-ingestion [0,0] cached during the capture->queryable gap keeps the page
        // on "not onboarded" for a full cache cycle after events actually land.
        expect(mockApi.query).toHaveBeenCalledWith(expect.anything(), { refresh: 'force_blocking' })
    })

    it.each([
        [[[1, 1, 1, '2026-07-01T00:00:00Z']], 'onboarded'],
        [[[1, 0, 0, '1970-01-01T00:00:00Z']], 'connected-no-calls'],
        [[[0, 0, 0, '1970-01-01T00:00:00Z']], 'not-instrumented'],
    ])('maps signal row %j to state %s', async (results, expected) => {
        const logic = mountWith(results)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.onboardingState).toBe(expected)
        expect(logic.values.isOnboarded).toBe(expected === 'onboarded')
    })

    it('treats a stringified "0" as false (no false-positive onboarding)', async () => {
        const logic = mountWith([['0', '0', '0', '1970-01-01T00:00:00Z']])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.onboardingState).toBe('not-instrumented')
    })

    it.each([
        // Below both thresholds: the live-feed activity stage.
        [1, 1, 'activity'],
        [299, 100, 'activity'],
        // Lifetime volume unlocks metrics even with a quiet week.
        [300, 0, 'metrics'],
        // Sustained density unlocks metrics even with low lifetime volume.
        [260, 250, 'metrics'],
    ])('stages %i lifetime / %i weekly calls as %s', async (total, last7d, expected) => {
        const logic = mountWith([[1, total, last7d, '2026-07-01T00:00:00Z']])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.dashboardStage).toBe(expected)
    })

    it('discards the epoch sentinel minIf() returns when there are no tool calls', async () => {
        const logic = mountWith([[1, 0, 0, '1970-01-01T00:00:00Z']])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.signals?.firstCallAt).toBeNull()
    })

    // Guards the connect + mapping into the app-wide setup-status layer: if either
    // breaks, the scene empty-state gate stays on its loading spinner forever.
    it.each([
        [[[1, 1, 1, '2026-07-01T00:00:00Z']], 'has-data'],
        [[[1, 0, 0, '1970-01-01T00:00:00Z']], 'waiting-for-data'],
        [[[0, 0, 0, '1970-01-01T00:00:00Z']], 'needs-setup'],
    ])('pushes signal row %j into productSetupStatusLogic as %s', async (results, expected) => {
        const logic = mountWith(results)
        await expectLogic(logic).toFinishAllListeners()
        const setupLogic = productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS })
        expect(setupLogic.values.status).toBe(expected)
    })

    // Guards the fail-open path: a persistently failing signal query must publish
    // `unknown` (gate renders the scene), not leave the gate on its spinner forever.
    it('publishes unknown when the signal query fails before any answer exists', async () => {
        jest.spyOn(mockApi, 'query').mockRejectedValue(new Error('query failed'))
        const logic = mcpAnalyticsOnboardingLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS }).values.status).toBe('unknown')
    })

    it('a failing poll never downgrades an existing answer', async () => {
        const logic = mountWith([[1, 1, 1, '2026-07-01T00:00:00Z']])
        await expectLogic(logic).toFinishAllListeners()
        jest.spyOn(mockApi, 'query').mockRejectedValue(new Error('query failed'))
        logic.actions.loadSignals()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS }).values.status).toBe('has-data')
    })

    it.each(['success', 'failure'] as const)(
        'ignores a signal query %s from a previous project without completing the new setup attempt',
        async (outcome) => {
            let resolveQuery!: (response: any) => void
            let rejectQuery!: (error: Error) => void
            mockApi.query.mockReturnValueOnce(
                new Promise((resolve, reject) => {
                    resolveQuery = resolve
                    rejectQuery = reject
                })
            )
            const logic = mcpAnalyticsOnboardingLogic()
            logic.mount()
            const setupLogic = productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS })
            teamLogic.actions.loadCurrentTeamSuccess({
                ...teamLogic.values.currentTeam!,
                id: teamLogic.values.currentTeamId! + 1,
                uuid: '00000000-0000-4000-8000-000000000456',
            })
            setupLogic.actions.reportSetupShown('needs-setup')
            const attemptId = setupLogic.values.setupAttempt!.id

            if (outcome === 'success') {
                resolveQuery({ results: [[1, 1, 1, '2026-07-01T00:00:00Z']] })
            } else {
                rejectQuery(new Error('previous project query failed'))
            }
            await expectLogic(logic).toFinishAllListeners()
            expect(setupLogic.values.status).toBe('loading')
            expect(setupLogic.values.setupAttempt).toMatchObject({ id: attemptId, completed: false })

            mockApi.query.mockResolvedValue({ results: [[1, 1, 1, '2026-07-01T00:00:00Z']] } as any)
            await expectLogic(logic, () => logic.actions.loadSignals()).toFinishAllListeners()
            expect(setupLogic.values.setupAttempt).toMatchObject({ id: attemptId, completed: true })
        }
    )

    describe('first data watch', () => {
        const FIRST_DATA_EVENT = 'mcp analytics first data seen live'
        const EPOCH = '1970-01-01T00:00:00Z'
        const FIRST_CALL_AT = '2026-07-01T00:00:00Z'

        const signalsWith = (toolCallsTotal: number, toolCalls7d: number = toolCallsTotal): MCPOnboardingSignals => ({
            hasInitialize: true,
            hasToolCall: toolCallsTotal > 0,
            toolCallsTotal,
            toolCalls7d,
            firstCallAt: toolCallsTotal > 0 ? FIRST_CALL_AT : null,
        })
        const NO_CALLS = signalsWith(0)
        const ONE_CALL = signalsWith(1)
        const BACKFILL_LIFETIME = signalsWith(300, 0)
        const BACKFILL_DENSE_WEEK = signalsWith(260, 250)

        it.each<{
            current: FirstDataWatch
            when: string
            signals: MCPOnboardingSignals | null
            expected: FirstDataWatch
        }>([
            { current: 'unknown', when: 'no answer', signals: null, expected: 'unknown' },
            { current: 'unknown', when: 'no calls', signals: NO_CALLS, expected: 'watching' },
            { current: 'unknown', when: 'one call', signals: ONE_CALL, expected: 'settled' },
            { current: 'watching', when: 'no answer', signals: null, expected: 'watching' },
            { current: 'watching', when: 'no calls', signals: NO_CALLS, expected: 'watching' },
            { current: 'watching', when: 'one call', signals: ONE_CALL, expected: 'arrived' },
            { current: 'watching', when: '300 lifetime calls', signals: BACKFILL_LIFETIME, expected: 'settled' },
            { current: 'watching', when: '250 calls this week', signals: BACKFILL_DENSE_WEEK, expected: 'settled' },
            { current: 'arrived', when: 'no answer', signals: null, expected: 'arrived' },
            { current: 'arrived', when: 'no calls', signals: NO_CALLS, expected: 'arrived' },
            { current: 'arrived', when: '300 lifetime calls', signals: BACKFILL_LIFETIME, expected: 'arrived' },
            { current: 'settled', when: 'no answer', signals: null, expected: 'settled' },
            { current: 'settled', when: 'no calls', signals: NO_CALLS, expected: 'settled' },
            { current: 'settled', when: 'one call', signals: ONE_CALL, expected: 'settled' },
        ])('$current + $when -> $expected', ({ current, signals, expected }) => {
            expect(nextFirstDataWatch(current, signals)).toBe(expected)
        })

        type Row = [has_initialize: number, tool_calls_total: number, tool_calls_7d: number, first_call_at: string]
        const NOT_INSTRUMENTED: Row = [0, 0, 0, EPOCH]
        const CONNECTED: Row = [1, 0, 0, EPOCH]
        const ONE: Row = [1, 1, 1, FIRST_CALL_AT]
        const TWO: Row = [1, 2, 2, FIRST_CALL_AT]
        const BACKFILL: Row = [1, 300, 300, FIRST_CALL_AT]

        let captureSpy: jest.SpyInstance
        beforeEach(() => {
            captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        })
        afterEach(() => {
            captureSpy.mockRestore()
        })

        const firstDataCaptures = (): unknown[][] =>
            captureSpy.mock.calls.filter(([event]) => event === FIRST_DATA_EVENT)

        async function play(
            steps: (Row | 'acknowledge' | 'acknowledge animated')[]
        ): Promise<ReturnType<typeof mcpAnalyticsOnboardingLogic.build>> {
            const query = jest.spyOn(mockApi, 'query').mockReset()
            steps
                .filter((step): step is Row => Array.isArray(step))
                .forEach((row) => {
                    query.mockResolvedValueOnce({ results: [row] } as any)
                })
            const logic = mcpAnalyticsOnboardingLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            for (const step of steps.slice(1)) {
                if (step === 'acknowledge' || step === 'acknowledge animated') {
                    logic.actions.acknowledgeFirstData(step === 'acknowledge animated')
                } else {
                    logic.actions.loadSignals()
                }
                await expectLogic(logic).toFinishAllListeners()
            }
            return logic
        }

        it.each<[string, Parameters<typeof play>[0], FirstDataWatch, number]>([
            [
                'a flip while watching arrives and captures once when acknowledged',
                [NOT_INSTRUMENTED, ONE, 'acknowledge'],
                'settled',
                1,
            ],
            ['a flip from connected-no-calls arrives', [CONNECTED, ONE, 'acknowledge'], 'settled', 1],
            ['an arrival stays armed across polls until acknowledged', [CONNECTED, ONE, TWO, TWO], 'arrived', 0],
            ['a page load with data never arms', [ONE, TWO, 'acknowledge'], 'settled', 0],
            ['a >=300-call backfill settles without arming', [CONNECTED, BACKFILL, 'acknowledge'], 'settled', 0],
            ['later polls never refire after acknowledging', [CONNECTED, ONE, 'acknowledge', TWO, TWO], 'settled', 1],
            ['a double acknowledge captures once', [CONNECTED, ONE, 'acknowledge', 'acknowledge'], 'settled', 1],
        ])('%s', async (_name, steps, expectedWatch, expectedCaptures) => {
            const logic = await play(steps)

            expect(logic.values.firstDataWatch).toBe(expectedWatch)
            expect(firstDataCaptures()).toHaveLength(expectedCaptures)
        })

        it('a failed poll in between still arrives on the next answer', async () => {
            jest.spyOn(mockApi, 'query')
                .mockReset()
                .mockResolvedValueOnce({ results: [CONNECTED] } as any)
                .mockRejectedValueOnce(new Error('query failed'))
                .mockResolvedValueOnce({ results: [ONE] } as any)
            const logic = mcpAnalyticsOnboardingLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.loadSignals()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.loadSignals()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.firstDataWatch).toBe('arrived')
        })

        it.each([true, false])('captures the live arrival with animated=%s', async (animated) => {
            jest.useFakeTimers({
                now: new Date('2026-07-01T00:01:30Z'),
                doNotFake: [
                    'setTimeout',
                    'clearTimeout',
                    'setInterval',
                    'clearInterval',
                    'setImmediate',
                    'clearImmediate',
                    'nextTick',
                    'queueMicrotask',
                    'performance',
                    'requestAnimationFrame',
                    'cancelAnimationFrame',
                    'requestIdleCallback',
                    'cancelIdleCallback',
                    'hrtime',
                ],
            })
            try {
                await play([CONNECTED, ONE, animated ? 'acknowledge animated' : 'acknowledge'])
            } finally {
                jest.useRealTimers()
            }

            expect(captureSpy).toHaveBeenCalledWith(
                FIRST_DATA_EVENT,
                { tool_calls_total: 1, seconds_since_first_call: 90, animated },
                undefined
            )
        })

        it('settles without capturing during an impersonated session', async () => {
            userLogic.actions.loadUserSuccess({ ...userLogic.values.user!, is_impersonated: true })

            const logic = await play([CONNECTED, ONE, 'acknowledge'])

            expect(logic.values.firstDataWatch).toBe('settled')
            expect(firstDataCaptures()).toHaveLength(0)
        })
    })
})
