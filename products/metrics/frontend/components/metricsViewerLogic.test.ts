import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { metricsCharacterizeCreate } from 'products/metrics/frontend/generated/api'

import { metricNamePickerLogic } from './metricNamePickerLogic'
import { metricsViewerLogic } from './metricsViewerLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    metricsQueryCreate: jest.fn(async () => ({ results: [] })),
    metricsCharacterizeCreate: jest.fn(async () => ({ direction: 'flat' })),
}))

const PICKER_ITEMS = [
    { name: 'requests_total', metric_type: 'sum' },
    { name: 'queue_depth', metric_type: 'gauge' },
    { name: 'request_duration', metric_type: 'histogram' },
    { name: 'mystery_metric', metric_type: 'unknown_type' },
]

describe('metricsViewerLogic', () => {
    let logic: ReturnType<typeof metricsViewerLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
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

    it('applies the type-appropriate aggregation when a later clause picks a metric', () => {
        logic.actions.setMetricName('requests_total')
        logic.actions.addClause()
        logic.actions.updateClause(1, { metricName: 'request_duration' })
        expect(logic.values.clauses[1].aggregation).toBe('p95')
    })

    it('builds the single-metric shorthand for one clause without a formula', () => {
        logic.actions.setMetricName('queue_depth')
        logic.actions.setGroupByKeys(['service.name'])
        logic.actions.setFilterStrings(['env=prod'])
        expect(logic.values.querySelection).toEqual({
            metricName: 'queue_depth',
            aggregation: 'avg',
            groupBy: [{ key: 'service.name' }],
            filters: [{ key: 'env', op: 'eq', value: 'prod' }],
        })
    })

    it.each([
        ['a second clause', true, ''],
        ['a formula', false, 'a * 100'],
    ])('switches to named clauses when %s is added', (_desc, addSecond, formula) => {
        logic.actions.setMetricName('requests_total')
        if (addSecond) {
            logic.actions.addClause()
            logic.actions.updateClause(1, { metricName: 'queue_depth' })
        }
        if (formula) {
            logic.actions.setFormulaEnabled(true)
            logic.actions.setFormula(formula)
        }
        expect(logic.values.querySelection).toEqual({
            clauses: [
                { name: 'a', metricName: 'requests_total', aggregation: 'increase' },
                ...(addSecond ? [{ name: 'b', metricName: 'queue_depth', aggregation: 'avg' }] : []),
            ],
            ...(formula ? { formula } : {}),
        })
    })

    it('returns no selection while any clause lacks a metric', () => {
        logic.actions.setMetricName('queue_depth')
        logic.actions.addClause()
        expect(logic.values.querySelection).toBeNull()
    })

    it('renumbers clause names when a clause is removed', () => {
        logic.actions.setMetricName('requests_total')
        logic.actions.addClause()
        logic.actions.updateClause(1, { metricName: 'queue_depth' })
        logic.actions.addClause()
        logic.actions.updateClause(2, { metricName: 'request_duration' })
        logic.actions.removeClause(0)
        expect(logic.values.querySelection).toEqual({
            clauses: [
                { name: 'a', metricName: 'queue_depth', aggregation: 'avg' },
                { name: 'b', metricName: 'request_duration', aggregation: 'p95' },
            ],
        })
    })

    it.each([
        ['one clause', false, true],
        ['multiple clauses', true, false],
    ])('anomaly characterization with %s', async (_desc, addSecond, expectCalled) => {
        logic.actions.setMetricName('requests_total')
        if (addSecond) {
            logic.actions.addClause()
            logic.actions.updateClause(1, { metricName: 'queue_depth' })
        }
        await logic.asyncActions.fetchAnomaly({})
        expect(metricsCharacterizeCreate as jest.Mock).toHaveBeenCalledTimes(expectCalled ? 1 : 0)
    })
})
