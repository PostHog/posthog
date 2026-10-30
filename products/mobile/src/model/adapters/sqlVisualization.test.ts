import type { SqlCell, SqlTableView } from '../views'
import {
    effectiveSqlDisplay,
    sqlAxes,
    sqlColumns,
    sqlInterval,
    sqlRankingView,
    sqlResultDisplay,
    sqlScalar,
    sqlSeriesViews,
    sqlTableView,
} from './sqlVisualization'

function sql(extra: Record<string, unknown> = {}): Record<string, unknown> {
    return { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'select 1' }, ...extra }
}

function table(types: [string, string][], rows: SqlCell[][], query: unknown = sql()): SqlTableView {
    const view = sqlTableView(query, { result: rows, columns: types.map(([name]) => name), types })
    if (!view) {
        throw new Error('not a SQL table')
    }
    return view
}

const DAILY: [string, string][] = [
    ['day', 'Date'],
    ['signups', 'UInt64'],
    ['activations', 'Nullable(UInt64)'],
]

describe('sqlVisualization', () => {
    test.each<[string, string, string]>([
        ['a nullable integer', 'Nullable(UInt64)', 'INTEGER'],
        ['a low-cardinality nullable string', 'LowCardinality(Nullable(String))', 'STRING'],
        ['a DateTime64 with a timezone', "DateTime64(6, 'UTC')", 'DATETIME'],
        ['a nullable date', 'Nullable(Date32)', 'DATE'],
        ['a decimal', 'Decimal(18, 2)', 'DECIMAL'],
        ['a boolean', 'Bool', 'BOOLEAN'],
        ['an array of strings', 'Array(String)', 'ARRAY'],
    ])('reads %s as its scalar', (_name, type, scalar) => {
        expect(sqlScalar(type)).toBe(scalar)
    })

    test('builds the table with cell formats, stringified objects and the cut-off flag', () => {
        const query = sql({
            tableSettings: { columns: [{ column: 'views', settings: { formatting: { style: 'number' } } }] },
        })

        const view = sqlTableView(query, {
            result: [['/pricing', 12, { a: 1 }]],
            columns: ['page', 'views', 'extra'],
            types: [
                ['page', 'String'],
                ['views', 'UInt64'],
                ['extra', 'Map(String, UInt8)'],
            ],
            hasMore: true,
        })

        expect(view).toMatchObject({
            columns: [
                { name: 'page', scalar: 'STRING', isNumerical: false, isDate: false, format: null },
                { name: 'views', isNumerical: true, format: { kind: 'sql', style: 'number', prefix: '' } },
                { name: 'extra' },
            ],
            rows: [['/pricing', 12, '{"a":1}']],
            hasMore: true,
        })
    })

    test.each<[string, [string, string][], SqlCell[][], string]>([
        [
            'dates and numbers over several rows',
            DAILY,
            [
                ['2026-10-01', 1, 2],
                ['2026-10-02', 3, 4],
            ],
            'ActionsLineGraph',
        ],
        [
            'two strings and a number',
            [
                ['browser', 'String'],
                ['os', 'String'],
                ['n', 'UInt64'],
            ],
            [['Chrome', 'Mac', 3]],
            'TwoDimensionalHeatmap',
        ],
        ['one number column', [['count()', 'UInt64']], [[312]], 'BoldNumber'],
        ['one date row', DAILY, [['2026-10-01', 1, 2]], 'ActionsBar'],
        [
            'no number column',
            [
                ['email', 'String'],
                ['plan', 'String'],
            ],
            [['a@example.com', 'free']],
            'ActionsTable',
        ],
    ])('resolves Auto for %s', (_name, types, rows, display) => {
        expect(effectiveSqlDisplay(sql({ display: 'Auto' }), table(types, rows))).toBe(display)
    })

    test.each<[string, Record<string, unknown>, string | null, string[]]>([
        ['the first date column and every number', {}, 'day', ['signups', 'activations']],
        [
            'the saved axes',
            { chartSettings: { xAxis: { column: 'day' }, yAxis: [{ column: 'activations' }] } },
            'day',
            ['activations'],
        ],
        [
            'every number except the breakdown column',
            { chartSettings: { seriesBreakdownColumn: 'activations' } },
            'day',
            ['signups'],
        ],
        [
            'the defaults when the saved x column is gone',
            { chartSettings: { xAxis: { column: 'week' }, yAxis: [{ column: 'activations' }] } },
            'day',
            ['signups', 'activations'],
        ],
        [
            'the defaults when a saved y column is not a number',
            { chartSettings: { xAxis: { column: 'signups' }, yAxis: [{ column: 'day' }] } },
            'day',
            ['signups', 'activations'],
        ],
    ])('picks %s as the axes', (_name, extra, x, y) => {
        const axes = sqlAxes(sql(extra), sqlColumns(['day', 'signups', 'activations'], DAILY, sql(extra)))

        expect([axes.x?.name ?? null, axes.y.map((column) => column.name)]).toEqual([x, y])
    })

    test('picks the first text column as x when there is no date', () => {
        const types: [string, string][] = [
            ['n', 'UInt64'],
            ['plan', 'String'],
        ]

        expect(sqlAxes(sql(), sqlColumns(['n', 'plan'], types, sql())).x?.name).toBe('plan')
    })

    test('gives every series a point per date in date order, with a gap where a value is missing', () => {
        const rows: SqlCell[][] = [
            ['2026-10-02', 3, null],
            ['2026-10-01', 1, 2],
        ]

        const series = sqlSeriesViews(sql({ display: 'ActionsLineGraph' }), table(DAILY, rows))

        expect(series.map((item) => [item.label, item.points.map((point) => [point.at, point.value])])).toEqual([
            [
                'signups',
                [
                    ['2026-10-01', 1],
                    ['2026-10-02', 3],
                ],
            ],
            [
                'activations',
                [
                    ['2026-10-01', 2],
                    ['2026-10-02', Number.NaN],
                ],
            ],
        ])
    })

    test('splits a breakdown column into one aligned series per value', () => {
        const types: [string, string][] = [
            ['day', 'Date'],
            ['plan', 'String'],
            ['n', 'UInt64'],
        ]
        const query = sql({ display: 'ActionsBar', chartSettings: { seriesBreakdownColumn: 'plan' } })
        const rows: SqlCell[][] = [
            ['2026-10-01', 'free', 5],
            ['2026-10-01', 'paid', 2],
            ['2026-10-02', 'free', 7],
        ]

        const series = sqlSeriesViews(query, table(types, rows, query))

        expect(
            series.map((item) => [item.label, item.breakdownValue, item.points.map((point) => point.value)])
        ).toEqual([
            ['free', 'free', [5, 7]],
            ['paid', 'paid', [2, Number.NaN]],
        ])
    })

    test('draws a cumulative display as a running sum per series', () => {
        const rows: SqlCell[][] = [
            ['2026-10-01', 1, 2],
            ['2026-10-02', 3, 4],
            ['2026-10-03', 5, 6],
        ]

        const series = sqlSeriesViews(sql({ display: 'ActionsLineGraphCumulative' }), table(DAILY, rows))

        expect(series.map((item) => item.points.map((point) => point.value))).toEqual([
            [1, 4, 9],
            [2, 6, 12],
        ])
    })

    test.each<[string, string[], string]>([
        ['hours', ['2026-10-01 00:00:00', '2026-10-01 01:00:00', '2026-10-01 02:00:00'], 'hour'],
        ['days', ['2026-10-01', '2026-10-02', '2026-10-03'], 'day'],
        ['weeks', ['2026-09-28', '2026-10-05', '2026-10-12'], 'week'],
        ['months', ['2026-08-01', '2026-09-01', '2026-10-01'], 'month'],
    ])('infers %s from the dates', (_name, dates, interval) => {
        expect(sqlInterval(dates.map((at) => ({ at })))).toBe(interval)
    })

    test('ranks bar values in the server order with their sum', () => {
        const types: [string, string][] = [
            ['plan', 'String'],
            ['mrr', 'Float64'],
        ]
        const query = sql({ display: 'ActionsBarValue' })
        const rows: SqlCell[][] = [
            ['Starter', 3000],
            ['Enterprise', 48_000],
            ['Teams', 12_000],
        ]

        expect(sqlRankingView(query, table(types, rows, query))).toEqual({
            rows: [
                { key: '0:Starter', label: 'Starter', value: 3000 },
                { key: '1:Enterprise', label: 'Enterprise', value: 48_000 },
                { key: '2:Teams', label: 'Teams', value: 12_000 },
            ],
            total: 63_000,
        })
    })

    test.each<[string, Record<string, unknown>, SqlCell[][], string]>([
        ['a bar chart over dates', { display: 'ActionsBar' }, [['2026-10-01', 1, 2]], 'chart'],
        [
            'a line chart over text',
            { display: 'ActionsLineGraph', chartSettings: { xAxis: { column: 'signups' } } },
            [],
            'web',
        ],
        ['a transposed table', { display: 'ActionsTable', tableSettings: { transpose: true } }, [], 'web'],
        ['a scatter plot', { display: 'ScatterPlot' }, [], 'web'],
        ['a metric, which the phone does not port', { display: 'Metric' }, [], 'web'],
        [
            'a query without a display as a table, as on the web',
            {},
            [
                ['2026-10-01', 1, 2],
                ['2026-10-02', 3, 4],
            ],
            'table',
        ],
    ])('shows %s as its phone display', (_name, extra, rows, display) => {
        expect(sqlResultDisplay(sql(extra), table(DAILY, rows, sql(extra)))).toBe(display)
    })

    test.each<[string, string, string]>([
        ['a bar chart over text as ranked bars', 'ActionsBar', 'bars'],
        ['a pie of two y columns on the web', 'ActionsPie', 'web'],
    ])('shows %s', (_name, display, expected) => {
        const types: [string, string][] = [
            ['plan', 'String'],
            ['n', 'UInt64'],
            ['m', 'UInt64'],
        ]
        const yAxis = display === 'ActionsBar' ? [{ column: 'n' }] : [{ column: 'n' }, { column: 'm' }]
        const query = sql({ display, chartSettings: { yAxis } })

        expect(sqlResultDisplay(query, table(types, [['free', 1, 2]], query))).toBe(expected)
    })

    test.each<[string, string, string]>([
        ['a UTC datetime', '2026-10-01T00:00:00Z', '2026-10-01 00:00:00'],
        ['a DateTime64 with an offset', '2026-10-01T14:05:09.123456-04:00', '2026-10-01 14:05:09'],
    ])('keeps the wall clock of %s as the point date', (_name, cell, at) => {
        const types: [string, string][] = [
            ['hour', "DateTime64(6, 'UTC')"],
            ['n', 'UInt64'],
        ]
        const query = sql({ display: 'ActionsLineGraph' })

        const series = sqlSeriesViews(query, table(types, [[cell, 5]], query))

        expect(series[0]?.points).toEqual([{ at, value: 5 }])
    })

    test('keys a NULL breakdown value apart from an empty one', () => {
        const types: [string, string][] = [
            ['day', 'Date'],
            ['plan', 'Nullable(String)'],
            ['n', 'UInt64'],
        ]
        const query = sql({ display: 'ActionsLineGraph', chartSettings: { seriesBreakdownColumn: 'plan' } })
        const rows: SqlCell[][] = [
            ['2026-10-01', null, 1],
            ['2026-10-01', '', 2],
        ]

        const keys = sqlSeriesViews(query, table(types, rows, query)).map((series) => series.key)

        expect(new Set(keys).size).toBe(2)
    })

    test('reads numbers sent as strings, and leaves other text as a gap', () => {
        const rows: SqlCell[][] = [
            ['2026-10-01', '12.5', 'n/a'],
            ['2026-10-02', 3, '0x10'],
        ]
        const bars = sql({ display: 'ActionsBarValue' })
        const types: [string, string][] = [
            ['plan', 'String'],
            ['mrr', 'Decimal(18, 2)'],
        ]

        const series = sqlSeriesViews(sql({ display: 'ActionsLineGraph' }), table(DAILY, rows))
        const ranking = sqlRankingView(
            bars,
            table(
                types,
                [
                    ['Teams', '3000.50'],
                    ['Free', 'n/a'],
                ],
                bars
            )
        )

        expect(series.map((item) => item.points.map((point) => point.value))).toEqual([
            [12.5, 3],
            [Number.NaN, Number.NaN],
        ])
        expect(ranking?.rows.map((row) => [row.label, row.value])).toEqual([['Teams', 3000.5]])
    })
})
