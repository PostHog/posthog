import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { metricsValuesRetrieve } from '../generated/api'
import { metricsSceneLogic } from '../metricsSceneLogic'
import { metricNamePickerLogic } from './metricNamePickerLogic'
import { metricsCatalogLogic } from './metricsCatalogLogic'
import { metricsViewerLogic } from './metricsViewerLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    metricsValuesRetrieve: jest.fn(),
    metricsQueryCreate: jest.fn(),
}))

const CATALOG_ITEMS = [
    { name: 'http.server.duration', metric_type: 'histogram', unit: 'ms', last_seen: '2026-09-03T10:00:00+00:00', sparkline: [1, 2, 3] },
    { name: 'queue.depth', metric_type: 'gauge', unit: '', last_seen: '2026-09-03T10:00:00+00:00', sparkline: [3, 2, 1] },
    { name: 'jobs.processed', metric_type: 'sum', unit: '', last_seen: '2026-09-03T09:00:00+00:00', sparkline: [0, 1] },
]

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
        jest.mocked(metricsValuesRetrieve).mockResolvedValue({ results: CATALOG_ITEMS } as any)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads catalog items from the metric names endpoint', async () => {
        logic = metricsCatalogLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadCatalogSuccess']).toMatchValues({
            catalogItems: CATALOG_ITEMS,
        })
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

        expect(jest.mocked(metricsValuesRetrieve)).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ service: 'api' })
        )
    })

    it('fetches the whole catalog when no service scope is set', async () => {
        logic = metricsCatalogLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadCatalogSuccess'])

        const call = jest.mocked(metricsValuesRetrieve).mock.calls[0][1]
        expect(call).not.toHaveProperty('service')
    })

    it('openMetric lands the metric in the viewer and switches tab', async () => {
        metricNamePickerLogic.mount()
        await expectLogic(metricNamePickerLogic).toDispatchActions(['loadItemsSuccess'])
        logic = metricsCatalogLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.openMetric(CATALOG_ITEMS[2]) // jobs.processed, a sum
        }).toDispatchActions([
            metricsViewerLogic.actionTypes.setMetricName,
            metricsSceneLogic.actionTypes.setActiveTab,
        ])

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
