import { NodeKind } from '~/queries/schema/schema-general'
import type { TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, PropertyFilterType, PropertyMathType, PropertyOperator } from '~/types'

import type { ChartDisplayOptionEligibility } from './chartDisplayOptions'
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

const RENDERS_EVERYTHING: ChartDisplayOptionEligibility = {
    isTrends: true,
    hasSingleSeriesOutput: true,
    hasTrendsFormula: false,
    boxPlotMissingProperty: false,
    hasMetricInsight: false,
}

function disabledReasons(eligibility: ChartDisplayOptionEligibility): Map<ChartDisplayType, string | undefined> {
    return new Map(
        getChartDisplayOptions(eligibility)
            .flatMap((group) => group.options)
            .map((option) => [option.display, option.disabledReason])
    )
}

describe('getChartDisplayOptions', () => {
    it.each([
        [
            'not Trends',
            { ...RENDERS_EVERYTHING, isTrends: false },
            ChartDisplayType.SlopeGraph,
            'This type is only available in Trends.',
        ],
        [
            'multiple series',
            { ...RENDERS_EVERYTHING, hasSingleSeriesOutput: false },
            ChartDisplayType.BoldNumber,
            'This type currently only supports insights with one series, and this insight has multiple series.',
        ],
        [
            'box plot without a numeric property',
            { ...RENDERS_EVERYTHING, boxPlotMissingProperty: true },
            ChartDisplayType.BoxPlot,
            'Select a numeric property to use a box plot.',
        ],
        [
            'world map with a formula',
            { ...RENDERS_EVERYTHING, hasTrendsFormula: true },
            ChartDisplayType.WorldMap,
            "This type isn't available, because it doesn't support formulas.",
        ],
        [
            'world map with a breakdown other than country',
            { ...RENDERS_EVERYTHING, breakdown: 'browser' },
            ChartDisplayType.WorldMap,
            "This type isn't available, because there's a breakdown other than by Country Code or Country Name properties.",
        ],
        [
            'world map with two breakdowns',
            {
                ...RENDERS_EVERYTHING,
                breakdowns: [{ property: '$geoip_country_code' }, { property: 'browser' }],
            },
            ChartDisplayType.WorldMap,
            "This type isn't available, because there's a breakdown other than by Country Code or Country Name properties.",
        ],
        [
            'world map with one country breakdown',
            { ...RENDERS_EVERYTHING, breakdowns: [{ property: '$geoip_country_code' }] },
            ChartDisplayType.WorldMap,
            undefined,
        ],
        ['nothing in the way', RENDERS_EVERYTHING, ChartDisplayType.ActionsLineGraph, undefined],
    ])('says why %s disables a chart type', (_case, eligibility, display, disabledReason) => {
        const reasons = disabledReasons(eligibility)

        expect(reasons.has(display)).toBe(true)
        expect(reasons.get(display)).toBe(disabledReason)
    })

    it.each([
        [true, true],
        [false, false],
    ])('offers the metric chart type only behind its flag (%s)', (hasMetricInsight, isOffered) => {
        expect(disabledReasons({ ...RENDERS_EVERYTHING, hasMetricInsight }).has(ChartDisplayType.Metric)).toBe(
            isOffered
        )
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
            name: 'puts the world map first for a country breakdown and skips breakdown-dropping types',
            query: makeTrendsQuery({ breakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'event' } }),
            expected: [
                ChartDisplayType.WorldMap,
                ChartDisplayType.ActionsUnstackedBar,
                ChartDisplayType.ActionsAreaGraph,
                ChartDisplayType.ActionsBarValue,
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
                ChartDisplayType.BoldNumber,
                makeTrendsQuery({ breakdownFilter: { breakdown: 'browser', breakdown_type: 'event' } })
            )
        ).toBeNull()
    })
})
