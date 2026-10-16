import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { recommendationsTabLogic } from './recommendationsTabLogic'
import type { ErrorTrackingRecommendation } from './types'

const computingRecommendation: ErrorTrackingRecommendation = {
    id: 'lens-id',
    type: 'quick_leave',
    meta: {},
    completed: false,
    status: 'computing',
    computed_at: null,
    dismissed_at: null,
    created_at: '2026-10-14T10:00:00Z',
    updated_at: '2026-10-14T10:00:00Z',
}

describe('recommendationsTabLogic', () => {
    let logic: ReturnType<typeof recommendationsTabLogic.build>
    let list: jest.SpyInstance

    beforeEach(async () => {
        jest.useFakeTimers()
        initKeaTests()
        list = jest
            .spyOn(api.errorTracking, 'listRecommendations')
            .mockResolvedValue({ results: [computingRecommendation] })
        logic = recommendationsTabLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['setRecommendations'])
        list.mockClear()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it('backs off polling while a recommendation keeps computing, and restarts it for a new compute', async () => {
        // Polls at 0.5 s, then 1 s, 2 s and 4 s later, and then every 5 s.
        for (const [delayMs, polls] of [
            [500, 1],
            [1000, 2],
            [2000, 3],
            [4000, 4],
            [5000, 5],
            [5000, 6],
        ]) {
            await jest.advanceTimersByTimeAsync(delayMs - 1)
            expect(list).toHaveBeenCalledTimes(polls - 1)
            await jest.advanceTimersByTimeAsync(1)
            expect(list).toHaveBeenCalledTimes(polls)
        }

        logic.actions.markRecommendationComputing(computingRecommendation.id)
        await jest.advanceTimersByTimeAsync(500)
        expect(list).toHaveBeenCalledTimes(7)
    })
})
