import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'

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
})
