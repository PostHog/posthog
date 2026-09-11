import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/constants'

import { PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { DEFAULT_DATE_FROM } from './components/metricsViewerLogic'
import { metricsQueryToViewerState } from './metricsAgentContext'

describe('metricsAgentContext', () => {
    const innerValues = (filterGroup: UniversalFiltersGroup): any[] =>
        (filterGroup.values[0] as UniversalFiltersGroup).values

    it('maps the single-metric shorthand onto one clause', () => {
        const result = metricsQueryToViewerState({
            query: {
                metricName: 'http_requests_total',
                aggregation: 'rate',
                groupBy: [{ key: 'service_name' }, { key: 'http_status' }],
                dateFrom: '2026-09-08T00:00:00Z',
                dateTo: '2026-09-09T00:00:00Z',
            },
        })

        expect(result?.clauses).toHaveLength(1)
        expect(result?.clauses[0]).toMatchObject({
            name: 'a',
            metricName: 'http_requests_total',
            aggregation: 'rate',
            aggregationExplicitlySet: true,
            groupByKeys: ['service_name', 'http_status'],
        })
        expect(result?.dateFrom).toBe('2026-09-08T00:00:00Z')
        expect(result?.dateTo).toBe('2026-09-09T00:00:00Z')
    })

    it('accepts a raw input that is not wrapped in a query object', () => {
        const result = metricsQueryToViewerState({ metricName: 'process_cpu_seconds' })

        expect(result?.clauses[0].metricName).toBe('process_cpu_seconds')
    })

    it('falls back to the default window when no dates are given', () => {
        const result = metricsQueryToViewerState({ query: { metricName: 'up' } })

        expect(result?.dateFrom).toBe(DEFAULT_DATE_FROM)
        expect(result?.dateTo).toBeNull()
    })

    it('turns label matchers into filter bar chips', () => {
        const result = metricsQueryToViewerState({
            query: {
                metricName: 'up',
                filters: [
                    { key: 'service_name', op: 'eq', value: 'api-gateway' },
                    { key: 'pod', op: 'not_regex', value: '^canary-' },
                ],
            },
        })

        expect(innerValues(result!.clauses[0].filterGroup)).toEqual([
            {
                type: PropertyFilterType.MetricAttribute,
                key: 'service_name',
                value: ['api-gateway'],
                operator: PropertyOperator.Exact,
            },
            {
                type: PropertyFilterType.MetricAttribute,
                key: 'pod',
                value: ['^canary-'],
                operator: PropertyOperator.NotRegex,
            },
        ])
    })

    it('leaves the filter bar empty when the query narrowed nothing', () => {
        const result = metricsQueryToViewerState({ query: { metricName: 'up' } })

        expect(result?.clauses[0].filterGroup).toEqual(DEFAULT_UNIVERSAL_GROUP_FILTER)
    })

    it('keeps the formula and its clause aliases together', () => {
        const result = metricsQueryToViewerState({
            query: {
                clauses: [
                    { name: 'a', metricName: 'errors_total', aggregation: 'increase' },
                    { name: 'b', metricName: 'requests_total', aggregation: 'increase' },
                ],
                formula: 'a / b',
            },
        })

        expect(result?.clauses.map((clause) => clause.name)).toEqual(['a', 'b'])
        expect(result?.formula).toBe('a / b')
    })

    it('drops a formula whose clauses did not all survive the mapping', () => {
        const result = metricsQueryToViewerState({
            query: {
                clauses: [{ name: 'a', metricName: 'errors_total' }, { name: 'b' }],
                formula: 'a / b',
            },
        })

        expect(result?.clauses).toHaveLength(1)
        expect(result?.formula).toBe('')
    })

    it('shows a quantile aggregation as the p95 the clause row can express', () => {
        const result = metricsQueryToViewerState({
            query: { metricName: 'request_duration', aggregation: 'histogram_quantile', quantile: 0.99 },
        })

        expect(result?.clauses[0].aggregation).toBe('p95')
    })

    it('returns null when the call named no metric, so the open chart survives', () => {
        expect(metricsQueryToViewerState({ query: { dateFrom: '-1h' } })).toBeNull()
        expect(metricsQueryToViewerState({ query: { clauses: [] } })).toBeNull()
    })
})
