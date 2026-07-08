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

    // The chip parser must match the two-char operators before the bare '=', and never let the
    // value slice swallow the operator characters.
    it.each([
        ['env=prod', { key: 'env', op: 'eq', value: 'prod' }],
        ['env!=prod', { key: 'env', op: 'neq', value: 'prod' }],
        ['svc=~checkout.*', { key: 'svc', op: 'regex', value: 'checkout.*' }],
        ['path!~/health', { key: 'path', op: 'not_regex', value: '/health' }],
        ['  env = prod ', { key: 'env', op: 'eq', value: 'prod' }],
    ])('parses filter chip %s into the right operator', (chip, expected) => {
        logic.actions.setFilterStrings([chip])
        expect(logic.values.queryFilters).toEqual([expected])
    })

    it('drops malformed filter chips with no operator or empty key', () => {
        logic.actions.setFilterStrings(['noop', '=orphan', 'env=prod'])
        expect(logic.values.queryFilters).toEqual([{ key: 'env', op: 'eq', value: 'prod' }])
    })
})
