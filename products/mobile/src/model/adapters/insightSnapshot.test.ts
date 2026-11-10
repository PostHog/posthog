import type { InsightApi } from '@/api/insights'
import { DEMO_SQL_INSIGHTS } from '@/demo/sqlCharts'
import { splitTilesByEligibility } from '@/features/views/list/tileEligibility'
import { pointActorsInput } from '@/features/views/pointSheet/pointActorsInput'
import {
    insightDisplay,
    insightRenderState,
    noDataText,
    pinRangeLabel,
    queryDisplay,
    snapshotBarLayout,
    snapshotChartSeries,
    snapshotFormatter,
} from '@/features/views/snapshotChart'
import { chartAxes } from '@/ui/chart/chartAxes'
import { chartGeometry } from '@/ui/chart/chartGeometry'
import { rangeContent, tooltipContent, tooltipPoint } from '@/ui/chart/chartSeries'
import { themes } from '@/ui/theme'
import { dashboardView } from './dashboardView'

import { insightSnapshot, numberParts, usesOwnRange } from './insightSnapshot'

const NOW = Date.parse('2026-10-14T12:00:00Z')

function trends(math: string | undefined, display = 'ActionsLineGraph', extra: Record<string, unknown> = {}): unknown {
    return {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            interval: 'day',
            series: [{ kind: 'EventsNode', event: '$pageview', ...(math ? { math } : {}) }],
            trendsFilter: { display },
            dateRange: { date_from: '-7d' },
            ...extra,
        },
    }
}

function insight(overrides: Partial<InsightApi>): InsightApi {
    return {
        id: 7,
        short_id: 'abc123',
        name: 'Signups',
        derived_name: null,
        query: trends(undefined),
        result: [],
        last_refresh: '2026-10-14T11:00:00Z',
        cache_target_age: '2026-10-14T17:00:00Z',
        next_allowed_client_refresh: '2026-10-14T11:15:00Z',
        is_cached: true,
        // The window reaches the end of today, so the last bucket is in progress.
        resolved_date_range: { date_from: '2026-10-11T00:00:00Z', date_to: '2026-10-14T23:59:59Z' },
        ...overrides,
    }
}

const DAYS = ['2026-10-11', '2026-10-12', '2026-10-13', '2026-10-14']
const CONTEXT = { readAt: 1000, serverNow: NOW }

function viz(source: Record<string, unknown>): unknown {
    return { kind: 'InsightVizNode', source }
}

const FUNNEL = viz({ kind: 'FunnelsQuery', series: [] })
const RETENTION = viz({ kind: 'RetentionQuery', retentionFilter: { period: 'Week' } })
const COHORT_ROW = { date: '2026-10-05T00:00:00Z', values: [{ count: 10 }] }

function sqlInsight(extra: Record<string, unknown>, types: [string, string][], result: unknown): Partial<InsightApi> {
    return {
        query: { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'select 1' }, ...extra },
        columns: types.map(([name]) => name),
        types,
        hasMore: false,
        result,
    }
}

const SQL_DAILY: [string, string][] = [
    ['day', 'Date'],
    ['signups', 'UInt64'],
]
const SQL_PLANS: [string, string][] = [
    ['plan', 'String'],
    ['mrr', 'Float64'],
]

