import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { buildLogScopeFilter, logsDeepLinkUrl, type TraceLogScope } from './traceLogScope'

const ids = { traceId: 'trace-abc', spanId: 'span-xyz' }
const dateRange = { date_from: '2026-06-11T07:00:00.000Z', date_to: '2026-06-11T09:00:00.000Z' }

describe('traceLogScope', () => {
    it.each<[TraceLogScope, string, string]>([
        ['span', 'span_id', 'span-xyz'],
        ['trace', 'trace_id', 'trace-abc'],
    ])('pins the embedded viewer for scope=%s to %s=%s', (scope, key, value) => {
        expect(buildLogScopeFilter(scope, ids)).toEqual({
            type: FilterLogicalOperator.And,
            values: [{ key, type: PropertyFilterType.Log, operator: PropertyOperator.Exact, value: [value] }],
        })
    })

    it('builds a Logs deep link with a two-level filter group and the time window', () => {
        const url = logsDeepLinkUrl('trace', ids, dateRange)
        expect(url.startsWith('/logs?')).toBe(true)

        const params = new URLSearchParams(url.slice(url.indexOf('?') + 1))
        expect(JSON.parse(params.get('filterGroup')!)).toEqual({
            type: 'AND',
            values: [
                {
                    type: 'AND',
                    values: [
                        {
                            key: 'trace_id',
                            type: 'log',
                            operator: 'exact',
                            value: ['trace-abc'],
                        },
                    ],
                },
            ],
        })
        expect(JSON.parse(params.get('dateRange')!)).toEqual(dateRange)
    })
})
