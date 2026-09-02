import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { DEFAULT_DATE_RANGE } from './components/LogsViewer/Filters/logsViewerFiltersLogic'
import { logsQueryToViewerFilters } from './logsAgentContext'

describe('logsAgentContext', () => {
    const innerValues = (filterGroup: UniversalFiltersGroup): any[] =>
        (filterGroup.values[0] as UniversalFiltersGroup).values

    it('unwraps the query object and mirrors date range and search term', () => {
        const result = logsQueryToViewerFilters({
            query: { dateRange: { date_from: '-6h' }, searchTerm: 'connection refused' },
        })

        expect(result.dateRange).toEqual({ date_from: '-6h' })
        expect(result.searchTerm).toBe('connection refused')
    })

    it('falls back to the default date range and empty search when omitted', () => {
        const result = logsQueryToViewerFilters({ query: {} })

        expect(result.dateRange).toEqual(DEFAULT_DATE_RANGE)
        expect(result.searchTerm).toBe('')
    })

    it('accepts a raw input that is not wrapped in a query object', () => {
        const result = logsQueryToViewerFilters({ dateRange: { date_from: '-1d' } })

        expect(result.dateRange).toEqual({ date_from: '-1d' })
    })

    it('defaults type and operator on raw agent filters that omit them', () => {
        const result = logsQueryToViewerFilters({
            query: { filterGroup: [{ key: 'http.status_code', value: '500' }] },
        })

        expect(innerValues(result.filterGroup!)).toEqual([
            {
                key: 'http.status_code',
                value: '500',
                type: PropertyFilterType.LogAttribute,
                operator: PropertyOperator.Exact,
            },
        ])
    })

    it('preserves an explicit type and operator on a raw filter', () => {
        const result = logsQueryToViewerFilters({
            query: {
                filterGroup: [{ key: 'message', value: 'timeout', type: 'log', operator: 'icontains' }],
            },
        })

        expect(innerValues(result.filterGroup!)[0]).toMatchObject({
            key: 'message',
            operator: 'icontains',
            type: 'log',
        })
    })

    it('folds service names and severity levels into the filter group', () => {
        const result = logsQueryToViewerFilters({
            query: { serviceNames: ['api-gateway'], severityLevels: ['error', 'fatal'] },
        })

        const serialized = JSON.stringify(result.filterGroup)
        expect(serialized).toContain('api-gateway')
        expect(serialized).toContain('error')
        expect(serialized).toContain('fatal')
    })

    it('drops severity values outside the canonical buckets', () => {
        const result = logsQueryToViewerFilters({
            query: { severityLevels: ['error', 'ERROR', 'nonsense'] },
        })

        const serialized = JSON.stringify(result.filterGroup)
        expect(serialized).toContain('error')
        expect(serialized).not.toContain('nonsense')
    })

    it('produces the empty default group when no filters are given', () => {
        const result = logsQueryToViewerFilters({ query: {} })

        expect(result.filterGroup).toEqual({
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values: [] }],
        })
    })
})
