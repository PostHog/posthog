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

    it.each([1, null])('only requests trial status with a team and the rollout flag (team: %s)', async (teamId) => {
        const logic = selfDrivingTrialLogic({ teamId })
        logic.mount()
        try {
            await jest.advanceTimersByTimeAsync(0)
            await jest.advanceTimersByTimeAsync(60_000)
            expect(mockTrialList).not.toHaveBeenCalled()

            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SELF_DRIVING_UBP]: true })
            await jest.advanceTimersByTimeAsync(0)
            expect(mockTrialList).toHaveBeenCalledTimes(teamId === null ? 0 : 1)

            await jest.advanceTimersByTimeAsync(60_000)
            await jest.advanceTimersByTimeAsync(0)
            expect(mockTrialList).toHaveBeenCalledTimes(teamId === null ? 0 : 2)

            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SELF_DRIVING_UBP]: false })
            await jest.advanceTimersByTimeAsync(120_000)
            await logic.asyncActions.loadTrial()
            expect(mockTrialList).toHaveBeenCalledTimes(teamId === null ? 0 : 2)
            expect(logic.values.trialEnabled).toBe(false)
        } finally {
            logic.unmount()
        }
    })
})
