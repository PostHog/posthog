import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'

jest.mock('lib/api')

const mockApi = api as jest.Mocked<typeof api>

// Signal row shape: [has_initialize, tool_calls_total, tool_calls_7d, first_call_at]
describe('mcpAnalyticsOnboardingLogic', () => {
    beforeEach(() => {
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
        // Below both thresholds: early.
        [500, 100, 'early'],
        // Lifetime volume graduates even with a quiet week.
        [1000, 0, 'full'],
        // Sustained density graduates even with low lifetime volume.
        [400, 250, 'full'],
        [1, 1, 'early'],
    ])('gates %i lifetime / %i weekly calls to %s mode', async (total, last7d, expected) => {
        const logic = mountWith([[1, total, last7d, '2026-07-01T00:00:00Z']])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.dataMaturity).toBe(expected)
        expect(logic.values.resolvedDashboardMode).toBe(expected)
    })

    it('lets the manual override win over the volume gate', async () => {
        const logic = mountWith([[1, 3, 3, '2026-07-01T00:00:00Z']])
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setDashboardModeOverride('full')
        expect(logic.values.resolvedDashboardMode).toBe('full')
        logic.actions.setDashboardModeOverride(null)
        expect(logic.values.resolvedDashboardMode).toBe('early')
    })

    it('discards the epoch sentinel minIf() returns when there are no tool calls', async () => {
        const logic = mountWith([[1, 0, 0, '1970-01-01T00:00:00Z']])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.signals?.firstCallAt).toBeNull()
    })
})
