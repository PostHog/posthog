import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { apmSpansQueryToViewerFilters, apmTraceGetToTraceId } from './tracingAgentContext'
import { DEFAULT_DATE_RANGE } from './tracingFiltersLogic'

describe('tracingAgentContext', () => {
    const innerValues = (filterGroup: UniversalFiltersGroup): any[] =>
        (filterGroup.values[0] as UniversalFiltersGroup).values

    describe('apmSpansQueryToViewerFilters', () => {
        it('unwraps the query object and mirrors date range, services, sort and view mode', () => {
            const result = apmSpansQueryToViewerFilters({
                query: {
                    dateRange: { date_from: '-6h' },
                    serviceNames: ['api-gateway'],
                    orderBy: 'duration',
                    orderDirection: 'ASC',
                    flatSpans: true,
                },
            })

            expect(result).toMatchObject({
                dateRange: { date_from: '-6h' },
                serviceNames: ['api-gateway'],
                orderBy: 'duration',
                orderDirection: 'ASC',
                viewMode: 'spans',
            })
        })

        it('resets omitted fields to the viewer defaults', () => {
            const result = apmSpansQueryToViewerFilters({ query: {} })

            expect(result).toEqual({
                dateRange: DEFAULT_DATE_RANGE,
                serviceNames: [],
                filterGroup: {
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.And, values: [] }],
                },
                orderBy: 'timestamp',
                orderDirection: 'DESC',
                viewMode: 'traces',
            })
        })

        it('accepts a raw input that is not wrapped in a query object', () => {
            const result = apmSpansQueryToViewerFilters({ dateRange: { date_from: '-1d' } })

            expect(result.dateRange).toEqual({ date_from: '-1d' })
        })

        it('defaults type and operator on raw agent filters that omit them', () => {
            const result = apmSpansQueryToViewerFilters({
                query: { filterGroup: [{ key: 'http.method', value: 'POST' }] },
            })

            expect(innerValues(result.filterGroup!)).toEqual([
                {
                    key: 'http.method',
                    value: 'POST',
                    type: PropertyFilterType.SpanAttribute,
                    operator: PropertyOperator.Exact,
                },
            ])
        })

        it('preserves an explicit type and operator on a raw filter', () => {
            const result = apmSpansQueryToViewerFilters({
                query: { filterGroup: [{ key: 'duration', value: '1000000000', type: 'span', operator: 'gt' }] },
            })

            expect(innerValues(result.filterGroup!)[0]).toMatchObject({ key: 'duration', type: 'span', operator: 'gt' })
        })

        it.each([
            ['statusCodes', { statusCodes: [2, '1'] }, { key: 'status_code', value: ['2', '1'] }],
            ['traceId', { traceId: 'abc123' }, { key: 'trace_id', value: ['abc123'] }],
        ])('folds %s into the filter group as a span column filter', (_name, query, expected) => {
            const result = apmSpansQueryToViewerFilters({ query })

            expect(innerValues(result.filterGroup!)).toEqual([
                { type: PropertyFilterType.Span, operator: PropertyOperator.Exact, ...expected },
            ])
        })

        // rootSpans has no viewer facet: the span list never sends it and the backend reads an
        // omitted value as false, so the mode the mirror picks stays a flatSpans question.
        it.each([
            ['rootSpans is false', { rootSpans: false }, 'traces'],
            ['rootSpans is true', { rootSpans: true }, 'traces'],
            ['flatSpans comes along with rootSpans', { rootSpans: true, flatSpans: true }, 'spans'],
        ])('leaves the view mode to flatSpans when %s', (_name, query, expected) => {
            expect(apmSpansQueryToViewerFilters({ query }).viewMode).toBe(expected)
        })

        it('ignores an orderBy the viewer cannot sort by', () => {
            const result = apmSpansQueryToViewerFilters({ query: { orderBy: 'latest' } })

            expect(result.orderBy).toBe('timestamp')
        })
    })

    describe('apmTraceGetToTraceId', () => {
        it.each([
            ['a 32-char hex id', '0123456789abcdef0123456789ABCDEF', '0123456789abcdef0123456789ABCDEF'],
            ['a short id', 'abc123', null],
            ['a non-hex id', 'g123456789abcdef0123456789abcdef', null],
            ['a missing id', undefined, null],
        ])('returns %s as %p', (_name, traceId, expected) => {
            expect(apmTraceGetToTraceId({ trace_id: traceId })).toBe(expected)
        })
    })
})
