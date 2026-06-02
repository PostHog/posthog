import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { buildTraceLogsFilters } from './logsLink'

describe('buildTraceLogsFilters', () => {
    const filters = buildTraceLogsFilters('deadbeef', '2024-01-01T12:00:00.000Z')

    it('filters by the trace id as a LOG-type exact filter', () => {
        expect(filters.filterGroup).toEqual({
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            key: 'trace_id',
                            value: ['deadbeef'],
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Log,
                        },
                    ],
                },
            ],
        })
    })

    it('scopes the date range to ±5 minutes around the span timestamp', () => {
        expect(filters.dateRange).toEqual({
            date_from: '2024-01-01T11:55:00.000Z',
            date_to: '2024-01-01T12:05:00.000Z',
        })
    })
})
