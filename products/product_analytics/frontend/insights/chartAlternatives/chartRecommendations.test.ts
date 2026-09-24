import { NodeKind } from '~/queries/schema/schema-general'
import type { TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, PropertyFilterType, PropertyMathType, PropertyOperator } from '~/types'

import { getChartDisplayOptions } from './chartDisplayOptions'
import { getChartAlternatives, isTwoBucketSlopeCandidate } from './chartRecommendations'

function makeTrendsQuery(overrides: Partial<TrendsQuery> = {}): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                name: '$pageview',
                event: '$pageview',
                math: BaseMathType.TotalCount,
                math_property: 'duration',
            },
        ],
        trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
        ...overrides,
    }
}

const compatibleOptions = getChartDisplayOptions({
    isTrends: true,
    hasSingleSeriesOutput: true,
    hasTrendsFormula: false,
    boxPlotMissingProperty: false,
    hasMetricInsight: true,
})

describe('getChartAlternatives', () => {
    it.each([
        {
            name: 'prefers time series siblings and Metric for a plain line chart',
            query: makeTrendsQuery(),
            expected: [
                ChartDisplayType.Metric,
                ChartDisplayType.ActionsUnstackedBar,
                ChartDisplayType.ActionsAreaGraph,
            ],
        },
        {
            name: 'puts the world map first for a country breakdown, then the parts-of-a-whole charts',
            query: makeTrendsQuery({
                breakdownFilter: { breakdowns: [{ property: '$geoip_country_code', type: 'event' }] },
            }),
            expected: [ChartDisplayType.WorldMap, ChartDisplayType.ActionsBar, ChartDisplayType.ActionsPie],
        },
        {
            name: 'prefers stacked bars and proportions for a breakdown, skipping types that drop it',
            query: makeTrendsQuery({ breakdownFilter: { breakdowns: [{ property: '$browser', type: 'event' }] } }),
            expected: [ChartDisplayType.ActionsBar, ChartDisplayType.ActionsPie, ChartDisplayType.ActionsDonut],
        },
        {
            name: 'demotes lines and side-by-side bars for a breakdown even from a stacked bar chart',
            query: makeTrendsQuery({
                trendsFilter: { display: ChartDisplayType.ActionsBar },
                breakdownFilter: { breakdowns: [{ property: '$browser', type: 'event' }] },
            }),
            expected: [ChartDisplayType.ActionsPie, ChartDisplayType.ActionsDonut, ChartDisplayType.ActionsBarValue],
        },
        {
            name: 'puts the world map first for a country filter',
            query: makeTrendsQuery({
                properties: [
                    {
                        key: '$geoip_country_name',
                        value: 'Germany',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                ],
            }),
            expected: [ChartDisplayType.WorldMap, ChartDisplayType.Metric, ChartDisplayType.ActionsUnstackedBar],
        },
        {
            name: 'puts the box plot first for a percentile series',
            query: makeTrendsQuery({
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        math: PropertyMathType.P90,
                        math_property: 'duration',
                    },
                ],
            }),
            expected: [ChartDisplayType.BoxPlot, ChartDisplayType.Metric, ChartDisplayType.ActionsUnstackedBar],
        },
        {
            name: 'puts the box plot first for a moving average',
            query: makeTrendsQuery({
                trendsFilter: { display: ChartDisplayType.ActionsLineGraph, smoothingIntervals: 7 },
            }),
            expected: [ChartDisplayType.BoxPlot, ChartDisplayType.Metric, ChartDisplayType.ActionsUnstackedBar],
        },
        {
            name: 'prefers other total value charts when viewing a pie chart of several series',
            query: makeTrendsQuery({
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount },
                    { kind: NodeKind.EventsNode, event: '$autocapture', math: BaseMathType.TotalCount },
                ],
                trendsFilter: { display: ChartDisplayType.ActionsPie },
            }),
            expected: [ChartDisplayType.ActionsDonut, ChartDisplayType.ActionsBarValue, ChartDisplayType.Metric],
        },
        {
            name: 'does not suggest proportion charts for a pie chart of one series',
            query: makeTrendsQuery({ trendsFilter: { display: ChartDisplayType.ActionsPie } }),
            expected: [
                ChartDisplayType.Metric,
                ChartDisplayType.ActionsUnstackedBar,
                ChartDisplayType.ActionsLineGraph,
            ],
        },
        {
            name: 'puts the slope graph first when asked to suggest it',
            query: makeTrendsQuery(),
            suggestSlope: true,
            expected: [ChartDisplayType.SlopeGraph, ChartDisplayType.Metric, ChartDisplayType.ActionsUnstackedBar],
        },
        {
            name: 'does not suggest proportion charts for a pie chart of one rendered formula',
            query: makeTrendsQuery({
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount },
                    { kind: NodeKind.EventsNode, event: '$autocapture', math: BaseMathType.TotalCount },
                ],
                trendsFilter: {
                    display: ChartDisplayType.ActionsPie,
                    formulas: ['A', 'B'],
                    formulaNodes: [{ formula: 'A / B' }],
                },
            }),
            expected: [
                ChartDisplayType.Metric,
                ChartDisplayType.ActionsUnstackedBar,
                ChartDisplayType.ActionsLineGraph,
            ],
        },
    ])('$name', ({ query, expected, suggestSlope }) => {
        expect(getChartAlternatives(compatibleOptions, query, suggestSlope).map((option) => option.display)).toEqual(
            expected
        )
    })

    const twoBuckets = { result: [{ days: ['2026-01-01', '2026-01-02'], data: [1, 2] }] }
    it.each([
        ['two buckets', makeTrendsQuery(), twoBuckets, true],
        ['three buckets', makeTrendsQuery(), { result: [{ days: ['2026-01-01', '2026-01-02', '2026-01-03'] }] }, false],
        [
            'two smoothed buckets',
            makeTrendsQuery({ trendsFilter: { display: ChartDisplayType.ActionsLineGraph, smoothingIntervals: 2 } }),
            twoBuckets,
            false,
        ],
        [
            'two buckets of a truncated breakdown',
            makeTrendsQuery({ breakdownFilter: { breakdowns: [{ property: '$browser', type: 'event' }] } }),
            { ...twoBuckets, hasMore: true },
            false,
        ],
        [
            'two buckets of a complete breakdown',
            makeTrendsQuery({ breakdownFilter: { breakdowns: [{ property: '$browser', type: 'event' }] } }),
            { ...twoBuckets, hasMore: false },
            true,
        ],
    ])('suggests a slope for %s only when its preview can be derived', (_, query, insightData, expected) => {
        expect(isTwoBucketSlopeCandidate(query, insightData)).toBe(expected)
    })
})