describe('insightSnapshot', () => {
    test.each<[string, Record<string, unknown>, number, string]>([
        ['prefix and suffix', { prefix: '£', suffix: 'M', decimalPlaces: 2 }, 42.7, '£42.70M'],
        ['percent', { style: 'percent', decimalPlaces: 2 }, 0.12375, '12.38%'],
        ['grouped number', { style: 'number', decimalPlaces: 2 }, 12345.6, '12,345.60'],
        ['short number', { style: 'short', prefix: '$' }, 2345678, '$2.35\u00a0M'],
        ['raw number', { style: 'none' }, 12345.6789, '12345.6789'],
        ['zero precision', { style: 'number', decimalPlaces: 0, suffix: ' users' }, 1234.6, '1,235 users'],
        ['negative number', { prefix: '$', decimalPlaces: 2 }, -24.5, '$-24.50'],
        ['zero', { style: 'percent', decimalPlaces: 1 }, 0, '0.0%'],
        ['default precision', {}, 0.123456, '0.123456'],
        ['invalid precision', { style: 'number', decimalPlaces: -1 }, 1234.5678, '1,234.568'],
    ])('preserves SQL big number formatting: %s', (_name, formatting, value, expected) => {
        const snapshot = insightSnapshot(
            insight({
                query: {
                    kind: 'DataVisualizationNode',
                    display: 'BoldNumber',
                    source: { kind: 'HogQLQuery', query: 'select 1 as value' },
                    tableSettings: {
                        columns: [
                            { column: 'other', settings: { formatting: { prefix: 'wrong' } } },
                            { column: 'value', settings: { formatting } },
                        ],
                    },
                },
                columns: ['value'],
                result: [[value]],
            }),
            undefined,
            CONTEXT
        )

        expect(snapshotFormatter(snapshot)(snapshot.value as number)).toBe(expected)
    })

    test.each<[string, Record<string, unknown>, number, string]>([
        [
            'custom units',
            { aggregationAxisPrefix: '$', aggregationAxisPostfix: 'M', decimalPlaces: 2 },
            42.756,
            '$42.76M',
        ],
        ['minimum precision', { decimalPlaces: 3, minDecimalPlaces: 2 }, 12.3, '12.30'],
        ['percentage', { aggregationAxisFormat: 'percentage', decimalPlaces: 2 }, 12.375, '12.38%'],
        ['scaled percentage', { aggregationAxisFormat: 'percentage_scaled', decimalPlaces: 2 }, 0.12375, '12.38%'],
        ['short number', { aggregationAxisFormat: 'short' }, 2345678, '2.35\u00a0M'],
        ['currency', { aggregationAxisFormat: 'currency', aggregationAxisPrefix: '$' }, 1234.5, '$1,234.50'],
        ['small values', {}, 0.001234, '0.0012'],
        ['seconds', { aggregationAxisFormat: 'duration' }, 3.125, '3.13s'],
        ['milliseconds', { aggregationAxisFormat: 'duration_ms' }, 3.125, '3.13ms'],
        ['nanoseconds', { aggregationAxisFormat: 'duration_ns' }, 1250, '1.25µs'],
    ])('preserves trends formatting: %s', (_name, formatting, value, expected) => {
        const snapshot = insightSnapshot(
            insight({
                query: trends(undefined, 'BoldNumber', { trendsFilter: { display: 'BoldNumber', ...formatting } }),
                result: [{ aggregated_value: value }],
            }),
            undefined,
            CONTEXT
        )

        expect(snapshotFormatter(snapshot)(snapshot.value as number)).toBe(expected)
    })

    test.each([
        ['ActionsBar', null, 'stacked'],
        ['ActionsStackedBar', null, 'stacked'],
        ['ActionsUnstackedBar', null, 'grouped'],
        ['ActionsBar', 'grouped', 'grouped'],
        ['ActionsUnstackedBar', 'stacked', 'stacked'],
    ] as const)('uses %s with the device preference %s as %s', (display, preferred, expected) => {
        const snapshot = insightSnapshot(insight({ query: trends(undefined, display) }), undefined, CONTEXT)
        expect(snapshotBarLayout(snapshot, preferred)).toBe(expected)
    })

    test.each<[string, Partial<InsightApi>]>([
        [
            'a rate-limited response',
            {
                result: null,
                last_refresh: '2026-10-14T12:00:00Z',
                query_status: { error: true, error_code: 'rate_limited' },
            },
        ],
        ['an error with a result field', { result: [], query_status: { error: true } }],
    ])('keeps the previous freshness and values after %s', (_name, failed) => {
        const good = insightSnapshot(insight({ result: [{ days: DAYS, data: [1, 2, 3, 4] }] }), undefined, CONTEXT)

        const after = insightSnapshot(insight(failed), good, { ...CONTEXT, readAt: 2000 })

        expect(after).toMatchObject({
            lastRefreshAt: '2026-10-14T11:00:00Z',
            nextAllowedRefreshAt: '2026-10-14T11:15:00Z',
            value: good.value,
            readAt: 2000,
            refreshFailed: true,
        })
    })

    test.each<[string, unknown, unknown[], Record<string, unknown>]>([
        [
            'the last complete bucket against the one before it, skipping today',
            trends('dau'),
            [{ days: DAYS, data: [10, 20, 30, 5] }],
            { value: 30, valueAt: '2026-10-13', delta: { previous: 20, basis: 'previous_bucket' } },
        ],
        [
            'window totals of a summable series against the previous period',
            trends(undefined),
            [
                { days: DAYS, data: [1, 2, 3, 4], compare_label: 'current', action: { order: 0 } },
                { days: DAYS, data: [1, 1, 1, 1], compare_label: 'previous', action: { order: 0 } },
            ],
            { value: 10, valueAt: null, delta: { previous: 4, basis: 'compare' } },
        ],
        [
            'distinct users bucket by bucket against the previous period, never a sum',
            trends('weekly_active'),
            [
                { days: DAYS, data: [100, 110, 120, 30], compare_label: 'current', action: { order: 0 } },
                { days: DAYS, data: [90, 95, 100, 98], compare_label: 'previous', action: { order: 0 } },
            ],
            { value: 120, valueAt: '2026-10-13', delta: { previous: 100, basis: 'compare' } },
        ],
        [
            'the server aggregate of a big number',
            trends('dau'),
            [{ aggregated_value: 412, action: { order: 0 } }],
            { value: 412, valueAt: null, delta: null },
        ],
        [
            'ranked breakdown totals with "Other" last and no big number, since no one value stands for the insight',
            trends(undefined, 'ActionsBarValue', { breakdownFilter: { breakdown: '$browser' } }),
            [
                {
                    aggregated_value: 80,
                    label: '$$_posthog_breakdown_other_$$',
                    breakdown_value: '$$_posthog_breakdown_other_$$',
                    action: { order: 0 },
                },
                { aggregated_value: 20, label: 'Safari', breakdown_value: 'Safari', action: { order: 0 } },
                { aggregated_value: 50, label: 'Chrome', breakdown_value: 'Chrome', action: { order: 0 } },
            ],
            {
                value: null,
                delta: null,
                capabilities: { number: false },
                ranking: {
                    rows: [
                        { label: 'Chrome', value: 50 },
                        { label: 'Safari', value: 20 },
                        { label: 'Other', value: 80 },
                    ],
                    total: 150,
                },
            },
        ],
    ])('reads %s', (_name, query, result, expected) => {
        const snapshot = insightSnapshot(insight({ query, result }), undefined, CONTEXT)

        expect(snapshot).toMatchObject(expected)
    })

    test('keeps array breakdown identities distinct and pairs the matching previous period', () => {
        const result = [
            {
                days: DAYS,
                data: [1, 2, 3, 4],
                breakdown_value: ['a', 'b'],
                compare_label: 'current',
                action: { order: 0 },
            },
            {
                days: DAYS,
                data: [5, 6, 7, 8],
                breakdown_value: ['a,b'],
                compare_label: 'current',
                action: { order: 0 },
            },
            {
                days: DAYS,
                data: [9, 10, 11, 12],
                breakdown_value: ['a,b'],
                compare_label: 'previous',
                action: { order: 0 },
            },
            {
                days: DAYS,
                data: [13, 14, 15, 16],
                breakdown_value: ['a', 'b'],
                compare_label: 'previous',
                action: { order: 0 },
            },
        ]
        const snapshot = insightSnapshot(insight({ result }), undefined, CONTEXT)
        const chart = snapshotChartSeries(snapshot, themes.light.chartPalette)

        expect(snapshot.allSeries).toHaveLength(4)
        expect(new Set(snapshot.allSeries.map((series) => series.key)).size).toBe(4)
        expect(snapshot.allSeries[0]?.breakdownValue).toEqual(['a', 'b'])
        expect(chart.map((series) => series.compareOf ?? null)).toEqual([
            null,
            null,
            snapshot.allSeries[1]?.key,
            snapshot.allSeries[0]?.key,
        ])
        expect(pointActorsInput(snapshot, snapshot.allSeries[0]?.key ?? '', 0, false)?.breakdown).toEqual(['a', 'b'])
    })

    test('matches array breakdown aggregates and scales percentage points without changing relative percent', () => {
        const entries = [
            { aggregated_value: 0.35, breakdown_value: ['a', 'b'], compare_label: 'current', action: { order: 0 } },
            { aggregated_value: 0.1, breakdown_value: ['a,b'], compare_label: 'previous', action: { order: 0 } },
            { aggregated_value: 0.3, breakdown_value: ['a', 'b'], compare_label: 'previous', action: { order: 0 } },
        ]

        const parts = numberParts(trends(undefined), entries, { valueFormat: 'percentage_scaled', unit: null }, null)

        expect(parts.delta).toMatchObject({ previous: 0.3, unit: 'points' })
        expect(parts.delta?.change).toBeCloseTo(5)
        expect(parts.delta?.percent).toBeCloseTo((0.05 / 0.3) * 100)
    })

    // `result: null` is a tile that the cache-only dashboard read found without a cache.
    test.each<[string, unknown, unknown, string, string]>([
        ['a line chart without a cache', trends(undefined), null, 'chart', 'pending'],
        ['a big number without a cache', trends(undefined, 'BoldNumber'), null, 'number', 'pending'],
        ['a funnel without a cache', FUNNEL, null, 'funnel', 'pending'],
        ['a retention grid without a cache', RETENTION, null, 'retention', 'pending'],
        ['value bars without a cache', trends(undefined, 'ActionsBarValue'), null, 'bars', 'pending'],
        ['a line chart with no points in the range', trends(undefined), [], 'chart', 'empty'],
        ['a funnel with no steps', FUNNEL, [], 'funnel', 'empty'],
        ['a retention grid with no cohorts', RETENTION, [], 'retention', 'empty'],
        ['a line chart with points', trends(undefined), [{ days: DAYS, data: [1, 2, 3, 4] }], 'chart', 'ready'],
        ['paths', viz({ kind: 'PathsQuery' }), null, 'web', 'ready'],
        ['a world map', trends(undefined, 'WorldMap'), null, 'web', 'ready'],
        [
            'a funnel broken down by cohort',
            viz({ kind: 'FunnelsQuery', series: [], breakdownFilter: { breakdown: [3], breakdown_type: 'cohort' } }),
            null,
            'web',
            'ready',
        ],
        [
            'retention with a breakdown',
            viz({ kind: 'RetentionQuery', breakdownFilter: { breakdown: '$browser' } }),
            null,
            'web',
            'ready',
        ],
        [
            'retention that sums a property',
            viz({ kind: 'RetentionQuery', retentionFilter: { aggregationType: 'sum' } }),
            null,
            'web',
            'ready',
        ],
        [
            'retention rows with breakdown values under a query without a breakdown',
            RETENTION,
            [{ ...COHORT_ROW, breakdown_value: 'Chrome' }],
            'web',
            'ready',
        ],
    ])('shows %s with the display and state it draws', (_name, query, result, display, state) => {
        const snapshot = insightSnapshot(insight({ query, result }), undefined, CONTEXT)

        expect([insightDisplay(snapshot), insightRenderState(snapshot)]).toEqual([display, state])
    })

    test('reads a SQL line chart into series, an interval, a format and its table', () => {
        const yAxis = [{ column: 'signups', settings: { formatting: { style: 'number', suffix: ' accounts' } } }]
        const response = sqlInsight({ display: 'ActionsBar', chartSettings: { yAxis } }, SQL_DAILY, [
            ['2026-10-12', 5],
            ['2026-10-13', 7],
        ])

        const snapshot = insightSnapshot(insight(response), undefined, CONTEXT)

        expect(snapshot).toMatchObject({
            kindLabel: 'Bar',
            chartKind: 'bar',
            interval: 'day',
            series: {
                interval: 'day',
                points: [
                    { at: '2026-10-12', value: 5 },
                    { at: '2026-10-13', value: 7 },
                ],
            },
            allSeries: [{ label: 'signups', compare: null }],
            inProgressFrom: null,
            ranking: null,
            capabilities: { number: false, chart: true, people: false },
            sqlTable: { columns: [{ name: 'day', isDate: true }, { name: 'signups' }], hasMore: false },
        })
        expect(snapshotFormatter(snapshot)(1234)).toBe('1,234 accounts')
    })

    test.each<[string, Partial<InsightApi>, string]>([
        ['with a range', {}, 'No rows for this range'],
        ['without a range', { resolved_date_range: null }, 'No rows'],
    ])('names rows when a SQL result is empty, %s', (_name, extra, expected) => {
        const empty = { ...sqlInsight({ display: 'ActionsTable' }, SQL_PLANS, []), ...extra }

        expect(noDataText(insightSnapshot(insight(empty), undefined, CONTEXT))).toBe(expected)
    })

    test('gives a SQL table no big number, even when its first cell is a number', () => {
        const types: [string, string][] = [
            ['views', 'UInt64'],
            ['page', 'String'],
        ]

        const snapshot = insightSnapshot(
            insight(sqlInsight({ display: 'ActionsTable' }, types, [[12, '/']])),
            undefined,
            CONTEXT
        )

        expect([snapshot.value, snapshot.capabilities.number]).toEqual([null, false])
    })

    test('formats a SQL chart without saved y axes with its first y column, not the x column', () => {
        const tableSettings = {
            columns: [
                { column: 'day', settings: { formatting: { prefix: 'wrong ' } } },
                { column: 'signups', settings: { formatting: { suffix: ' accounts' } } },
            ],
        }
        const response = sqlInsight({ display: 'ActionsLineGraph', tableSettings }, SQL_DAILY, [
            ['2026-10-12', 5],
            ['2026-10-13', 7],
        ])

        const snapshot = insightSnapshot(insight(response), undefined, CONTEXT)

        expect(snapshotFormatter(snapshot)(1234)).toBe('1234 accounts')
    })

    test('keeps the last SQL table and marks the failure when a read fails', () => {
        const table = sqlInsight({ display: 'ActionsTable' }, SQL_PLANS, [['Teams', 9]])
        const good = insightSnapshot(insight(table), undefined, CONTEXT)

        const after = insightSnapshot(insight({ ...table, result: [], query_status: { error: true } }), good, {
            ...CONTEXT,
            readAt: 2000,
        })

        expect([after.sqlTable?.rows, after.refreshFailed, insightDisplay(after), insightRenderState(after)]).toEqual([
            [['Teams', 9]],
            true,
            'table',
            'ready',
        ])
    })

    // A SQL display can change once the result is known: Auto resolves on the columns, and a chart needs date x values.
    test.each<[string, Partial<InsightApi>, string, string, string]>([
        ['a table without a cache', sqlInsight({ display: 'ActionsTable' }, [], null), 'table', 'pending', 'Table'],
        ['Auto without a cache', sqlInsight({ display: 'Auto' }, [], null), 'table', 'pending', 'SQL'],
        ['no display without a cache', sqlInsight({}, [], null), 'table', 'pending', 'Table'],
        ['a table with no rows', sqlInsight({ display: 'ActionsTable' }, SQL_PLANS, []), 'table', 'empty', 'Table'],
        [
            'Auto over dates',
            sqlInsight({ display: 'Auto' }, SQL_DAILY, [
                ['2026-10-12', 5],
                ['2026-10-13', 7],
            ]),
            'chart',
            'ready',
            'Line',
        ],
        [
            'Auto over one number',
            sqlInsight({ display: 'Auto' }, [['count()', 'UInt64']], [[312]]),
            'number',
            'ready',
            'Big number',
        ],
        [
            'a bar chart over plans',
            sqlInsight({ display: 'ActionsBar' }, SQL_PLANS, [['Teams', 9]]),
            'chart',
            'ready',
            'Bar',
        ],
        ['a heatmap', sqlInsight({ display: 'CalendarHeatmap' }, SQL_DAILY, null), 'web', 'ready', 'SQL'],
    ])('shows SQL %s with the display, state and label it draws', (_name, response, display, state, label) => {
        const snapshot = insightSnapshot(insight(response), undefined, CONTEXT)

        expect([insightDisplay(snapshot), insightRenderState(snapshot), snapshot.kindLabel]).toEqual([
            display,
            state,
            label,
        ])
    })

    test.each<[string, Record<string, unknown> | null, unknown, boolean]>([
        ['a tile with its own dates', { date_from: '-30d' }, trends(undefined), true],
        ['a tile that ignores dashboard filters', { ignoreDashboardFilters: true }, trends(undefined), true],
        [
            'a SQL tile without the filters placeholder',
            null,
            { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'select count() from events' } },
            true,
        ],
        [
            'a SQL tile with the filters placeholder',
            null,
            {
                kind: 'DataVisualizationNode',
                source: { kind: 'HogQLQuery', query: 'select count() from events where { filters }' },
            },
            false,
        ],
        ['a trends tile', null, trends(undefined), false],
    ])('detects %s', (_name, overrides, query, expected) => {
        expect(usesOwnRange(overrides, query)).toBe(expected)
    })
    test.each([
        [false, true, 'Last 7 days'],
        [true, true, 'Oct 11 – 14'],
        [true, false, 'Uses its own range'],
    ])('labels a pin with own range %s and resolved dates %s', (own, resolved, label) => {
        const snapshot = insightSnapshot(
            insight({ result: [], ...(!resolved ? { resolved_date_range: null } : {}) }),
            undefined,
            { ...CONTEXT, usesOwnRange: own }
        )
        expect(pinRangeLabel(snapshot)).toBe(label)
    })
})

