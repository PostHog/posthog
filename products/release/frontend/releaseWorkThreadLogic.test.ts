import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import posthog from 'lib/posthog-typed'

import { initKeaTests } from '~/test/init'

import { todayWorkThreadsRetrieve } from 'products/today/frontend/generated/api'
import type { WorkThreadApi } from 'products/today/frontend/generated/api.schemas'

import { releaseLogic } from './releaseLogic'
import { releaseWorkThreadLogic } from './releaseWorkThreadLogic'

const EMPTY_PAGE = { results: [], count: 0, next: null }
const RELEASE_ID = '0193a000-0000-7000-8000-000000000001'

jest.mock('products/today/frontend/generated/api', () => ({
    todayWorkThreadsRetrieve: jest.fn(),
}))
jest.mock('./generated/api', () => ({
    releasesList: jest.fn(async () => EMPTY_PAGE),
    releasesCreate: jest.fn(),
    releasesPartialUpdate: jest.fn(),
}))
jest.mock('products/feature_flags/frontend/generated/api', () => ({
    featureFlagsList: jest.fn(async () => EMPTY_PAGE),
    scheduledChangesList: jest.fn(async () => EMPTY_PAGE),
}))
jest.mock('products/experiments/frontend/generated/api', () => ({
    experimentsList: jest.fn(async () => EMPTY_PAGE),
}))
jest.mock('products/early_access_features/frontend/generated/api', () => ({
    earlyAccessFeatureList: jest.fn(async () => EMPTY_PAGE),
}))

const mockedRetrieve = jest.mocked(todayWorkThreadsRetrieve)

function workThread(title: string): WorkThreadApi {
    return {
        key: `release:${RELEASE_ID}`,
        name: 'Quiet theme',
        line: {
            key: `release:${RELEASE_ID}`,
            steps: [
                {
                    key: `release:${RELEASE_ID}:planned`,
                    title,
                    description: 'Not started.',
                    area: 'Release',
                    item: null,
                    facts: [],
                    chosen_label: null,
                    started_from: null,
                    options: [],
                    alongside: [],
                },
            ],
        },
    }
}

describe('releaseWorkThreadLogic', () => {
    let logic: ReturnType<typeof releaseWorkThreadLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockedRetrieve.mockReset()
        mockedRetrieve.mockResolvedValue({ results: [workThread('Planned')] })
        logic = releaseWorkThreadLogic({ releaseId: RELEASE_ID })
    })

    afterEach(() => {
        logic.unmount()
    })

    test('loads the thread of its release from the release work source', async () => {
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadReleaseWorkThreadSuccess'])
            .toMatchValues({
                thread: workThread('Planned'),
                threadLoading: false,
                threadFailed: false,
            })
        expect(mockedRetrieve).toHaveBeenCalledWith(expect.any(String), { source: 'release', ref: RELEASE_ID })
    })

    test('a failed load shows as failed until a retry loads the thread', async () => {
        mockedRetrieve.mockRejectedValueOnce(new Error('Server error'))
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadReleaseWorkThreadFailure'])
            .toMatchValues({ thread: null, threadFailed: true })

        await expectLogic(logic, () => {
            logic.actions.loadReleaseWorkThread()
        }).toDispatchActions(['loadReleaseWorkThreadSuccess'])
        expect(logic.values).toMatchObject({ thread: workThread('Planned'), threadFailed: false })
    })

    test.each([
        ['the flags reload', () => releaseLogic.actions.loadFlagsSuccess([]), true],
        [
            'the server confirms a save of this release',
            () =>
                releaseLogic.actions.setReleaseLocally({
                    id: RELEASE_ID,
                    changes: { survey_ids: [] },
                    broadcasts: [],
                    linked: { surveys: [], insights: [] },
                }),
            true,
        ],
        [
            'a save of this release is only applied optimistically',
            () => releaseLogic.actions.setReleaseLocally({ id: RELEASE_ID, changes: { survey_ids: [] } }),
            false,
        ],
        [
            'the server confirms a save of another release',
            () =>
                releaseLogic.actions.setReleaseLocally({
                    id: 'another-release',
                    changes: { survey_ids: [] },
                    broadcasts: [],
                    linked: { surveys: [], insights: [] },
                }),
            false,
        ],
    ])('whether the thread reloads when %s', async (_name, change, reloads) => {
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadReleaseWorkThreadSuccess'])
        mockedRetrieve.mockResolvedValue({ results: [workThread('Behind a flag')] })

        await expectLogic(logic, change).toFinishAllListeners()

        expect(logic.values.thread).toEqual(workThread(reloads ? 'Behind a flag' : 'Planned'))
    })

    test.each([
        ['schedule_rollout with a flag id opens the schedule dialog', 'schedule_rollout', { flag_id: 5 }, 5, false],
        ['schedule_rollout without a flag id reports the failure', 'schedule_rollout', null, null, true],
        ['an action the page does not know reports the failure', 'archive_flag', { flag_id: 5 }, null, true],
    ])('%s', async (_name, actionId, params, scheduleFlagId, reported) => {
        const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => undefined as never)
        const capture = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.runAction(actionId, params)
        }).toFinishAllListeners()

        expect(releaseLogic.values.scheduleFlagId).toEqual(scheduleFlagId)
        expect(toast).toHaveBeenCalledTimes(reported ? 1 : 0)
        expect(capture).toHaveBeenCalledTimes(reported ? 1 : 0)
        toast.mockRestore()
        capture.mockRestore()
    })
})
