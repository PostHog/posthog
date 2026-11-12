import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { featureFlagsActivityRetrieve } from 'products/feature_flags/frontend/generated/api'

import { releaseCalendarLogic } from './releaseCalendarLogic'

jest.mock('products/feature_flags/frontend/generated/api', () => ({
    featureFlagsActivityRetrieve: jest.fn(),
    featureFlagsList: jest.fn(async () => ({ results: [], next: null })),
    scheduledChangesList: jest.fn(async () => ({ results: [], next: null })),
}))

const mockedRetrieve = jest.mocked(featureFlagsActivityRetrieve)
const PAGE = { results: [], next: null, previous: null, total_count: 0 }

describe('releaseCalendarLogic', () => {
    beforeEach(() => {
        initKeaTests()
        mockedRetrieve.mockReset()
    })

    it('retries a flag whose history failed to load', async () => {
        mockedRetrieve.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(PAGE as never)
        const logic = releaseCalendarLogic()
        logic.mount()

        logic.actions.loadFlagActivity([1])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.flagActivity[1]).toBeUndefined()
        expect(logic.values.failedFlagIds).toEqual([1])

        logic.actions.loadFlagActivity([1])
        await expectLogic(logic).toFinishAllListeners()
        expect(mockedRetrieve).toHaveBeenCalledTimes(2)
        expect(logic.values.flagActivity[1]).toEqual([])
        expect(logic.values.failedFlagIds).toEqual([])
    })

    it('loads a flag again when its history is refreshed', async () => {
        mockedRetrieve.mockResolvedValue(PAGE as never)
        const logic = releaseCalendarLogic()
        logic.mount()

        logic.actions.loadFlagActivity([1])
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadFlagActivity([1])
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.refreshFlagActivity([1])
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedRetrieve).toHaveBeenCalledTimes(2)
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