describe('SQL charts across dashboard tiles and native charts', () => {
    const fixture = DEMO_SQL_INSIGHTS[0]
    if (!fixture) {
        throw new Error('Expected a SQL chart fixture')
    }
    const response = (): InsightApi =>
        insight({
            query: fixture.query,
            columns: fixture.sqlData.columns,
            types: fixture.sqlData.columns.map((name) => [name, name === 'month' ? 'String' : 'Nullable(Float64)']),
            result: fixture.sqlData.rows,
        })

    test.each(['String', 'Date'])('keeps unformatted SQL counts neutral with a %s axis', (type) => {
        const api = response()
        api.types = api.columns?.map((name) => [name, name === 'month' ? type : 'Float64'])
        api.result = [['2026-02-01', 2400, 300, null, 34]]
        api.query = {
            ...fixture.query,
            chartSettings: {
                xAxis: fixture.query.chartSettings.xAxis,
                yAxis: [
                    fixture.query.chartSettings.yAxis[0],
                    { column: 'orders', settings: { display: { yAxisPosition: 'right' } } },
                ],
            },
        }
        const snapshot = insightSnapshot(api, undefined, CONTEXT)
        const series = snapshotChartSeries(snapshot, themes.light.chartPalette)
        const axes = chartAxes(series, 'bar', 'grouped', snapshotFormatter(snapshot))
        expect(axes.left.formatValue(2400)).toBe('$2,400')
        expect(axes.right?.formatValue(34)).toBe('34')
        expect(tooltipPoint(series, [], 0, 'day')?.rows.map((row) => row.formattedValue)).toEqual(['$2,400', '34'])
    })

    test.each(['String', 'Date'])('resolves automatic SQL series from the saved chart with a %s axis', (type) => {
        const api = response()
        api.types = api.columns?.map((name) => [name, name === 'month' ? type : 'Float64'])
        api.result = [['2026-02-01', 2400, 300, null, 34]]
        api.query = {
            ...fixture.query,
            display: 'ActionsLineGraph',
            chartSettings: {
                xAxis: fixture.query.chartSettings.xAxis,
                yAxis: [
                    fixture.query.chartSettings.yAxis[0],
                    { column: 'orders', settings: { display: { displayType: 'auto' } } },
                ],
            },
        }
        const snapshot = insightSnapshot(api, undefined, CONTEXT)
        expect(snapshot.chartKind).toBe('bar')
        expect(snapshotChartSeries(snapshot, themes.light.chartPalette).map((series) => series.kind)).toEqual([
            'bar',
            'line',
        ])
    })

    test('preserves saved labels, columns, mixed series, separate scales, percentage units and null gaps', () => {
        const api = response()
        const snapshot = insightSnapshot(api, undefined, CONTEXT)
        const series = snapshotChartSeries(snapshot, themes.light.chartPalette)
        const axes = chartAxes(series, 'bar', 'stacked', snapshotFormatter(snapshot))
        const geometry = chartGeometry({
            width: 350,
            height: 180,
            kind: 'bar',
            variant: 'inline',
            count: 6,
            values: axes.left.values,
            dates: [0, 1, 2, 3, 4, 5],
            labels: series[0]?.points.map((p) => p.label),
            interval: 'day',
            formatValue: String,
            uses24hourClock: false,
            primaryAxis: axes.left,
            rightAxis: axes.right,
        })
        expect(snapshot.capabilities).toMatchObject({ chart: true, number: false, people: false })
        expect(queryDisplay(api.query)).toBe('chart')
        expect(snapshot.value).toBeNull()
        expect(series.map((s) => [s.label, s.kind, s.axis])).toEqual([
            ['Sales', 'bar', 'left'],
            ['Renewals', 'bar', 'left'],
            ['Growth', 'line', 'right'],
        ])
        expect(series[0]?.points[5]).toEqual({ at: 5, label: 'Jul 2026 (est.)', value: 3900 })
        expect(series[2]?.points[0]?.value).toBeNaN()
        expect(series[2]?.points[1]?.value).toBe(0.2)
        expect(Math.max(...axes.left.values.filter(Number.isFinite))).toBe(4550)
        expect(Math.max(...(axes.right?.values.filter(Number.isFinite) ?? []))).toBe(0.2)
        expect(geometry.yTicks.some((tick) => tick.text?.startsWith('$'))).toBe(true)
        expect(geometry.rightYTicks?.every((tick) => tick.text?.endsWith('%'))).toBe(true)
        expect(geometry.xLabels.at(-1)?.text).toBe('Jul 2026 (est.)')
        const point = tooltipPoint(series, [], 1, 'day')
        if (!point) {
            throw new Error('Expected a tooltip for the SQL chart')
        }
        expect(tooltipContent(point, { formatValue: String, compact: true, maxRows: 4 }).header).toBe('Mar 2026')
        expect(point.rows.map((row) => row.formattedValue)).toEqual(['$2,800', '$450', '20.0%'])
        expect(rangeContent(series, [], 1, 2, 'day', String)?.rows[2]?.values).toBe('20.0% → 9.0%')
        const view = dashboardView({ id: 99, name: 'Example', tiles: [{ id: 1, insight: api }] })
        expect(splitTilesByEligibility(view.tiles, 'chart').usable.map((tile) => tile.tileId)).toEqual([1])
    })

    test('maps by returned column name and does not turn missing values into zeros unless requested', () => {
        const api = response()
        api.columns = ['growth', 'renewals', 'month', 'sales']
        api.types = api.columns.map((name) => [name, name === 'month' ? 'String' : 'Nullable(Float64)'])
        api.result = [
            ['0.125', null, 'Later', '123.45'],
            [null, 2, 'Earlier', 0],
        ]
        const snapshot = insightSnapshot(api, undefined, CONTEXT)
        expect(snapshot.allSeries[0]?.points.map((p) => [p.label, p.value])).toEqual([
            ['Later', 123.45],
            ['Earlier', 0],
        ])
        expect(snapshot.allSeries[1]?.points[0]?.value).toBeNaN()
        expect(snapshot.allSeries[2]?.points[0]?.value).toBe(0.125)
        api.query = { ...fixture.query, chartSettings: { ...fixture.query.chartSettings, showNullsAsZero: true } }
        expect(insightSnapshot(api, undefined, CONTEXT).allSeries[1]?.points[0]?.value).toBe(0)
    })

    test.each([
        ['Metric', {}, 'SQL metric cards are not supported on mobile yet'],
        ['ActionsTable', {}, 'This SQL visualization cannot be pinned as a chart yet'],
        ['BoldNumber', {}, 'Saved as a big number'],
        [
            'ActionsBar',
            { seriesBreakdownColumn: 'region' },
            'SQL category breakdown charts are not supported on mobile yet',
        ],
        ['ActionsStackedBar', { stackBars100: true }, '100% stacked SQL charts are not supported on mobile yet'],
        [
            'ActionsBar',
            { rightYAxisSettings: { scale: 'logarithmic' } },
            'Logarithmic SQL axes are not supported on mobile yet',
        ],
    ])(
        'explains unsupported %s settings instead of claiming the data is not over time',
        (display, settings, reason) => {
            const api = response()
            api.query = {
                ...fixture.query,
                display,
                chartSettings: { ...fixture.query.chartSettings, ...(settings as object) },
            }
            const snapshot = insightSnapshot(api, undefined, CONTEXT)
            expect(snapshot.capabilities).toMatchObject({ chart: false, chartReason: reason })
            const view = dashboardView({ id: 99, name: 'Example', tiles: [{ id: 1, insight: api }] })
            expect(splitTilesByEligibility(view.tiles, 'chart').unusable[0]?.reason).toBe(reason)
        }
    )

    test('keeps category labels when a saved SQL chart requests cumulative values', () => {
        const api = response()
        api.query = { ...fixture.query, display: 'ActionsLineGraphCumulative' }
        const snapshot = insightSnapshot(api, undefined, CONTEXT)
        expect(snapshot.allSeries[0]?.points.slice(0, 2)).toEqual([
            { at: '0', label: 'Feb 2026', value: 2400 },
            { at: '1', label: 'Mar 2026', value: 5200 },
        ])
    })

    test('missing saved result columns fall back to the web while empty valid results remain an empty chart', () => {
        const api = response()
        api.columns = ['month', 'different_value']
        const invalid = insightSnapshot(api, undefined, CONTEXT)
        expect(invalid.capabilities.chartReason).toBe('Saved chart columns are unavailable')
        expect(insightDisplay(invalid)).toBe('web')
        api.columns = fixture.sqlData.columns
        api.result = []
        expect(insightRenderState(insightSnapshot(api, undefined, CONTEXT))).toBe('empty')
    })
})
