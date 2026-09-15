import { NodeKind } from '~/queries/schema/schema-general'
import type { TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, PropertyFilterType, PropertyMathType, PropertyOperator } from '~/types'

import { getChartAlternatives, getChartDisplayChangeWarning, getChartDisplayOptions } from './chartDisplayOptions'

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

describe('getChartDisplayOptions', () => {
    it('disables chart types the insight cannot render and says why', () => {
        const options = getChartDisplayOptions({
            isTrends: true,
            hasSingleSeriesOutput: false,
            hasTrendsFormula: true,
            breakdown: 'browser',
            boxPlotMissingProperty: true,
            hasMetricInsight: false,
        })
        const optionsByDisplay = new Map(
            options.flatMap((group) => group.options).map((option) => [option.display, option])
        )

        expect(optionsByDisplay.has(ChartDisplayType.Metric)).toBe(false)
        expect(optionsByDisplay.get(ChartDisplayType.BoldNumber)?.disabledReason).toBe(
            'This type currently only supports insights with one series, and this insight has multiple series.'
        )
        expect(optionsByDisplay.get(ChartDisplayType.BoxPlot)?.disabledReason).toBe(
            'Select a numeric property to use a box plot.'
        )
        expect(optionsByDisplay.get(ChartDisplayType.WorldMap)?.disabledReason).toBe(
            "This type isn't available, because it doesn't support formulas."
        )
        expect(optionsByDisplay.get(ChartDisplayType.ActionsLineGraph)?.disabledReason).toBeUndefined()

        const listBreakdownOptions = getChartDisplayOptions({
            isTrends: true,
            hasSingleSeriesOutput: true,
            hasTrendsFormula: false,
            breakdowns: [{ property: '$geoip_country_code', type: 'event' }],
            boxPlotMissingProperty: false,
            hasMetricInsight: false,
        })
        expect(
            listBreakdownOptions.flatMap((group) => group.options).find((o) => o.display === ChartDisplayType.WorldMap)
                ?.disabledReason
        ).toBeUndefined()
    })

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

    it('warns only when a chart type changes the query beyond its display', () => {
        expect(
            getChartDisplayChangeWarning(
                ChartDisplayType.BoxPlot,
                makeTrendsQuery({
                    trendsFilter: {
                        display: ChartDisplayType.ActionsLineGraph,
                        formulaNodes: [{ formula: 'A / B', custom_name: '' }],
                    },
                })
            )?.title
        ).toBe('This chart type removes the formula')
        expect(
            getChartDisplayChangeWarning(
                ChartDisplayType.WorldMap,
                makeTrendsQuery({
                    breakdownFilter: { breakdown: '$geoip_country_name', breakdown_type: 'person' },
                })
            )?.title
        ).toBe('This chart type changes the breakdown to Country code')
        expect(
            getChartDisplayChangeWarning(
                ChartDisplayType.WorldMap,
                makeTrendsQuery({
                    breakdownFilter: { breakdowns: [{ property: '$geoip_country_code', type: 'event' }] },
                })
            )
        ).toBeNull()
        expect(
            getChartDisplayChangeWarning(
                ChartDisplayType.BoldNumber,
                makeTrendsQuery({ breakdownFilter: { breakdown: 'browser', breakdown_type: 'event' } })
            )
        ).toBeNull()
    })
})
