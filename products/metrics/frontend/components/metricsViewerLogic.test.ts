import { expectLogic } from 'kea-test-utils'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import { metricsAttributesRetrieve, metricsValuesRetrieve } from 'products/metrics/frontend/generated/api'

import { metricNamePickerLogic } from './metricNamePickerLogic'
import { metricsViewerLogic, NEW_QUERY_STARTED_ERROR_MESSAGE } from './metricsViewerLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsValuesRetrieve: jest.fn(),
    metricsAttributesRetrieve: jest.fn(),
}))

const filterGroupWith = (filters: Record<string, any>[]): UniversalFiltersGroup => ({
    type: FilterLogicalOperator.And,
    values: [
        {
            type: FilterLogicalOperator.And,
            values: filters.map(
                (filter) => ({ type: PropertyFilterType.MetricAttribute, ...filter }) as UniversalFiltersGroupValue
            ),
        },
    ],
})

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
        jest.mocked(metricsValuesRetrieve).mockResolvedValue({ results: PICKER_ITEMS })
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

    // metricsQueryNode is what "Save as insight" persists: a wrong mapping here
    // silently saves insights that re-run a different query than the viewer showed.
    it('maps viewer state to a MetricsQuery node, translating p95 to quantile', () => {
        logic.actions.setMetricName('request_duration')
        logic.actions.setGroupByKeys(['container'])
        logic.actions.setFilterGroup(
            filterGroupWith([{ key: 'namespace', operator: PropertyOperator.Exact, value: ['posthog'] }])
        )
        logic.actions.setDateFrom('-24h')

        expect(logic.values.aggregation).toBe('p95')
        expect(logic.values.metricsQueryNode).toEqual({
            kind: NodeKind.MetricsQuery,
            clauses: [
                {
                    name: 'a',
                    metricName: 'request_duration',
                    aggregation: 'quantile',
                    metricType: 'histogram',
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

    // A type outside the API enum (or a metric missing from the picker list) must be
    // omitted, not persisted — the backend rejects unknown metric types.
    it('omits metricType from the node when the picked type is unknown', () => {
        logic.actions.setMetricName('mystery_metric')
        expect(logic.values.metricsQueryNode?.clauses[0]).not.toHaveProperty('metricType')
    })

    // A failed query (bad regex, 500) used to render the same "No data" empty state as a genuinely
    // empty result. The failure records the message so the viewer can show a real error instead.
    // kea-loaders dispatches `<key>Failure(error.message, error)`, so the reducer reads the message.
    it('records a real query failure in queryError', () => {
        logic.actions.fetchQueryResultsFailure('Invalid regex pattern', new Error('Invalid regex pattern'))
        expect(logic.values.queryError).toBe('Invalid regex pattern')
    })

    // The debounced viewer aborts the in-flight query on every change; that cancellation rejects with
    // NEW_QUERY_STARTED_ERROR_MESSAGE (whose text has no "abort"), and must not become an error banner.
    it('does not record an aborted (superseded) query as an error', () => {
        logic.actions.fetchQueryResultsFailure(
            NEW_QUERY_STARTED_ERROR_MESSAGE,
            new DOMException(NEW_QUERY_STARTED_ERROR_MESSAGE, 'AbortError')
        )
        expect(logic.values.queryError).toBeNull()
    })

    // The filter bar's property filters must translate into the backend's Prometheus-style
    // matchers: operator mapping, multi-value alternation (with regex escaping), and skipping
    // chips that are still being edited. A bad mapping silently filters the chart wrong.
    it.each([
        [
            'exact -> eq',
            { key: 'env', operator: PropertyOperator.Exact, value: ['prod'] },
            { key: 'env', op: 'eq', value: 'prod' },
        ],
        [
            'is_not -> neq',
            { key: 'env', operator: PropertyOperator.IsNot, value: ['prod'] },
            { key: 'env', op: 'neq', value: 'prod' },
        ],
        [
            'regex -> regex',
            { key: 'svc', operator: PropertyOperator.Regex, value: ['checkout.*'] },
            { key: 'svc', op: 'regex', value: 'checkout.*' },
        ],
        [
            'not_regex -> not_regex',
            { key: 'path', operator: PropertyOperator.NotRegex, value: ['/health'] },
            { key: 'path', op: 'not_regex', value: '/health' },
        ],
        [
            'multi-value exact -> anchored, escaped regex',
            { key: 'pod', operator: PropertyOperator.Exact, value: ['api.1', 'api.2'] },
            { key: 'pod', op: 'regex', value: '^(?:api\\.1|api\\.2)$' },
        ],
        [
            'multi-value is_not -> anchored not_regex',
            { key: 'pod', operator: PropertyOperator.IsNot, value: ['a', 'b'] },
            { key: 'pod', op: 'not_regex', value: '^(?:a|b)$' },
        ],
    ])('maps filter bar chip (%s) to a backend matcher', (_name, propertyFilter, expected) => {
        logic.actions.setFilterGroup(filterGroupWith([propertyFilter]))
        expect(logic.values.queryFilters).toEqual([expected])
    })

    it('skips chips that are still being edited or use unsupported operators', () => {
        logic.actions.setFilterGroup(
            filterGroupWith([
                { key: 'env', operator: PropertyOperator.Exact, value: [] }, // value not picked yet
                { key: '', operator: PropertyOperator.Exact, value: ['x'] }, // no key
                { key: 'env', operator: PropertyOperator.IContains, value: ['pr'] }, // unsupported operator
                { key: 'env', operator: PropertyOperator.Exact, value: ['prod'] },
            ])
        )
        expect(logic.values.queryFilters).toEqual([{ key: 'env', op: 'eq', value: 'prod' }])
    })

    // The group-by picker shipped with `options={[]}` and never fetched, so it offered no
    // attribute keys. Typing must query the attributes endpoint (scoped by search) and map
    // `{ name }` rows into `{ key, label }` options.
    it('group-by search fetches attribute keys and maps them into options', async () => {
        jest.mocked(metricsAttributesRetrieve).mockResolvedValue({
            results: [{ name: 'env' }, { name: 'service_name' }],
            count: 2,
        })
        await expectLogic(logic, () => {
            logic.actions.setGroupBySearch('e')
        }).toDispatchActions(['loadAttributeKeyOptions', 'loadAttributeKeyOptionsSuccess'])
        expect(metricsAttributesRetrieve).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ search: 'e' })
        )
        expect(logic.values.attributeKeyOptions).toEqual([
            { key: 'env', label: 'env' },
            { key: 'service_name', label: 'service_name' },
        ])
    })
})
