import { router } from 'kea-router'

import api from 'lib/api'

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

    // Non-default viewer state must reach the URL (so a link is shareable) while defaults stay out of it.
    // Filters are an array param — this guards the kea-router JSON round-trip that the restore relies on.
    it('writes non-default viewer state to the URL and omits defaults', () => {
        logic.actions.setMetricName('queue_depth')
        logic.actions.setAggregation('rate')
        logic.actions.setFilterStrings(['env=prod'])
        expect(router.values.searchParams).toMatchObject({
            metric: 'queue_depth',
            agg: 'rate',
            filters: ['env=prod'],
        })
        // Defaults are omitted, keeping shared URLs clean.
        expect(router.values.searchParams.view).toBeUndefined()
        expect(router.values.searchParams.dateFrom).toBeUndefined()
    })

    // A reloaded or shared link must restore the reducers. The URL aggregation has to win over the
    // type-based default that setMetricName applies (requests_total is a counter -> 'increase'), and the
    // array params (filters, groupBy) must survive the JSON round-trip as string arrays.
    it('restores viewer state from the URL', () => {
        router.actions.push('/metrics', {
            metric: 'requests_total',
            agg: 'rate',
            filters: ['env=prod'],
            groupBy: ['service.name'],
        })
        expect(logic.values.metricName).toBe('requests_total')
        expect(logic.values.aggregation).toBe('rate')
        expect(logic.values.filterStrings).toEqual(['env=prod'])
        expect(logic.values.groupByKeys).toEqual(['service.name'])
    })
})
