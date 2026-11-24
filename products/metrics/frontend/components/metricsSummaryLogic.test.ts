import { expectLogic } from 'kea-test-utils'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { metricsNamesRetrieve, metricsValuesRetrieve } from '../generated/api'
import { metricsSceneLogic } from '../metricsSceneLogic'
import { metricsSummaryLogic } from './metricsSummaryLogic'
import { metricsViewerLogic } from './metricsViewerLogic'

jest.mock('../generated/api', () => ({
    metricsAttributeValuesRetrieve: jest.fn(),
    metricsAttributesRetrieve: jest.fn(),
    metricsCharacterizeCreate: jest.fn(),
    metricsHasMetricsRetrieve: jest.fn(),
    metricsQueryCreate: jest.fn(),
    metricsSamplesCreate: jest.fn(),
    metricsNamesRetrieve: jest.fn(),
    metricsValuesRetrieve: jest.fn(),
}))

const METRICS = [
    { name: 'http.server.duration', metric_type: 'histogram', unit: 'ms', series_count: 12, tag_key_count: 3 },
    { name: 'queue.depth', metric_type: 'gauge', unit: '', series_count: 2, tag_key_count: 1 },
]

describe('metricsSummaryLogic', () => {
    let logic: ReturnType<typeof metricsSummaryLogic.build>

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
        jest.mocked(metricsValuesRetrieve).mockResolvedValue({ results: METRICS } as any)
        jest.mocked(metricsNamesRetrieve).mockResolvedValue({ results: [] } as any)
        logic = metricsSummaryLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the metrics with series stats and filters them by name', async () => {
        await expectLogic(logic).toDispatchActions(['loadMetricsSuccess']).toMatchValues({ filteredMetrics: METRICS })
        expect(jest.mocked(metricsValuesRetrieve).mock.calls[0][1]).toMatchObject({
            series_stats: true,
            sparklines: false,
        })

        logic.actions.setSearch('  QUEUE ')

        expect(logic.values.filteredMetrics.map((metric) => metric.name)).toEqual(['queue.depth'])
    })

    it('asks the server to search when the catalog is truncated', async () => {
        await expectLogic(logic).toDispatchActions(['loadMetricsSuccess'])
        logic.actions.setCatalogTruncated(true)

        await expectLogic(logic, () => {
            logic.actions.setSearch('queue')
        }).toDispatchActions(['loadMetricsSuccess'])

        expect(jest.mocked(metricsValuesRetrieve).mock.lastCall?.[1]).toMatchObject({ value: 'queue' })
    })

    it('opens a clicked metric in the viewer as a builder query', async () => {
        await expectLogic(logic).toDispatchActions(['loadMetricsSuccess'])
        metricsViewerLogic.actions.applyQuery({
            kind: NodeKind.MetricsQuery,
            clauses: [],
            language: 'promql',
            promql: 'up',
        })

        await expectLogic(logic, () => {
            logic.actions.viewMetric('queue.depth')
        }).toDispatchActions([
            metricsViewerLogic.actionCreators.setMetricName('queue.depth'),
            metricsSceneLogic.actionCreators.setActiveTab('viewer'),
        ])
        expect(metricsSceneLogic.values.activeTab).toBe('viewer')
        expect(metricsViewerLogic.values.language).toBe('builder')
    })
})
