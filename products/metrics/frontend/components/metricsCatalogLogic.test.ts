import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { metricsNamesRetrieve, metricsValuesRetrieve } from '../generated/api'
import { metricsSceneLogic } from '../metricsSceneLogic'
import { metricNamePickerLogic } from './metricNamePickerLogic'
import { metricsCatalogLogic } from './metricsCatalogLogic'
import { metricsViewerLogic } from './metricsViewerLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    metricsNamesRetrieve: jest.fn(),
    metricsValuesRetrieve: jest.fn(),
    metricsQueryCreate: jest.fn(),
}))

const CATALOG_ITEMS = [
    {
        name: 'http.server.duration',
        metric_type: 'histogram',
    },
    {
        name: 'queue.depth',
        metric_type: 'gauge',
    },
    { name: 'jobs.processed', metric_type: 'sum' },
]

const SPARKLINE_ITEM = {
    ...CATALOG_ITEMS[0],
    unit: 'ms',
    last_seen: '2026-09-03T10:00:00+00:00',
    sparkline: [1, 2, 3],
}

describe('metricsCatalogLogic', () => {
    let logic: ReturnType<typeof metricsCatalogLogic.build>

    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: AccessControlLevel.Viewer,
            },
        } as AppContext
        initKeaTests()
        jest.mocked(metricsValuesRetrieve).mockReset()
        jest.mocked(metricsValuesRetrieve).mockResolvedValue({ results: [SPARKLINE_ITEM] } as any)
        jest.mocked(metricsNamesRetrieve).mockResolvedValue({ results: CATALOG_ITEMS } as any)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads catalog names without requesting sparklines', async () => {
        logic = metricsCatalogLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadCatalogSuccess']).toMatchValues({
            catalogItems: CATALOG_ITEMS,
        })
    })

    it('loads a card sparkline only when that card enters view', async () => {
        logic = metricsCatalogLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadCatalogSuccess'])

        await expectLogic(logic, () => {
            logic.actions.loadSparkline(CATALOG_ITEMS[0])
        }).toDispatchActions(['loadSparklineSuccess'])

        expect(jest.mocked(metricsValuesRetrieve)).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ value: 'http.server.duration', limit: 1 })
        )
        expect(logic.values.catalogItemDetails['http.server.duration']).toEqual(SPARKLINE_ITEM)
    })

    it('retries a sparkline after a transient failure', async () => {
        jest.mocked(metricsValuesRetrieve)
            .mockRejectedValueOnce(new Error('temporary error'))
            .mockResolvedValueOnce({ results: [SPARKLINE_ITEM] } as any)
        logic = metricsCatalogLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadCatalogSuccess'])

        await expectLogic(logic, () => {
            logic.actions.loadSparkline(CATALOG_ITEMS[0])
        }).toDispatchActions(['loadSparklineFailure'])
        expect(logic.values.catalogItemDetailsFailed['http.server.duration']).toBe(true)

        await expectLogic(logic, () => {
            logic.actions.retrySparkline(CATALOG_ITEMS[0])
        }).toDispatchActions(['loadSparklineSuccess'])

        expect(logic.values.catalogItemDetailsFailed['http.server.duration']).toBe(false)
        expect(jest.mocked(metricsValuesRetrieve)).toHaveBeenCalledTimes(2)
    })

    it('keeps every in-flight card when more cards scroll into view', async () => {
        // Several cards cross the viewport at once. Each one is its own request,
        // so a later card must not cancel or fail an earlier one still in flight.
        jest.mocked(metricsValuesRetrieve).mockImplementation(
            (_teamId: any, params: any) =>
                new Promise((resolve) =>
                    setTimeout(() => resolve({ results: [{ ...SPARKLINE_ITEM, name: params.value }] } as any), 0)
                ) as any
        )
        logic = metricsCatalogLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadCatalogSuccess'])

        await expectLogic(logic, () => {
            logic.actions.loadSparkline(CATALOG_ITEMS[0])
            logic.actions.loadSparkline(CATALOG_ITEMS[1])
        }).toFinishAllListeners()

        expect(logic.values.catalogItemDetailsFailed).toEqual({})
        expect(Object.keys(logic.values.catalogItemDetails).sort()).toEqual([
            CATALOG_ITEMS[0].name,
            CATALOG_ITEMS[1].name,
        ])
    })

    it('a rejection from the old service scope does not fail the same card in the new scope', async () => {
        // A card in scope A fails after the person has entered scope B. The name
        // can exist in both, and the new card must still get to ask for itself.
        let rejectFirst: (error: Error) => void = () => {}
        jest.mocked(metricsValuesRetrieve).mockImplementationOnce(
            () => new Promise((_resolve, reject) => (rejectFirst = reject)) as any
        )
        metricNamePickerLogic.mount()
        logic = metricsCatalogLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadCatalogSuccess'])

        logic.actions.loadSparkline(CATALOG_ITEMS[0])
        metricNamePickerLogic.actions.setServices(['api'])
        await expectLogic(logic).toDispatchActions(['loadCatalogSuccess'])

        rejectFirst(new Error('boom'))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.catalogItemDetailsFailed).toEqual({})
        expect(logic.values.catalogItemDetailsLoading[CATALOG_ITEMS[0].name]).toBeUndefined()
    })

    it('narrows the visible cards by a search substring', async () => {
        logic = metricsCatalogLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadCatalogSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setSearch('queue')
        }).toMatchValues({
            visibleItems: [CATALOG_ITEMS[1]],
        })
    })

    it('fetches the catalog scoped to the services the picker is pinned to', async () => {
        // The catalog follows the same picker scoping the overview drives, so a
        // service clicked on the overview only draws that service's cards.
        metricNamePickerLogic.mount()
        metricNamePickerLogic.actions.setServices(['api'])
        logic = metricsCatalogLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadCatalogSuccess'])

        expect(jest.mocked(metricsNamesRetrieve)).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ service: 'api' })
        )
    })

    it('fetches the whole catalog when no service scope is set', async () => {
        logic = metricsCatalogLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadCatalogSuccess'])

        const call = jest.mocked(metricsNamesRetrieve).mock.calls[0][1]
        expect(call).not.toHaveProperty('service')
    })

    it('openMetric lands the metric in the viewer and switches tab', async () => {
        metricNamePickerLogic.mount()
        await expectLogic(metricNamePickerLogic).toDispatchActions(['loadItemsSuccess'])
        logic = metricsCatalogLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.openMetric(CATALOG_ITEMS[2]) // jobs.processed, a sum
        }).toDispatchActions([metricsViewerLogic.actionTypes.setMetricName, metricsSceneLogic.actionTypes.setActiveTab])

        expect(metricsSceneLogic.values.activeTab).toBe('viewer')
        expect(metricsViewerLogic.values.metricName).toBe('jobs.processed')
    })

    it('openMetric pins the picked metric type so a reused name charts only that type', async () => {
        metricNamePickerLogic.mount()
        await expectLogic(metricNamePickerLogic).toDispatchActions(['loadItemsSuccess'])
        logic = metricsCatalogLogic()
        logic.mount()

        logic.actions.openMetric(CATALOG_ITEMS[0]) // a histogram

        expect(metricsViewerLogic.values.activeClause.selectedMetricType).toBe('histogram')
        // The type drives the default aggregation: a histogram charts as a percentile.
        expect(metricsViewerLogic.values.activeClause.aggregation).toBe('p95')
    })
})
