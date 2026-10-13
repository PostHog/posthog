import { ApiError } from 'lib/api-error'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { cohortsRetrieve } from 'products/cohorts/frontend/generated/api'

import { broadcastWizardLogic } from '../broadcastWizardLogic'
import { broadcastAudienceCohortsLogic } from './broadcastAudienceCohortsLogic'

jest.mock('products/cohorts/frontend/generated/api', () => ({ cohortsRetrieve: jest.fn() }))

const cohort = (isCalculating: boolean): any => ({
    id: 42,
    name: 'Spring sale recipients',
    is_static: true,
    is_calculating: isCalculating,
    errors_calculating: 0,
    count: isCalculating ? null : 2,
})

describe('broadcastAudienceCohortsLogic', () => {
    let audienceSizeRequests: number

    beforeEach(() => {
        audienceSizeRequests = 0
        useMocks({
            post: {
                '/api/projects/:team_id/hog_flows/user_blast_radius/': () => {
                    audienceSizeRequests += 1
                    return [200, { affected: 2, total: 10 }]
                },
            },
        })
        initKeaTests()
    })

    it('keeps a matching cohort through a failed poll and refreshes the audience size when matching ends', async () => {
        jest.useFakeTimers()
        try {
            jest.mocked(cohortsRetrieve)
                .mockResolvedValueOnce(cohort(true))
                .mockRejectedValueOnce(new ApiError('Server error', 500))
                .mockResolvedValueOnce(cohort(false))

            const wizard = broadcastWizardLogic({ id: 'new' })
            wizard.mount()
            wizard.actions.setAudienceProperties([
                { type: PropertyFilterType.Cohort, key: 'id', value: 42, operator: PropertyOperator.In },
            ])
            const logic = broadcastAudienceCohortsLogic({ id: 'new' })
            logic.mount()

            await jest.advanceTimersByTimeAsync(1000)
            expect(logic.values.audienceCohorts[42]).toMatchObject({ isCalculating: true })
            const requestsWhileMatching = audienceSizeRequests

            await jest.advanceTimersByTimeAsync(3500)
            expect(cohortsRetrieve).toHaveBeenCalledTimes(2)
            expect(logic.values.audienceCohorts[42]).toMatchObject({ isCalculating: true })

            await jest.advanceTimersByTimeAsync(3500)
            expect(cohortsRetrieve).toHaveBeenCalledTimes(3)
            expect(logic.values.audienceCohorts[42]).toMatchObject({ isCalculating: false, count: 2 })
            expect(audienceSizeRequests).toBeGreaterThan(requestsWhileMatching)
        } finally {
            jest.useRealTimers()
        }
    })
})
