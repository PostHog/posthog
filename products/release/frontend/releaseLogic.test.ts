import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { releasesList } from './generated/api'
import { releaseLogic } from './releaseLogic'

const EMPTY_PAGE = { results: [], count: 0, next: null }

jest.mock('./generated/api', () => ({
    releasesList: jest.fn(),
    releasesCreate: jest.fn(),
    releasesPartialUpdate: jest.fn(),
}))
jest.mock('products/feature_flags/frontend/generated/api', () => ({
    featureFlagsList: jest.fn(async () => EMPTY_PAGE),
    featureFlagsRetrieve: jest.fn(),
    scheduledChangesList: jest.fn(async () => EMPTY_PAGE),
}))
jest.mock('products/experiments/frontend/generated/api', () => ({
    experimentsList: jest.fn(async () => EMPTY_PAGE),
}))
jest.mock('products/early_access_features/frontend/generated/api', () => ({
    earlyAccessFeatureList: jest.fn(async () => EMPTY_PAGE),
    earlyAccessFeatureRetrieve: jest.fn(),
}))

const mockedReleasesList = jest.mocked(releasesList)

describe('releaseLogic', () => {
    beforeEach(() => {
        initKeaTests()
        mockedReleasesList.mockReset()
        mockedReleasesList.mockResolvedValue(EMPTY_PAGE as never)
        featureFlagLogic.mount()
    })

    it.each([
        ['loads once the flag arrives after mount', true, 1],
        ['loads nothing while the flag is off', false, 0],
    ])('%s', async (_name, enabled, calls) => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        const logic = releaseLogic()
        logic.mount()

        featureFlagLogic.actions.setFeatureFlags(enabled ? [FEATURE_FLAGS.RELEASES_AREA] : [], {
            [FEATURE_FLAGS.RELEASES_AREA]: enabled,
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedReleasesList).toHaveBeenCalledTimes(calls)
    })
})
