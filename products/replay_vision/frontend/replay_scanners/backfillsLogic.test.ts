import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { BackfillEstimateResponseApi } from '../generated/api.schemas'
import { backfillsLogic } from './backfillsLogic'

const ESTIMATE: BackfillEstimateResponseApi = {
    total_sessions: 40,
    total_credits: 400,
    credits_per_observation: 10,
    credits_remaining: 1000,
    window_start: '2026-01-01T00:00:00Z',
    window_end: '2026-02-01T00:00:00Z',
}

describe('backfillsLogic', () => {
    let logic: ReturnType<typeof backfillsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/:id/backfills/': { results: [], count: 0 },
            },
        })
        initKeaTests()
        logic = backfillsLogic({ scannerId: 'sid' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('keeps the last estimate and records the error when a request fails', async () => {
        await expectLogic(logic, () => {
            logic.actions.requestEstimateSuccess(ESTIMATE)
        }).toMatchValues({ estimate: ESTIMATE, estimateError: null })

        // The card must not blank on a transient failure: the estimate stays put, the error is what changes.
        await expectLogic(logic, () => {
            logic.actions.requestEstimateFailure('The scanner is busy.')
        }).toMatchValues({ estimate: ESTIMATE, estimateError: 'The scanner is busy.' })
    })

    it('holds the last estimate while a fresh request is in flight and remembers its window', async () => {
        logic.actions.requestEstimateSuccess(ESTIMATE)
        logic.actions.requestEstimateFailure('busy')

        await expectLogic(logic, () => {
            logic.actions.requestEstimate('2026-03-01T00:00:00Z', '2026-04-01T00:00:00Z')
        }).toMatchValues({
            estimate: ESTIMATE,
            estimateError: null,
            estimateLoading: true,
            lastRequestedWindow: { windowStart: '2026-03-01T00:00:00Z', windowEnd: '2026-04-01T00:00:00Z' },
        })
    })

    it('retries the estimate for the last requested window', async () => {
        logic.actions.requestEstimate('2026-05-01T00:00:00Z', '2026-06-01T00:00:00Z')

        await expectLogic(logic, () => {
            logic.actions.retryEstimate()
        }).toDispatchActions([logic.actionCreators.requestEstimate('2026-05-01T00:00:00Z', '2026-06-01T00:00:00Z')])
    })
})
