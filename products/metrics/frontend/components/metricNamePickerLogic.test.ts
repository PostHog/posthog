import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { metricsNamesRetrieve } from '../generated/api'
import { METRIC_NAMES_LIMIT, filterMetricNames, metricNamePickerLogic } from './metricNamePickerLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    metricsNamesRetrieve: jest.fn(),
}))

const deferred = <T>(): { promise: Promise<T>; resolve: (value: T) => void } => {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((r) => (resolve = r))
    return { promise, resolve }
}
const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))
const fullPage = Array.from({ length: METRIC_NAMES_LIMIT }, (_, i) => ({ name: `m${i}`, metric_type: 'gauge' }))

const ITEMS = [
    { name: 'server.http', metric_type: 'sum' },
    { name: 'http.requests', metric_type: 'sum' },
    { name: 'queue.depth', metric_type: 'gauge' },
    { name: 'http', metric_type: 'gauge' },
]

describe('metricNamePickerLogic', () => {
    let logic: ReturnType<typeof metricNamePickerLogic.build>

    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: AccessControlLevel.Viewer,
            },
        } as AppContext
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.METRICS]: true })
        jest.mocked(metricsNamesRetrieve).mockReset()
        jest.mocked(metricsNamesRetrieve).mockResolvedValue({ results: ITEMS } as any)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the full list on mount', async () => {
        logic = metricNamePickerLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadItemsSuccess']).toMatchValues({
            items: ITEMS,
            itemsComplete: true,
        })
        expect(metricsNamesRetrieve).toHaveBeenCalledTimes(1)
        expect(metricsNamesRetrieve).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ value: '', limit: METRIC_NAMES_LIMIT })
        )
    })

    it('filters a complete list locally without a request', async () => {
        logic = metricNamePickerLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadItemsSuccess'])
        jest.mocked(metricsNamesRetrieve).mockClear()

        logic.actions.setSearch('HTTP')

        expect(logic.values.filteredItems).toEqual([ITEMS[3], ITEMS[1], ITEMS[0]])
        await expectLogic(logic).toFinishAllListeners()
        expect(metricsNamesRetrieve).not.toHaveBeenCalled()
    })

    it('searches the server when a complete list has no local match', async () => {
        logic = metricNamePickerLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadItemsSuccess']).toMatchValues({ itemsComplete: true })

        jest.mocked(metricsNamesRetrieve).mockResolvedValueOnce({ results: [{ name: 'checkout.orders' }] } as any)
        await expectLogic(logic, () => {
            logic.actions.setSearch('checkout')
        }).toDispatchActions(['searchItemsSuccess'])

        expect(logic.values.filteredItems).toEqual([{ name: 'checkout.orders' }])
    })

    it('reloads an empty list when the picker opens', async () => {
        jest.mocked(metricsNamesRetrieve).mockResolvedValueOnce({ results: [] } as any)
        logic = metricNamePickerLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadItemsSuccess']).toMatchValues({ items: [] })

        await expectLogic(logic, () => {
            logic.actions.openPicker()
        })
            .toDispatchActions(['loadItemsSuccess'])
            .toMatchValues({ items: ITEMS })
        expect(metricsNamesRetrieve).toHaveBeenCalledTimes(2)
    })

    it('keeps the first load running when an early search finishes', async () => {
        const firstLoad = deferred<any>()
        jest.mocked(metricsNamesRetrieve)
            .mockReturnValueOnce(firstLoad.promise)
            .mockResolvedValueOnce({ results: [] } as any)
        logic = metricNamePickerLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setSearch('zzz')
        }).toDispatchActions(['searchItemsSuccess'])

        expect(logic.values.fullItemsLoading).toBe(true)
        firstLoad.resolve({ results: ITEMS })
        await expectLogic(logic).toDispatchActions(['loadItemsSuccess']).toMatchValues({ items: ITEMS })
    })

    it('does not send a search that was cleared during the debounce', async () => {
        jest.mocked(metricsNamesRetrieve).mockResolvedValueOnce({ results: fullPage } as any)
        logic = metricNamePickerLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadItemsSuccess'])
        jest.mocked(metricsNamesRetrieve).mockClear()

        logic.actions.setSearch('zzz')
        logic.actions.setSearch('')
        await wait(400)

        expect(metricsNamesRetrieve).not.toHaveBeenCalled()
        expect(logic.values.searchedItemsLoading).toBe(false)
    })

    it('searches in the background and adds new names when the list is partial', async () => {
        jest.mocked(metricsNamesRetrieve).mockResolvedValueOnce({ results: fullPage } as any)
        logic = metricNamePickerLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadItemsSuccess']).toMatchValues({ itemsComplete: false })

        jest.mocked(metricsNamesRetrieve).mockResolvedValueOnce({
            results: [{ name: 'm1', metric_type: 'gauge' }, ITEMS[2]],
        } as any)
        await expectLogic(logic, () => {
            logic.actions.setSearch('m1')
        })
            .toMatchValues({ searchedItemsLoading: true })
            .toDispatchActions(['searchItemsSuccess'])
            .toMatchValues({ searchedItemsLoading: false })

        expect(metricsNamesRetrieve).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ value: 'm1' })
        )
        expect(logic.values.items).toHaveLength(METRIC_NAMES_LIMIT + 1)
        expect(logic.values.items[METRIC_NAMES_LIMIT]).toEqual(ITEMS[2])
    })

    it('reloads the full list when the service scope changes', async () => {
        logic = metricNamePickerLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadItemsSuccess'])

        jest.mocked(metricsNamesRetrieve).mockResolvedValueOnce({ results: [ITEMS[2]] } as any)
        await expectLogic(logic, () => {
            logic.actions.setServices(['api'])
        })
            .toMatchValues({ filteredItems: [], items: ITEMS })
            .toDispatchActions(['loadItemsSuccess'])
            .toMatchValues({ filteredItems: [ITEMS[2]], items: [ITEMS[2]] })
        expect(metricsNamesRetrieve).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ value: '', service: 'api' })
        )
    })

    it('shows the old list again when the new scope fails to load', async () => {
        logic = metricNamePickerLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadItemsSuccess'])

        jest.mocked(metricsNamesRetrieve).mockRejectedValueOnce(new Error('timeout'))
        await expectLogic(logic, () => {
            logic.actions.setServices(['api'])
        }).toDispatchActions(['loadItemsFailure'])

        expect(logic.values.filteredItems).toEqual(ITEMS)
    })

    it('drops a search that finishes after the service scope changes', async () => {
        const oldScopeSearch = deferred<any>()
        jest.mocked(metricsNamesRetrieve)
            .mockResolvedValueOnce({ results: fullPage } as any)
            .mockReturnValueOnce(oldScopeSearch.promise)
            .mockResolvedValueOnce({ results: [ITEMS[2]] } as any)
        logic = metricNamePickerLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadItemsSuccess'])

        logic.actions.setSearch('old')
        await wait(350)
        logic.actions.setServices(['api'])
        oldScopeSearch.resolve({ results: [{ name: 'old.scope.metric' }] })

        await expectLogic(logic).toDispatchActions(['loadItemsSuccess']).toFinishAllListeners()
        expect(logic.values.items.map((item) => item.name)).not.toContain('old.scope.metric')
    })
})

describe('filterMetricNames', () => {
    it('ranks exact, then prefix, then suffix, then the server order', () => {
        expect(filterMetricNames(ITEMS, ' Http ').map((item) => item.name)).toEqual([
            'http',
            'http.requests',
            'server.http',
        ])
    })

    it('returns every item for an empty search', () => {
        expect(filterMetricNames(ITEMS, '')).toBe(ITEMS)
    })
})
