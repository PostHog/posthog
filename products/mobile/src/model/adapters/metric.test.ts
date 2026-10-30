import type { ReportChartApi, ReportMetricApi } from '@/api/reports'

import {
    asTrendsInsight,
    formatMetricValue,
    MAX_OPEN_URL_LENGTH,
    metricChartKind,
    metricFilterCount,
    metricView,
    metricWindowLabel,
    reportChartView,
    trendsAggregate,
    trendsSeries,
} from './metric'

const SCOPE = { host: 'https://app.example.com', projectId: 2 }
const NEW_INSIGHT = 'https://app.example.com/project/2/insights/new#q='

function trends(source: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        kind: 'InsightVizNode',
        source: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: '$exception' }], ...source },
    }
}

function liveMetric(overrides: Partial<ReportMetricApi> = {}): ReportMetricApi {
    return {
        metric_id: 'users',
        title: 'Affected users',
        kind: 'affected_users',
        role: 'primary',
        value: 612,
        value_at: '2026-10-09T09:00:00Z',
        series: [3, 4],
        value_format: 'count',
        unit: null,
        caption: null,
        query: trends(),
        ...overrides,
    }
}

describe('report metric', () => {
    test.each<[number, string, string | null, string]>([
        [3721, 'count', null, '3,721'],
        [612, 'count', 'users', '612 users'],
        [34, 'percentage', null, '34%'],
        [0.345, 'percentage_scaled', null, '34.5%'],
        [2300, 'duration', 'ms', '2.3s'],
        [340, 'duration', 'ms', '340 ms'],
        [184_000, 'currency', 'USD', '$184k'],
    ])('formats %d as %s', (value, format, unit, expected) => {
        expect(formatMetricValue(value, format, unit)).toBe(expected)
    })

    test.each<[string, ReportMetricApi['value_format'], unknown[], 'line' | 'bar']>([
        ['a count', 'count', [undefined], 'bar'],
        ['revenue summed per bucket', 'currency', ['sum', 'sum'], 'bar'],
        ['revenue that is not all sums', 'currency', ['sum', 'avg'], 'line'],
        ['a rate', 'percentage', [undefined], 'line'],
        ['a duration', 'duration', ['p95'], 'line'],
    ])('chart kind for %s', (_name, format, maths, expected) => {
        const insight = asTrendsInsight(trends({ series: maths.map((math) => ({ kind: 'EventsNode', math })) }))
        expect(metricChartKind(format, insight)).toBe(expected)
    })

    test('derives the series and aggregate queries without touching the authored one', () => {
        const query = trends({
            interval: 'hour',
            trendsFilter: {
                display: 'ActionsTable',
                showPercentStackView: true,
                hiddenLegendIndexes: [0],
                decimals: 1,
            },
        })
        const authored = JSON.stringify(query)
        const view = metricView(liveMetric({ query }), SCOPE)

        expect(view).toMatchObject({ chart: 'bar', interval: 'hour' })
        expect(view.data).toEqual({
            kind: 'query',
            seriesQuery: expect.objectContaining({
                kind: 'TrendsQuery',
                trendsFilter: { display: 'ActionsBar', showPercentStackView: false, decimals: 1 },
            }),
            aggregateQuery: expect.objectContaining({
                trendsFilter: expect.objectContaining({ display: 'BoldNumber' }),
            }),
        })
        expect(JSON.stringify(query)).toBe(authored)
    })

    test('a redacted metric keeps its snapshot and runs nothing', () => {
        expect(metricView(liveMetric({ query: null, role: 'supporting', caption: '  ' }), SCOPE)).toEqual({
            metricId: 'users',
            role: 'supporting',
            title: 'Affected users',
            format: { valueFormat: 'count', unit: null },
            chart: 'bar',
            interval: 'day',
            snapshot: { value: 612, at: '2026-10-09T09:00:00Z', series: [3, 4] },
            data: { kind: 'none' },
            windowLabel: 'Current window',
            filterCount: 0,
        })
        expect(metricView(liveMetric({ value: null }), SCOPE).snapshot).toBeUndefined()
    })

    test.each<[string, unknown, { at: string; value: number }[] | undefined]>([
        [
            'zips days and data to the shorter list, NaN for a missing bucket',
            {
                results: [
                    { days: ['2026-10-11', '2026-10-12', '2026-10-13'], data: [4, null] },
                    { days: [], data: [] },
                ],
            },
            [
                { at: '2026-10-11', value: 4 },
                { at: '2026-10-12', value: Number.NaN },
            ],
        ],
        [
            'reads the `result` key too',
            { result: [{ days: ['2026-10-13'], data: [7] }] },
            [{ at: '2026-10-13', value: 7 }],
        ],
        ['no buckets', { results: [{ days: [], data: [] }] }, undefined],
        ['not a trends response', { results: 'nope' }, undefined],
    ])('trends series: %s', (_name, response, expected) => {
        expect(trendsSeries(response, 'day')?.points).toEqual(expected)
    })

    test('reads the aggregate from the first series only', () => {
        expect(
            trendsAggregate({ results: [{ aggregated_value: 612, data: [300, 400] }, { aggregated_value: 9 }] })
        ).toBe(612)
        expect(trendsAggregate({ results: [{ data: [300, 400] }] })).toBeUndefined()
    })

    test.each<[unknown, string]>([
        ['-14d', 'Last 14 days'],
        ['-24h', 'Last 24 hours'],
        ['-1m', 'Last month'],
        ['2026-10-01', 'Current window'],
        [undefined, 'Current window'],
    ])('window label for date_from %s', (dateFrom, expected) => {
        expect(metricWindowLabel(asTrendsInsight(trends({ dateRange: { date_from: dateFrom } })))).toBe(expected)
    })

    test('counts property filters across series, nested groups and the query', () => {
        const insight = asTrendsInsight(
            trends({
                series: [
                    { kind: 'EventsNode', properties: [{ key: '$browser' }, { key: '$os' }] },
                    { kind: 'EventsNode' },
                ],
                properties: {
                    type: 'AND',
                    values: [{ type: 'AND', values: [{ key: 'plan' }, { type: 'OR', values: [] }] }],
                },
            })
        )
        expect(metricFilterCount(insight)).toBe(3)
    })

    test.each<[string, unknown, boolean, string | undefined]>([
        ['a trends line', trends({ trendsFilter: { display: 'ActionsLineGraph' } }), true, NEW_INSIGHT],
        ['a trends graph with no display', trends(), true, NEW_INSIGHT],
        ['a bold number', trends({ trendsFilter: { display: 'BoldNumber' } }), false, NEW_INSIGHT],
        ['a pie', trends({ trendsFilter: { display: 'ActionsPie' } }), false, NEW_INSIGHT],
        ['a breakdown', trends({ breakdownFilter: { breakdown: '$browser' } }), false, NEW_INSIGHT],
        [
            'a SQL graph',
            { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'select 1' }, display: 'ActionsBar' },
            false,
            'https://app.example.com/project/2/sql?open_query=',
        ],
        [
            'a saved insight',
            { kind: 'SavedInsightNode', shortId: 'ab/c' },
            false,
            'https://app.example.com/project/2/insights/ab%2Fc',
        ],
        ['a saved insight without a short id', { kind: 'SavedInsightNode' }, false, undefined],
        [
            'a query too long to open',
            trends({ properties: [{ key: 'x'.repeat(MAX_OPEN_URL_LENGTH) }] }),
            true,
            undefined,
        ],
    ])('report chart: %s', (_name, query, drawable, urlPrefix) => {
        const chart: ReportChartApi = { chart_id: 'c1', title: 'Chart', query, caption: null }
        const view = reportChartView(chart, SCOPE)
        expect(view.data?.kind).toBe(drawable ? 'query' : undefined)
        if (urlPrefix) {
            expect(view.openUrl?.startsWith(urlPrefix)).toBe(true)
        } else {
            expect(view.openUrl).toBeUndefined()
        }
    })

    test('an open link leaves the embed flags out', () => {
        const view = metricView(liveMetric({ query: { ...trends(), embedded: true, showFilters: false } }), SCOPE)
        const encoded = view.openUrl?.split('#q=')[1] ?? ''
        expect(JSON.parse(decodeURIComponent(encoded))).toEqual(trends())
    })
})
