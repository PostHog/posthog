import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { metricsNamesRetrieve, metricsValuesCreate } from '../generated/api'
import { metricsSceneLogic } from '../metricsSceneLogic'
import { metricNamePickerLogic } from './metricNamePickerLogic'
import { SPARKLINE_BATCH_SIZE, metricsCatalogLogic } from './metricsCatalogLogic'
import { metricsViewerLogic } from './metricsViewerLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    metricsNamesRetrieve: jest.fn(),
    metricsValuesCreate: jest.fn(),
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
        jest.mocked(metricsValuesCreate).mockReset()
        jest.mocked(metricsValuesCreate).mockResolvedValue({ results: [SPARKLINE_ITEM] } as any)
        jest.mocked(metricsNamesRetrieve).mockReset()
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
        expect(metricsValuesCreate).not.toHaveBeenCalled()
    })

    it('batches visible cards and maps each result by name', async () => {
        const queueDetail = { ...CATALOG_ITEMS[1], sparkline: [3, 2, 1] }
        jest.mocked(metricsValuesCreate).mockResolvedValueOnce({ results: [queueDetail, SPARKLINE_ITEM] } as any)
        logic = metricsCatalogLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadCatalogSuccess'])

        await expectLogic(logic, () => {
            logic.actions.loadSparkline(CATALOG_ITEMS[0])
            logic.actions.loadSparkline(CATALOG_ITEMS[1])
            logic.actions.loadSparkline(CATALOG_ITEMS[0])
        }).toDispatchActions(['loadSparklineSuccess'])

        expect(jest.mocked(metricsValuesCreate)).toHaveBeenCalledWith(expect.any(String), {
            names: ['http.server.duration', 'queue.depth'],
        })
        expect(metricsValuesCreate).toHaveBeenCalledTimes(1)
        expect(logic.values.catalogItemDetails['http.server.duration']).toEqual(SPARKLINE_ITEM)
        expect(logic.values.catalogItemDetails['queue.depth']).toEqual(queueDetail)
        expect(logic.values.catalogItemDetailsLoading).toEqual({ 'http.server.duration': false, 'queue.depth': false })
    })

    it('bounds batches and queues cards that enter view during a request', async () => {
        const items = Array.from({ length: SPARKLINE_BATCH_SIZE + 2 }, (_, index) => ({
            name: `metric.${index}`,
            metric_type: 'gauge',
        }))
        let completeBatch!: (response: any) => void
        jest.mocked(metricsValuesCreate).mockImplementationOnce(
            () => new Promise((resolve) => (completeBatch = resolve))
        )
        logic = metricsCatalogLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadCatalogSuccess'])

        await expectLogic(logic, () => {
            items.slice(0, -1).forEach(logic.actions.loadSparkline)
        }).toDispatchActions(['dequeueSparklines'])
        logic.actions.loadSparkline(items[items.length - 1])
        expect(metricsValuesCreate).toHaveBeenCalledTimes(1)
        expect(jest.mocked(metricsValuesCreate).mock.calls[0][1]?.names).toHaveLength(SPARKLINE_BATCH_SIZE)

        await expectLogic(logic, () => completeBatch({ results: [] })).toFinishAllListeners()

        expect(metricsValuesCreate).toHaveBeenCalledTimes(2)
        expect(jest.mocked(metricsValuesCreate).mock.calls[1][1]?.names).toEqual(
            items.slice(SPARKLINE_BATCH_SIZE).map((item) => item.name)
        )
        expect(Object.keys(logic.values.catalogItemDetails)).toHaveLength(items.length)
        expect(Object.values(logic.values.catalogItemDetailsLoading)).not.toContain(true)
    })

    it.each(['success', 'failure'])('discards an old scope batch %s', async (outcome) => {
        let finishBatch!: () => void
        jest.mocked(metricsValuesCreate).mockImplementationOnce(
            () =>
                new Promise((resolve, reject) => {
                    finishBatch = () =>
                        outcome === 'success'
                            ? resolve({ results: [SPARKLINE_ITEM] } as any)
                            : reject(new Error('old scope'))
                })
        )
        logic = metricsCatalogLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadCatalogSuccess'])
        await expectLogic(logic, () => logic.actions.loadSparkline(CATALOG_ITEMS[0])).toDispatchActions([
            'dequeueSparklines',
        ])
        await expectLogic(logic, () => logic.actions.setServices(['worker'])).toDispatchActions(['loadCatalogSuccess'])
        await expectLogic(logic, finishBatch).toFinishAllListeners()

        expect(logic.values.catalogItemDetails).toEqual({})
        expect(logic.values.catalogItemDetailsFailed).toEqual({})
        await expectLogic(logic, () => logic.actions.loadSparkline(CATALOG_ITEMS[0])).toDispatchActions([
            'loadSparklineSuccess',
        ])
        expect(metricsValuesCreate).toHaveBeenLastCalledWith(expect.any(String), {
            names: [CATALOG_ITEMS[0].name],
            service: 'worker',
        })
    })

    it('retries a sparkline after a transient failure', async () => {
        jest.mocked(metricsValuesCreate)
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
        expect(jest.mocked(metricsValuesCreate)).toHaveBeenCalledTimes(2)
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
        // The type drives the default aggregation: a histogram charts from its
        // bucket distribution, not the cumulative sum in the scalar value column.
        expect(metricsViewerLogic.values.activeClause.aggregation).toBe('histogram_quantile')
    })
})
