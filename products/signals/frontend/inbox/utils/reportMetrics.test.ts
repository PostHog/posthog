import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import {
    asReportMetricAggregateQuery,
    asReportMetricBarQuery,
    asReportMetricTrendsQuery,
    formatReportMetricParts,
    formatReportMetricValue,
    mergeReportMetricSnapshots,
    reportMetricAggregate,
    reportNeedsMetricRefresh,
    reportMetricDelta,
    reportMetricFilterCount,
    reportMetricRowParts,
    reportMetricUnitWord,
    reportMetricWindowLabel,
    type ReportMetricInsightQuery,
} from './reportMetrics'

const NOW = Date.parse('2026-09-09T12:00:00Z')
const SNAPSHOT_METRIC: ReportMetricApi = {
    metric_id: 'affected-users',
    title: 'Affected users',
    kind: 'affected_users',
    role: 'primary',
    value: 17,
    value_at: '2026-09-09T11:30:00Z',
    series: [3, 5, 9],
    value_format: 'count',
    unit: 'users',
    query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } },
    caption: null,
    comparison: { value: 12, label: 'Previous 14 days' },
}

describe('reportMetrics', () => {
    test.each([
        ['result response', { result: [{ aggregated_value: 0, data: [4, 7, 9] }] }, 0],
        ['results response', { results: [{ aggregated_value: 41, data: [20, 31] }] }, 41],
        ['missing aggregate', { results: [{ data: [20, 31] }] }, null],
        ['invalid aggregate', { results: [{ aggregated_value: Number.NaN }] }, null],
    ])('reads the whole-window aggregate from a %s', (_name, response, expected) => {
        expect(reportMetricAggregate(response)).toBe(expected)
    })

    test.each([
        ['zero count', { value_format: 'count', unit: 'users' } as const, 0, '0 users'],
        ['percentage points', { value_format: 'percentage', unit: null } as const, 34, '34%'],
        ['small percentage points', { value_format: 'percentage', unit: null } as const, 0.04, '0.04%'],
        ['scaled percentage', { value_format: 'percentage_scaled', unit: null } as const, 0.34, '34%'],
        ['small scaled percentage', { value_format: 'percentage_scaled', unit: null } as const, 0.0004, '0.04%'],
        ['milliseconds', { value_format: 'duration', unit: 'ms' } as const, 1250, '1.25s'],
        ['currency', { value_format: 'currency', unit: 'USD' } as const, 42.5, '$42.50'],
        ['small number', { value_format: 'number', unit: null } as const, 0.004, '0.004'],
        ['unavailable value', { value_format: 'number', unit: null } as const, null, null],
    ])('formats a %s metric', (_name, metric, value, expected) => {
        expect(formatReportMetricValue(metric, value)).toBe(expected)
    })

    test.each([
        [
            'count with a unit',
            { value_format: 'count', unit: 'users' } as const,
            1410,
            { value: '1,410', unit: 'users' },
        ],
        [
            'percent unit folded in',
            { value_format: 'percentage', unit: '%' } as const,
            34,
            { value: '34%', unit: null },
        ],
        [
            'currency code folded in',
            { value_format: 'currency', unit: 'USD' } as const,
            42.5,
            { value: '$42.50', unit: null },
        ],
        [
            'milliseconds folded in',
            { value_format: 'duration', unit: 'ms' } as const,
            1250,
            { value: '1.25s', unit: null },
        ],
    ])('splits a %s metric into a value and a separate unit', (_name, metric, value, expected) => {
        expect(formatReportMetricParts(metric, value)).toEqual(expected)
    })

    it('embeds a Trends query as a bar chart without changing its measurement', () => {
        const query = asReportMetricBarQuery({
            kind: 'InsightVizNode',
            source: {
                kind: 'TrendsQuery',
                dateRange: { date_from: '-7d' },
                interval: 'day',
                series: [{ kind: 'EventsNode', event: '$autocapture', math: 'dau' }],
            },
        })

        expect(query).toMatchObject({
            embedded: true,
            showFilters: false,
            source: {
                dateRange: { date_from: '-7d' },
                interval: 'day',
                series: [{ event: '$autocapture', math: 'dau' }],
                trendsFilter: { display: ChartDisplayType.ActionsBar },
            },
        })
    })

    it('drops a stored percent-stack view and hidden series when deriving the bar', () => {
        const query = asReportMetricBarQuery({
            kind: 'InsightVizNode',
            source: {
                kind: 'TrendsQuery',
                dateRange: { date_from: '-7d' },
                interval: 'day',
                series: [{ kind: 'EventsNode', event: '$autocapture', math: 'dau' }],
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraph,
                    showPercentStackView: true,
                    hiddenLegendIndexes: [0],
                },
            },
        })

        // A single-series metric bar must not percent-stack (every bucket would read 100%) or hide
        // its only series.
        expect(query?.source.trendsFilter).toMatchObject({
            display: ChartDisplayType.ActionsBar,
            showPercentStackView: false,
        })
        expect(query?.source.trendsFilter?.hiddenLegendIndexes).toBeUndefined()
    })

    it('derives a whole-window aggregate query without changing the stored measurement', () => {
        const storedQuery = {
            kind: 'InsightVizNode',
            source: {
                kind: 'TrendsQuery',
                dateRange: { date_from: '-7d' },
                interval: 'day',
                series: [{ kind: 'EventsNode', event: '$autocapture', math: 'dau' }],
                trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
            },
        }

        expect(asReportMetricAggregateQuery(storedQuery)).toMatchObject({
            source: {
                dateRange: { date_from: '-7d' },
                interval: 'day',
                series: [{ event: '$autocapture', math: 'dau' }],
                trendsFilter: { display: ChartDisplayType.BoldNumber },
            },
        })
        expect(storedQuery.source.trendsFilter.display).toBe(ChartDisplayType.ActionsLineGraph)
    })

    it('keeps a supporting metric query unchanged when validating it', () => {
        const query = {
            kind: 'InsightVizNode',
            source: {
                kind: 'TrendsQuery',
                dateRange: { date_from: '-7d' },
                series: [{ kind: 'EventsNode', event: '$autocapture', math: 'dau' }],
                trendsFilter: { display: 'ActionsLineGraph' },
            },
        }

        expect(asReportMetricTrendsQuery(query)).toBe(query)
    })

    test.each([
        ['an authored word', { kind: 'occurrences', unit: 'clicks', value_format: 'count' } as const, 'clicks'],
        [
            'a percent sign on an error rate',
            { kind: 'error_rate', unit: '%', value_format: 'percentage' } as const,
            'failure',
        ],
        [
            'a percent sign on a scaled conversion rate',
            { kind: 'conversion_rate', unit: '%', value_format: 'percentage_scaled' } as const,
            'conversion',
        ],
        ['a seconds suffix', { kind: 'duration', unit: 's', value_format: 'duration' } as const, 'seconds'],
        ['a milliseconds suffix', { kind: 'duration', unit: 'ms', value_format: 'duration' } as const, 'ms'],
        ['a currency code', { kind: 'revenue', unit: 'USD', value_format: 'currency' } as const, 'revenue'],
        ['no unit on a custom metric', { kind: 'custom', unit: null, value_format: 'number' } as const, ''],
        ['a whitespace-only unit', { kind: 'affected_users', unit: '  ', value_format: 'count' } as const, 'users'],
    ])('names the row unit from %s', (_name, metric, expected) => {
        expect(reportMetricUnitWord(metric)).toBe(expected)
    })

    test.each([
        [
            'a count',
            { kind: 'occurrences', unit: null, value_format: 'count' } as const,
            3758,
            { value: '3,758', unit: 'events' },
        ],
        [
            'percentage points',
            { kind: 'error_rate', unit: '%', value_format: 'percentage' } as const,
            40,
            { value: '40%', unit: 'failure' },
        ],
        [
            'a scaled percentage',
            { kind: 'conversion_rate', unit: null, value_format: 'percentage_scaled' } as const,
            0.051,
            { value: '5.1%', unit: 'conversion' },
        ],
        [
            'a duration in seconds',
            { kind: 'duration', unit: 's', value_format: 'duration' } as const,
            287,
            { value: '287', unit: 'seconds' },
        ],
        [
            'a currency amount',
            { kind: 'revenue', unit: 'USD', value_format: 'currency' } as const,
            1200,
            { value: '$1,200.00', unit: 'revenue' },
        ],
        [
            'a plain number',
            { kind: 'affected_users', unit: null, value_format: 'number' } as const,
            4.2,
            { value: '4.2', unit: 'users' },
        ],
        ['an unavailable value', { kind: 'affected_users', unit: null, value_format: 'count' } as const, null, null],
        ['an unusable value', { kind: 'affected_users', unit: null, value_format: 'count' } as const, Number.NaN, null],
    ])('stacks %s over its unit word', (_name, metric, value, expected) => {
        expect(reportMetricRowParts(metric, value)).toEqual(expected)
    })

    test.each([
        ['-14d', { source: { dateRange: { date_from: '-14d' } } }, 'Last 14 days'],
        ['-24h', { source: { dateRange: { date_from: '-24h' } } }, 'Last 24 hours'],
        ['-1d', { source: { dateRange: { date_from: '-1d' } } }, 'Last day'],
        ['-4w', { source: { dateRange: { date_from: '-4w' } } }, 'Last 4 weeks'],
        ['-1m', { source: { dateRange: { date_from: '-1m' } } }, 'Last month'],
        ['-2y', { source: { dateRange: { date_from: '-2y' } } }, 'Last 2 years'],
        ['a query with no date range', { source: { interval: 'day' } }, null],
        ['an absolute date', { source: { dateRange: { date_from: '2026-01-01' } } }, null],
        ['a missing query', undefined, null],
    ])('labels the live window of %s', (_name, query, expected) => {
        expect(reportMetricWindowLabel(query)).toBe(expected)
    })

    test.each([
        [
            'a multiplied user count',
            { kind: 'affected_users', value_format: 'count' } as const,
            237,
            72,
            { direction: 'up', tone: 'bad', label: '3.3×' },
        ],
        [
            'a growing user count',
            { kind: 'affected_users', value_format: 'count' } as const,
            1248,
            832,
            { direction: 'up', tone: 'bad', label: '+50%' },
        ],
        [
            'a whole multiple',
            { kind: 'affected_users', value_format: 'count' } as const,
            4,
            1,
            { direction: 'up', tone: 'bad', label: '4×' },
        ],
        [
            'a move too small to report',
            { kind: 'occurrences', value_format: 'count' } as const,
            3758,
            3760,
            { direction: 'flat', tone: 'neutral', label: 'No change' },
        ],
        [
            'a scaled conversion rate',
            { kind: 'conversion_rate', value_format: 'percentage_scaled' } as const,
            0.051,
            0.05,
            { direction: 'up', tone: 'good', label: '+0.1 pts' },
        ],
        [
            'a worsening error rate',
            { kind: 'error_rate', value_format: 'percentage' } as const,
            40,
            34,
            { direction: 'up', tone: 'bad', label: '+6 pts' },
        ],
        [
            'an improving error rate',
            { kind: 'error_rate', value_format: 'percentage' } as const,
            34,
            40,
            { direction: 'down', tone: 'good', label: '-6 pts' },
        ],
        [
            'a shorter duration',
            { kind: 'duration', value_format: 'duration' } as const,
            199,
            287,
            { direction: 'down', tone: 'good', label: '-31%' },
        ],
        [
            'falling revenue',
            { kind: 'revenue', value_format: 'currency' } as const,
            900,
            1000,
            { direction: 'down', tone: 'bad', label: '-10%' },
        ],
        [
            'a doubled custom metric',
            { kind: 'custom', value_format: 'number' } as const,
            10,
            5,
            { direction: 'up', tone: 'neutral', label: '2×' },
        ],
        [
            'a rise from nothing',
            { kind: 'affected_users', value_format: 'count' } as const,
            37,
            0,
            { direction: 'up', tone: 'bad', label: 'Up from 0' },
        ],
        [
            'two empty windows',
            { kind: 'affected_users', value_format: 'count' } as const,
            0,
            0,
            { direction: 'flat', tone: 'neutral', label: 'No change' },
        ],
        ['a missing current value', { kind: 'affected_users', value_format: 'count' } as const, null, 72, null],
    ])('describes %s as a change a reader can act on', (_name, metric, current, previous, expected) => {
        expect(reportMetricDelta(metric, current, previous)).toEqual(expected)
    })

    describe('reportMetricFilterCount', () => {
        const series = (properties?: unknown): Record<string, unknown> => ({
            kind: NodeKind.EventsNode,
            event: '$pageview',
            ...(properties === undefined ? {} : { properties }),
        })
        const trends = (source: Record<string, unknown>): ReportMetricInsightQuery =>
            ({ kind: NodeKind.InsightVizNode, source: { kind: NodeKind.TrendsQuery, ...source } }) as never

        it.each([
            ['no filters', trends({ series: [series()] }), 0],
            ['series filters', trends({ series: [series([{ key: 'a' }, { key: 'b' }]), series([{ key: 'c' }])] }), 3],
            [
                'a property group on the query',
                trends({
                    series: [series()],
                    properties: { type: 'AND', values: [{ type: 'OR', values: [{ key: 'a' }, { key: 'b' }] }] },
                }),
                2,
            ],
        ])('counts %s', (_label, query, expected) => {
            expect(reportMetricFilterCount(query)).toBe(expected)
        })
    })
    test.each([
        ['no metrics', {}, false],
        ['fresh snapshot', { metrics: [{ ...SNAPSHOT_METRIC, value_at: '2026-09-09T11:50:00Z' }] }, false],
        ['stale snapshot', { metrics: [SNAPSHOT_METRIC] }, true],
        ['no snapshot', { metrics: [{ ...SNAPSHOT_METRIC, value: null, value_at: null }] }, true],
    ])('asks for a refresh when a report has %s', (_name, report, expected) => {
        expect(reportNeedsMetricRefresh(report as { metrics?: ReportMetricApi[] }, NOW)).toBe(expected)
    })

    it('merges refreshed numbers by metric_id and keeps the query and comparison', () => {
        const report = { id: 'r1', metrics: [{ ...SNAPSHOT_METRIC }] }
        const merged = mergeReportMetricSnapshots(report, [
            {
                id: 'r1',
                metrics: [
                    {
                        ...SNAPSHOT_METRIC,
                        value: 21,
                        value_at: '2026-09-09T12:00:00Z',
                        series: [5, 9, 21],
                    },
                ],
            },
        ])

        expect(merged).not.toBe(report)
        expect(merged.metrics[0]).toMatchObject({
            value: 21,
            value_at: '2026-09-09T12:00:00Z',
            series: [5, 9, 21],
            query: SNAPSHOT_METRIC.query,
            comparison: SNAPSHOT_METRIC.comparison,
        })
        // The same numbers back, or another report's snapshot, leave the row object untouched.
        expect(mergeReportMetricSnapshots(report, [{ id: 'r1', metrics: [SNAPSHOT_METRIC] }])).toBe(report)
        expect(mergeReportMetricSnapshots(report, [{ id: 'other', metrics: [] }])).toBe(report)
    })
})
