import api from 'lib/api'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { metricNamePickerLogic } from './metricNamePickerLogic'
import { metricsViewerLogic } from './metricsViewerLogic'

const PICKER_ITEMS = [
    { name: 'requests_total', metric_type: 'sum' },
    { name: 'queue_depth', metric_type: 'gauge' },
    { name: 'request_duration', metric_type: 'histogram' },
    { name: 'mystery_metric', metric_type: 'unknown_type' },
]

describe('metricsViewerLogic', () => {
    let logic: ReturnType<typeof metricsViewerLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.metrics, 'values').mockResolvedValue({ results: PICKER_ITEMS })
        logic = metricsViewerLogic()
        logic.mount()
        metricNamePickerLogic.actions.loadItemsSuccess(PICKER_ITEMS)
    })

    afterEach(() => {
        logic?.unmount()
    })

    // Regression: the viewer defaulted every metric to `sum`, so selecting a
    // cumulative counter summed raw monotonic readings across pods and buckets —
    // a huge meaningless total instead of the actual increase.
    it.each([
        ['requests_total', 'increase'],
        ['queue_depth', 'avg'],
        ['request_duration', 'p95'],
    ])('selecting %s applies the type-appropriate aggregation %s', (metricName, expected) => {
        logic.actions.setMetricName(metricName)
        expect(logic.values.aggregation).toBe(expected)
    })

    it('keeps a manual aggregation pick until the metric changes', () => {
        logic.actions.setMetricName('requests_total')
        logic.actions.setAggregation('rate')
        expect(logic.values.aggregation).toBe('rate')
        logic.actions.setMetricName('queue_depth')
        expect(logic.values.aggregation).toBe('avg')
    })

    it('leaves aggregation untouched for unknown metric types', () => {
        logic.actions.setMetricName('requests_total')
        logic.actions.setMetricName('mystery_metric')
        expect(logic.values.aggregation).toBe('increase')
    })

    // metricsQueryNode is what "Save as insight" persists — a wrong mapping here
    // silently saves insights that re-run a different query than the viewer showed.
    it('maps viewer state to a MetricsQuery node, translating p95 to quantile', () => {
        logic.actions.setMetricName('request_duration')
        logic.actions.setGroupByKeys(['container'])
        logic.actions.setFilterStrings(['namespace=posthog'])
        logic.actions.setDateFrom('-24h')

        expect(logic.values.aggregation).toBe('p95')
        expect(logic.values.metricsQueryNode).toEqual({
            kind: NodeKind.MetricsQuery,
            clauses: [
                {
                    name: 'a',
                    metricName: 'request_duration',
                    aggregation: 'quantile',
                    quantile: 0.95,
                    filters: [{ key: 'namespace', op: 'eq', value: 'posthog' }],
                    groupBy: [{ key: 'container' }],
                },
            ],
            dateRange: { date_from: '-24h' },
        })
    })

    it('produces no MetricsQuery node without a metric name', () => {
        expect(logic.values.metricsQueryNode).toBeNull()
    })
})
