import type { WebQueryResponseApi } from '@/api/webAnalytics'

import { webActiveHoursSnapshot, webBreakdownSnapshot } from './webAnalytics'

const READ_AT = Date.parse('2026-10-14T12:00:00Z')

function good(extra: WebQueryResponseApi): WebQueryResponseApi {
    return { last_refresh: '2026-10-14T11:58:00Z', is_cached: true, ...extra }
}

describe('web analytics adapters', () => {
    test.each([
        [
            'a stats table with a bounce rate column between the counts',
            [
                'context.columns.breakdown_value',
                'context.columns.visitors',
                'context.columns.bounce_rate',
                'context.columns.views',
                'context.columns.ui_fill_fraction',
                'context.columns.cross_sell',
            ],
            [['/pricing', [412, 380], [0.41, 0.44], [455, 401], 1, '']],
            'Views',
        ],
        [
            'the outbound clicks table',
            ['context.columns.url', 'context.columns.visitors', 'context.columns.clicks'],
            [['https://example.com/', [412, 380], [455, 401]]],
            'Clicks',
        ],
    ])('reads %s by column name', (_name, columns, results, secondaryLabel) => {
        const snapshot = webBreakdownSnapshot('Page', good({ columns, results }), undefined, READ_AT)

        expect(snapshot.secondaryLabel).toBe(secondaryLabel)
        expect(snapshot.rows.map(({ value, previous, secondary }) => ({ value, previous, secondary }))).toEqual([
            { value: 412, previous: 380, secondary: 455 },
        ])
    })

    test('a rate-limited table answer keeps the rows on screen and marks them stale', () => {
        const first = webBreakdownSnapshot(
            'Country',
            good({
                columns: ['context.columns.breakdown_value', 'context.columns.visitors', 'context.columns.views'],
                results: [['US', [10, 8], [30, 20]]],
            }),
            undefined,
            READ_AT
        )
        const next = webBreakdownSnapshot(
            'Country',
            {
                results: null,
                last_refresh: '2026-10-14T12:01:00Z',
                query_status: { error: true, error_code: 'rate_limited' },
            },
            first,
            READ_AT + 60_000
        )

        expect(next).toMatchObject({ rows: first.rows, lastRefreshAt: first.lastRefreshAt, refreshFailed: true })
    })

    test('active hours put ISO weekdays Monday first and keep the unique total', () => {
        const snapshot = webActiveHoursSnapshot(
            good({
                timezone: 'Europe/Berlin',
                results: [
                    {
                        calendar_heatmap_data: {
                            data: [
                                { row: 1, column: 0, value: 4 },
                                { row: 7, column: 23, value: 9 },
                            ],
                            allAggregations: 11,
                        },
                    },
                ],
            }),
            undefined,
            READ_AT
        )

        expect(snapshot.cells[0]?.[0]).toBe(4)
        expect(snapshot.cells[6]?.[23]).toBe(9)
        expect(snapshot.total).toBe(11)
        expect(snapshot.timezone).toBe('Europe/Berlin')
    })
})
