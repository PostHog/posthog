import { combineUrl } from 'kea-router'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { buildTraceLogsUrl } from './logsLink'

describe('buildTraceLogsUrl', () => {
    const url = buildTraceLogsUrl('deadbeef', '2024-01-01T12:00:00.000Z')
    // Decode the way the Logs scene reads its params (kea-router JSON-decodes object params).
    const { pathname, searchParams } = combineUrl(url)

    it('targets the logs scene', () => {
        expect(pathname).toEqual('/logs')
    })

    it('filters by the trace id as a LOG-type exact filter', () => {
        expect(searchParams.filterGroup).toEqual({
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
        expect(searchParams.dateRange).toEqual({
            date_from: '2024-01-01T11:55:00.000Z',
            date_to: '2024-01-01T12:05:00.000Z',
        })
    })
})
