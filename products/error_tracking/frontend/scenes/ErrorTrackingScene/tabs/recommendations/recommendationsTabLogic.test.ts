import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { recommendationsTabLogic } from './recommendationsTabLogic'
import { AlertsRecommendation } from './types'

const alertsRecommendation = (): AlertsRecommendation => ({
    id: 'rec-1',
    type: 'alerts',
    meta: {
        alerts: [
            { key: 'error-tracking-issue-created', enabled: false },
            { key: 'error-tracking-issue-reopened', enabled: false },
        ],
    },
    completed: false,
    status: 'ready',
    computed_at: '2026-01-01T00:00:00Z',
    dismissed_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
})

describe('recommendationsTabLogic', () => {
    let logic: ReturnType<typeof recommendationsTabLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/error_tracking/recommendations': { results: [alertsRecommendation()] },
            },
        })
        initKeaTests()
        logic = recommendationsTabLogic()
        logic.mount()
        // Let the on-mount load settle so it can't overwrite the fixture mid-test.
        await expectLogic(logic).toDispatchActions(['setRecommendations'])
    })

    afterEach(() => {
        logic.unmount()
    })

    it('markAlertConfigured flips only the matching alert to enabled without waiting for a recompute', async () => {
        await expectLogic(logic, () => {
            logic.actions.markAlertConfigured('rec-1', 'error-tracking-issue-created')
        }).toFinishListeners()

        const updated = logic.values.recommendations[0] as AlertsRecommendation
        expect(updated.meta.alerts).toEqual([
            { key: 'error-tracking-issue-created', enabled: true },
            { key: 'error-tracking-issue-reopened', enabled: false },
        ])
    })

    it('markAlertConfigured leaves a non-matching recommendation id untouched', async () => {
        await expectLogic(logic, () => {
            logic.actions.markAlertConfigured('other-id', 'error-tracking-issue-created')
        }).toFinishListeners()

        const untouched = logic.values.recommendations[0] as AlertsRecommendation
        expect(untouched.meta.alerts.every((a) => !a.enabled)).toBe(true)
    })
})
