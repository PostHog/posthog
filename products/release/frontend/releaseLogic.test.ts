import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { hogFlowsList } from 'products/workflows/frontend/generated/api'

import { releasesList, releasesPartialUpdate } from './generated/api'
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
jest.mock('products/workflows/frontend/generated/api', () => ({
    hogFlowsList: jest.fn(),
    hogFlowsSendCalendarRetrieve: jest.fn(async () => ({ flows: [] })),
}))
jest.mock('products/early_access_features/frontend/generated/api', () => ({
    earlyAccessFeatureList: jest.fn(async () => EMPTY_PAGE),
    earlyAccessFeatureRetrieve: jest.fn(),
}))

const mockedReleasesList = jest.mocked(releasesList)
const mockedPartialUpdate = jest.mocked(releasesPartialUpdate)
const mockedHogFlowsList = jest.mocked(hogFlowsList)

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

    it.each([
        [
            'links the broadcasts the viewer started and keeps the linked ones',
            [
                ['b1', 1],
                ['b2', 1],
                ['b3', 2],
            ],
            ['b1', 'b2'],
        ],
        ['changes nothing when every broadcast is already linked', [['b1', 1]], null],
        ['ignores broadcasts someone else pointed at the release', [['b3', 2]], null],
    ])('%s', async (_name, started, expected) => {
        userLogic.mount()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, id: 1 })
        const release = {
            id: 'r1',
            name: 'Quiet theme',
            feature_flag_ids: [],
            broadcast_ids: ['b1'],
            broadcasts: [],
            has_hidden_flags: false,
            created_at: '2026-11-01T00:00:00Z',
        }
        mockedReleasesList.mockResolvedValue({ results: [release], count: 1, next: null } as never)
        mockedHogFlowsList.mockResolvedValue({
            results: (started as [string, number][]).map(([id, creator]) => ({ id, created_by: { id: creator } })),
        } as never)
        mockedPartialUpdate.mockReset()
        mockedPartialUpdate.mockImplementation(async (_project, _id, changes) => ({ ...release, ...changes }) as never)
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.RELEASES_AREA], { [FEATURE_FLAGS.RELEASES_AREA]: true })
        const logic = releaseLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.autoLinkBroadcasts('r1')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedHogFlowsList).toHaveBeenCalledWith(expect.any(String), {
            source_record: 'release:r1',
            created_by: MOCK_DEFAULT_USER.uuid,
            limit: 50,
            offset: 0,
        })
        if (expected) {
            expect(mockedPartialUpdate).toHaveBeenCalledWith(expect.any(String), 'r1', { broadcast_ids: expected })
        } else {
            expect(mockedPartialUpdate).not.toHaveBeenCalled()
        }
    })
})
