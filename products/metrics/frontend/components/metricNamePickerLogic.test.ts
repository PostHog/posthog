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
        expect(logic.values.itemsLoading).toBe(false)
        await expectLogic(logic).toNotHaveDispatchedActions(['searchItems'])
        expect(metricsNamesRetrieve).not.toHaveBeenCalled()
    })

    it('searches in the background and adds new names when the list is partial', async () => {
        const fullPage = Array.from({ length: METRIC_NAMES_LIMIT }, (_, i) => ({
            name: `m${i}`,
            metric_type: 'gauge',
        }))
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
            .toMatchValues({ itemsLoading: true })
            .toDispatchActions(['searchItemsSuccess'])
            .toMatchValues({ itemsLoading: false })

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
            .toDispatchActions(['loadItemsSuccess'])
            .toMatchValues({ items: [ITEMS[2]] })
        expect(metricsNamesRetrieve).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ value: '', service: 'api' })
        )
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
