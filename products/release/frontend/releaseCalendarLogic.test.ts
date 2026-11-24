import { expectLogic } from 'kea-test-utils'

import posthog from 'lib/posthog-typed'

import { initKeaTests } from '~/test/init'

import { featureFlagsActivityRetrieve } from 'products/feature_flags/frontend/generated/api'
import { surveysActivityRetrieve } from 'products/surveys/frontend/generated/api'

import { releaseCalendarLogic } from './releaseCalendarLogic'

jest.mock('lib/posthog-typed', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))
jest.mock('products/feature_flags/frontend/generated/api', () => ({
    featureFlagsActivityRetrieve: jest.fn(),
    featureFlagsList: jest.fn(async () => ({ results: [], next: null })),
    scheduledChangesList: jest.fn(async () => ({ results: [], next: null })),
}))

jest.mock('products/surveys/frontend/generated/api', () => ({
    surveysActivityRetrieve: jest.fn(),
}))

const mockedRetrieve = jest.mocked(featureFlagsActivityRetrieve)
const mockedSurveyRetrieve = jest.mocked(surveysActivityRetrieve)
const PAGE = { results: [], next: null, previous: null, total_count: 0 }

describe('releaseCalendarLogic', () => {
    beforeEach(() => {
        initKeaTests()
        mockedRetrieve.mockReset()
        mockedSurveyRetrieve.mockReset()
    })

    it('counts a row expansion but not the collapse that follows', async () => {
        const capture = jest.mocked(posthog.capture)
        capture.mockClear()
        const logic = releaseCalendarLogic()
        logic.mount()

        logic.actions.toggleExpanded('release-1')
        logic.actions.toggleExpanded('release-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(capture.mock.calls).toEqual([['release row expanded', { release_id: 'release-1' }]])
    })

    type Logic = ReturnType<typeof releaseCalendarLogic>
    test.each<{
        name: string
        retrieve: jest.Mock
        load: (logic: Logic) => void
        stored: (logic: Logic) => unknown
        failed: (logic: Logic) => unknown[]
        failedValue: unknown
    }>([
        {
            name: 'flag',
            retrieve: mockedRetrieve,
            load: (logic) => logic.actions.loadFlagActivity([1]),
            stored: (logic) => logic.values.flagActivity[1],
            failed: (logic) => logic.values.failedFlagIds,
            failedValue: 1,
        },
        {
            name: 'survey',
            retrieve: mockedSurveyRetrieve,
            load: (logic) => logic.actions.loadObjectActivity(['survey:abc']),
            stored: (logic) => logic.values.objectActivity['survey:abc'],
            failed: (logic) => logic.values.failedObjectKeys,
            failedValue: 'survey:abc',
        },
    ])('retries a $name whose history failed to load', async ({ retrieve, load, stored, failed, failedValue }) => {
        retrieve.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(PAGE as never)
        const logic = releaseCalendarLogic()
        logic.mount()

        load(logic)
        await expectLogic(logic).toFinishAllListeners()
        expect(stored(logic)).toBeUndefined()
        expect(failed(logic)).toEqual([failedValue])

        load(logic)
        await expectLogic(logic).toFinishAllListeners()
        expect(retrieve).toHaveBeenCalledTimes(2)
        expect(stored(logic)).toEqual([])
        expect(failed(logic)).toEqual([])
    })

    it('loads a flag again when its history is refreshed', async () => {
        mockedRetrieve.mockResolvedValue(PAGE as never)
        const logic = releaseCalendarLogic()
        logic.mount()

        logic.actions.loadFlagActivity([1])
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadFlagActivity([1])
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.refreshFlagActivity([1, 2])
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedRetrieve.mock.calls.map(([, flagId]) => flagId)).toEqual([1, 1])
    })

    it('ignores a superseded history response that arrives last', async () => {
        const resolvers: ((value: unknown) => void)[] = []
        mockedRetrieve.mockImplementation(() => new Promise((resolve) => resolvers.push(resolve)) as never)
        const logic = releaseCalendarLogic()
        logic.mount()

        logic.actions.loadFlagActivity([1])
        logic.actions.refreshFlagActivity([1])
        const [stale, fresh] = resolvers
        fresh({ ...PAGE, results: [{ id: 'new' }] })
        await expectLogic(logic).toFinishAllListeners()
        stale({ ...PAGE, results: [{ id: 'old' }] })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.flagActivity[1]).toEqual([{ id: 'new' }])
    })

    it('keeps at most six history requests in flight across loads', async () => {
        let inFlight = 0
        let peak = 0
        const releases: (() => void)[] = []
        mockedRetrieve.mockImplementation(
            () =>
                new Promise((resolve) => {
                    inFlight += 1
                    peak = Math.max(peak, inFlight)
                    releases.push(() => {
                        inFlight -= 1
                        resolve(PAGE as never)
                    })
                })
        )
        const logic = releaseCalendarLogic()
        logic.mount()

        logic.actions.loadFlagActivity([1, 2, 3, 4, 5])
        logic.actions.loadFlagActivity([6, 7, 8, 9, 10])
        while (releases.length) {
            releases.shift()!()
            await Promise.resolve()
            await Promise.resolve()
        }
        await expectLogic(logic).toFinishAllListeners()

        expect(peak).toBe(6)
        expect(mockedRetrieve).toHaveBeenCalledTimes(10)
    })
})
