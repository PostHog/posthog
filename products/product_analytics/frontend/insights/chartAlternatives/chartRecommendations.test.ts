import { NodeKind } from '~/queries/schema/schema-general'
import type { TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, PropertyFilterType, PropertyMathType, PropertyOperator } from '~/types'

import { getChartDisplayOptions } from './chartDisplayOptions'
import { getChartAlternatives } from './chartRecommendations'

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
                ChartDisplayType.ActionsBarValue,
            ],
        },
        {
            name: 'puts the world map first for a country breakdown, skips breakdown-dropping types and demotes vertical bars',
            query: makeTrendsQuery({
                breakdownFilter: { breakdowns: [{ property: '$geoip_country_code', type: 'event' }] },
            }),
            expected: [
                ChartDisplayType.WorldMap,
                ChartDisplayType.ActionsAreaGraph,
                ChartDisplayType.ActionsBarValue,
                ChartDisplayType.ActionsLineGraphCumulative,
            ],
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
            expected: [
                ChartDisplayType.WorldMap,
                ChartDisplayType.Metric,
                ChartDisplayType.ActionsUnstackedBar,
                ChartDisplayType.ActionsAreaGraph,
            ],
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
            expected: [
                ChartDisplayType.BoxPlot,
                ChartDisplayType.Metric,
                ChartDisplayType.ActionsUnstackedBar,
                ChartDisplayType.ActionsAreaGraph,
            ],
        },
        {
            name: 'puts the box plot first for a moving average',
            query: makeTrendsQuery({
                trendsFilter: { display: ChartDisplayType.ActionsLineGraph, smoothingIntervals: 7 },
            }),
            expected: [
                ChartDisplayType.BoxPlot,
                ChartDisplayType.Metric,
                ChartDisplayType.ActionsUnstackedBar,
                ChartDisplayType.ActionsAreaGraph,
            ],
        },
        {
            name: 'prefers other total value charts when viewing a pie chart',
            query: makeTrendsQuery({ trendsFilter: { display: ChartDisplayType.ActionsPie } }),
            expected: [
                ChartDisplayType.ActionsDonut,
                ChartDisplayType.ActionsBarValue,
                ChartDisplayType.Metric,
                ChartDisplayType.ActionsUnstackedBar,
            ],
        },
    ])('$name', ({ query, expected }) => {
        expect(getChartAlternatives(compatibleOptions, query).map((option) => option.display)).toEqual(expected)
    })
})
