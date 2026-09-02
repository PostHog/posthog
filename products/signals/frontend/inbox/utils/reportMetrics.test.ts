import { ChartDisplayType } from '~/types'

import {
    asReportMetricAggregateQuery,
    asReportMetricBarQuery,
    asReportMetricTrendsQuery,
    formatReportMetricValue,
    reportMetricAggregate,
} from './reportMetrics'

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
})
