import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { signalsTrialList } from 'products/signals/frontend/generated/api'

import { selfDrivingTrialLogic } from './selfDrivingTrialLogic'

jest.mock('products/signals/frontend/generated/api', () => ({ signalsTrialList: jest.fn() }))

const mockTrialList = jest.mocked(signalsTrialList)

describe('selfDrivingTrialLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.useFakeTimers()
        mockTrialList.mockReset()
        mockTrialList.mockRejectedValue(new Error('Unavailable'))
    })

    afterEach(() => jest.useRealTimers())

    it('starts and stops trial requests with the rollout flag, including polling after an error', async () => {
        const logic = selfDrivingTrialLogic({ teamId: 1 })
        logic.mount()
        try {
            await jest.advanceTimersByTimeAsync(0)
            await jest.advanceTimersByTimeAsync(60_000)
            expect(mockTrialList).not.toHaveBeenCalled()

            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SELF_DRIVING_UBP]: true })
            await jest.advanceTimersByTimeAsync(0)
            expect(mockTrialList).toHaveBeenCalledTimes(1)

            await jest.advanceTimersByTimeAsync(60_000)
            await jest.advanceTimersByTimeAsync(0)
            expect(mockTrialList).toHaveBeenCalledTimes(2)

            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SELF_DRIVING_UBP]: false })
            await jest.advanceTimersByTimeAsync(120_000)
            await logic.asyncActions.loadTrial()
            expect(mockTrialList).toHaveBeenCalledTimes(2)
            expect(logic.values.trialEnabled).toBe(false)
        } finally {
            logic.unmount()
        }
    })
})
