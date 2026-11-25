import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'lib/posthog-typed'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { hogFlowsList } from 'products/workflows/frontend/generated/api'

import { releasesList, releasesPartialUpdate } from './generated/api'
import { releaseLogic } from './releaseLogic'

const EMPTY_PAGE = { results: [], count: 0, next: null }

jest.mock('lib/posthog-typed', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))
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
        ['loads objects without the area', false, true, 1],
        ['loads objects with the area', true, true, 1],
        ['loads no objects for the area alone', true, false, 0],
        ['loads nothing while both flags are off', false, false, 0],
    ])('%s', async (_name, areaEnabled, objectsEnabled, calls) => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        const logic = releaseLogic()
        logic.mount()

        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.RELEASES_AREA]: areaEnabled,
            [FEATURE_FLAGS.RELEASE_OBJECTS]: objectsEnabled,
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedReleasesList).toHaveBeenCalledTimes(calls)
    })

    it('counts a release page open once per page, not per hash change', async () => {
        const capture = jest.mocked(posthog.capture)
        capture.mockClear()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.RELEASE_OBJECTS], {
            [FEATURE_FLAGS.RELEASE_OBJECTS]: true,
        })
        router.actions.push(urls.release('r1'))
        const logic = releaseLogic()
        logic.mount()

        router.actions.push(urls.release('r1'), {}, { panel: 'discussion' })
        router.actions.push(urls.release('r2'))
        await expectLogic(logic).toFinishAllListeners()

        expect(capture.mock.calls.filter(([event]) => event === 'release page opened')).toEqual([
            ['release page opened', { release_id: 'r1' }],
            ['release page opened', { release_id: 'r2' }],
        ])
    })

    it.each([
        ['flags never arrive', [], urls.releaseCalendar(), []],
        [
            'flags arrive while the page is still open',
            [FEATURE_FLAGS.RELEASE_OBJECTS],
            urls.releaseCalendar(),
            ['release calendar opened'],
        ],
        ['flags arrive after the person left the page', [FEATURE_FLAGS.RELEASE_OBJECTS], urls.projectHomepage(), []],
        [
            'the area flag arrives for the view all page',
            [FEATURE_FLAGS.RELEASES_AREA],
            null,
            ['release view all opened'],
        ],
        ['only the objects flag arrives for the view all page', [FEATURE_FLAGS.RELEASE_OBJECTS], null, []],
    ])(
        'counts a page open only when the gate lets the person in: %s',
        async (_name, arrivingFlags, pathWhenFlagsArrive, expected) => {
            const capture = jest.mocked(posthog.capture)
            capture.mockClear()
            featureFlagLogic.actions.setFeatureFlags([], {})
            const opened = pathWhenFlagsArrive === null ? urls.releases() : urls.releaseCalendar()
            router.actions.push(opened)
            const logic = releaseLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            if (pathWhenFlagsArrive && pathWhenFlagsArrive !== opened) {
                router.actions.push(pathWhenFlagsArrive)
            }
            featureFlagLogic.actions.setFeatureFlags(
                arrivingFlags,
                Object.fromEntries(arrivingFlags.map((flag) => [flag, true]))
            )
            await expectLogic(logic).toFinishAllListeners()

            const opens = capture.mock.calls.map((call) => String(call[0])).filter((event) => event.endsWith(' opened'))
            expect(opens).toEqual(expected)
        }
    )

    it.each([
        [
            'names the release page after the release',
            urls.release('r1'),
            [{ key: ['Release', 'r1'], name: 'Quiet theme' }],
        ],
        ['names the list page', urls.releaseList(), [{ key: 'Releases', name: 'Releases' }]],
        ['names the calendar page', urls.releaseCalendar(), [{ key: 'ReleaseCalendar', name: 'Release calendar' }]],
        ['names the view all page', urls.releases(), [{ key: 'ReleaseAll', name: 'View all' }]],
    ])('%s', async (_name, url, expected) => {
        mockedReleasesList.mockResolvedValue({
            results: [
                {
                    id: 'r1',
                    name: 'Quiet theme',
                    feature_flag_ids: [],
                    broadcast_ids: [],
                    broadcasts: [],
                    has_hidden_flags: false,
                    created_at: '2026-11-01T00:00:00Z',
                },
            ],
            count: 1,
            next: null,
        } as never)
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.RELEASE_OBJECTS], {
            [FEATURE_FLAGS.RELEASE_OBJECTS]: true,
        })
        router.actions.push(url)
        const logic = releaseLogic({ id: url === urls.release('r1') ? 'r1' : undefined })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.breadcrumbs).toEqual(expected)
        expect(logic.values.todayRecent).toEqual(
            url === urls.release('r1')
                ? { type: 'release', id: 'r1', name: 'Quiet theme', href: urls.release('r1') }
                : null
        )
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
            true,
            [['release broadcasts auto linked', { release_id: 'r1', count: 1 }]],
        ],
        ['changes nothing when every broadcast is already linked', [['b1', 1]], null, true, []],
        ['ignores broadcasts someone else pointed at the release', [['b3', 2]], null, true, []],
        ['counts no auto link when the save fails', [['b2', 1]], ['b1', 'b2'], false, []],
    ])('%s', async (_name, started, expected, saves, events) => {
        const capture = jest.mocked(posthog.capture)
        capture.mockClear()
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
        mockedPartialUpdate.mockImplementation(async (_project, _id, changes) => {
            if (!saves) {
                throw new Error('offline')
            }
            return { ...release, ...changes } as never
        })
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.RELEASE_OBJECTS], {
            [FEATURE_FLAGS.RELEASE_OBJECTS]: true,
        })
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
        expect(capture.mock.calls.filter(([event]) => event === 'release broadcasts auto linked')).toEqual(events)
    })
})
