import { convertPropertyGroupToProperties } from 'lib/components/PropertyFilters/utils'

import type { AnyPropertyFilter, BreakdownFilter, TrendsQuery } from '~/queries/schema/schema-general'
import { ChartDisplayType, PropertyMathType } from '~/types'

export type ChartDisplayIcon =
    | 'area'
    | 'bar'
    | 'calendarHeatmap'
    | 'cumulative'
    | 'donut'
    | 'horizontalBar'
    | 'line'
    | 'metric'
    | 'number'
    | 'pie'
    | 'table'
    | 'worldMap'

export interface ChartDisplayOption {
    display: ChartDisplayType
    description: string
    icon: ChartDisplayIcon
    label: string
    tooltip?: string
    disabledReason?: string
}

export interface ChartDisplayOptionGroup {
    title: string
    options: ChartDisplayOption[]
}

export interface ChartDisplayOptionEligibility {
    boxPlotMissingProperty: boolean
    hasMetricInsight: boolean
    hasSingleSeriesOutput: boolean
    hasTrendsFormula: boolean
    isTrends: boolean
    breakdown?: BreakdownFilter['breakdown']
    breakdowns?: BreakdownFilter['breakdowns']
}

export interface ChartDisplayChangeWarning {
    body: string
    title: string
}

export function getChartDisplayOptions({
    boxPlotMissingProperty,
    hasMetricInsight,
    hasSingleSeriesOutput,
    hasTrendsFormula,
    isTrends,
    breakdown,
    breakdowns,
}: ChartDisplayOptionEligibility): ChartDisplayOptionGroup[] {
    const hasMultipleBreakdowns = !!breakdowns?.length
    const hasSupportedCountryBreakdown =
        !hasMultipleBreakdowns && (breakdown === '$geoip_country_code' || breakdown === '$geoip_country_name')
    const trendsOnlyDisabledReason = !isTrends ? 'This type is only available in Trends.' : undefined
    const singleSeriesOnlyDisabledReason = !hasSingleSeriesOutput
        ? 'This type currently only supports insights with one series, and this insight has multiple series.'
        : undefined
    const boxPlotDisabledReason =
        trendsOnlyDisabledReason ||
        (boxPlotMissingProperty ? 'Select a numeric property to use a box plot.' : undefined)

    return [
        {
            title: 'Time series',
            options: [
                {
                    display: ChartDisplayType.ActionsLineGraph,
                    icon: 'line',
                    label: 'Line chart',
                    description: 'Trends over time plotted as a continuous line.',
                },
                {
                    display: ChartDisplayType.ActionsAreaGraph,
                    icon: 'area',
                    label: 'Area chart',
                    description: 'Trends over time plotted as a shaded area.',
                },
                {
                    display: ChartDisplayType.ActionsUnstackedBar,
                    icon: 'bar',
                    label: 'Bar chart',
                    description: 'Trends over time as vertical bars side-by-side.',
                },
                {
                    display: ChartDisplayType.ActionsBar,
                    icon: 'bar',
                    label: 'Stacked bar chart',
                    description: 'Trends over time as vertical bars.',
                },
                {
                    display: ChartDisplayType.BoxPlot,
                    icon: 'bar',
                    label: 'Box plot',
                    description: 'Distribution of a property over time showing quartiles.',
                    disabledReason: boxPlotDisabledReason,
                },
                {
                    display: ChartDisplayType.SlopeGraph,
                    icon: 'line',
                    label: 'Slope graph',
                    description: 'Change from the start to the end of the range, one line per series.',
                    disabledReason: trendsOnlyDisabledReason,
                },
            ],
        },
        {
            title: 'Cumulative time series',
            options: [
                {
                    display: ChartDisplayType.ActionsLineGraphCumulative,
                    icon: 'cumulative',
                    label: 'Line chart (cumulative)',
                    description: 'Accumulating values over time as a continuous line.',
                    disabledReason: trendsOnlyDisabledReason,
                },
            ],
        },
        {
            title: 'Total value',
            options: [
                {
                    display: ChartDisplayType.BoldNumber,
                    icon: 'number',
                    label: 'Number',
                    description: 'A big number showing the total value.',
                    disabledReason: trendsOnlyDisabledReason || singleSeriesOnlyDisabledReason,
                },
                ...(hasMetricInsight
                    ? [
                          {
                              display: ChartDisplayType.Metric,
                              icon: 'metric' as const,
                              label: 'Metric',
                              description: 'A headline value with a sparkline and period-over-period change.',
                              disabledReason: trendsOnlyDisabledReason || singleSeriesOnlyDisabledReason,
                          },
                      ]
                    : []),
                {
                    display: ChartDisplayType.ActionsPie,
                    icon: 'pie',
                    label: 'Pie chart',
                    description: 'Proportions of a whole as a pie.',
                    disabledReason: trendsOnlyDisabledReason,
                },
                {
                    display: ChartDisplayType.ActionsDonut,
                    icon: 'donut',
                    label: 'Donut chart',
                    description: 'Proportions of a whole as a ring.',
                    disabledReason: trendsOnlyDisabledReason,
                },
                {
                    display: ChartDisplayType.ActionsBarValue,
                    icon: 'horizontalBar',
                    label: 'Bar chart',
                    description: 'Total values as horizontal bars.',
                    disabledReason: trendsOnlyDisabledReason,
                },
                {
                    display: ChartDisplayType.ActionsTable,
                    icon: 'table',
                    label: 'Table',
                    description: 'Total values in a table view.',
                },
            ],
        },
        {
            title: 'Visualizations',
            options: [
                {
                    display: ChartDisplayType.WorldMap,
                    icon: 'worldMap',
                    label: 'World map',
                    description: 'Values per country on a map.',
                    tooltip: 'Visualize data by country.',
                    disabledReason:
                        trendsOnlyDisabledReason ||
                        (hasTrendsFormula
                            ? "This type isn't available, because it doesn't support formulas."
                            : !hasMultipleBreakdowns && (!breakdown || hasSupportedCountryBreakdown)
                              ? undefined
                              : "This type isn't available, because there's a breakdown other than by Country Code or Country Name properties."),
                },
                {
                    display: ChartDisplayType.CalendarHeatmap,
                    icon: 'calendarHeatmap',
                    label: 'Calendar heatmap',
                    description: 'Values per day and hour.',
                    disabledReason: trendsOnlyDisabledReason || singleSeriesOnlyDisabledReason,
                },
            ],
        },
    ]
}

export const BREAKDOWN_FREE_DISPLAYS = new Set<ChartDisplayType>([
    ChartDisplayType.BoldNumber,
    ChartDisplayType.Metric,
    ChartDisplayType.CalendarHeatmap,
    ChartDisplayType.BoxPlot,
])

const COUNTRY_PROPERTIES = new Set(['$geoip_country_code', '$geoip_country_name'])

const STATISTICAL_MATHS = new Set<string>([
    PropertyMathType.Average,
    PropertyMathType.Median,
    PropertyMathType.Minimum,
    PropertyMathType.Maximum,
    PropertyMathType.P75,
    PropertyMathType.P90,
    PropertyMathType.P95,
    PropertyMathType.P99,
])

const TOTAL_VALUE_DISPLAYS = new Set<ChartDisplayType>([
    ChartDisplayType.ActionsPie,
    ChartDisplayType.ActionsDonut,
    ChartDisplayType.ActionsBarValue,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.ActionsTable,
])

const DEFAULT_RECOMMENDATION_ORDER = [
    ChartDisplayType.Metric,
    ChartDisplayType.ActionsUnstackedBar,
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsBarValue,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsLineGraphCumulative,
    ChartDisplayType.ActionsPie,
    ChartDisplayType.ActionsDonut,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.BoxPlot,
    ChartDisplayType.WorldMap,
]

function isCountryProperty(value: unknown): boolean {
    return typeof value === 'string' && COUNTRY_PROPERTIES.has(value)
}

function hasCountryContext(query: TrendsQuery): boolean {
    const breakdownFilter = query.breakdownFilter
    if (!breakdownFilter?.breakdowns?.length && isCountryProperty(breakdownFilter?.breakdown)) {
        return true
    }
    const filters: AnyPropertyFilter[] = [
        ...(convertPropertyGroupToProperties(query.properties) ?? []),
        ...(query.series ?? []).flatMap((node) => node.properties ?? []),
    ]
    return filters.some((filter) => isCountryProperty(filter.key))
}

function isStatistical(query: TrendsQuery): boolean {
    return (
        (query.series ?? []).some((node) => STATISTICAL_MATHS.has(node.math ?? '')) ||
        (query.trendsFilter?.smoothingIntervals ?? 1) > 1
    )
}

function rankRecommendations(query: TrendsQuery | null, currentDisplay: ChartDisplayType): ChartDisplayType[] {
    const boosted: ChartDisplayType[] = []
    if (query && hasCountryContext(query)) {
        boosted.push(ChartDisplayType.WorldMap)
    }
    if (query && isStatistical(query)) {
        boosted.push(ChartDisplayType.BoxPlot)
    }
    if (TOTAL_VALUE_DISPLAYS.has(currentDisplay)) {
        boosted.push(ChartDisplayType.ActionsPie, ChartDisplayType.ActionsDonut, ChartDisplayType.ActionsBarValue)
    }
    return [...new Set([...boosted, ...DEFAULT_RECOMMENDATION_ORDER])]
}

export function getChartAlternatives(
    options: ChartDisplayOptionGroup[] | null | undefined,
    display: ChartDisplayType | undefined,
    query: TrendsQuery | null = null
): ChartDisplayOption[] {
    const optionsByDisplay = new Map(
        (options ?? []).flatMap((group) => group.options).map((option) => [option.display, option])
    )
    const currentDisplay = display ?? ChartDisplayType.ActionsLineGraph
    const breakdownFilter = query?.breakdownFilter
    const hasBreakdown = !!breakdownFilter?.breakdown || !!breakdownFilter?.breakdowns?.length
    return rankRecommendations(query, currentDisplay)
        .filter(
            (recommended) =>
                (!hasBreakdown || !BREAKDOWN_FREE_DISPLAYS.has(recommended)) &&
                (recommended !== ChartDisplayType.BoldNumber || !optionsByDisplay.has(ChartDisplayType.Metric))
        )
        .map((recommended) => optionsByDisplay.get(recommended))
        .filter(
            (option): option is ChartDisplayOption =>
                !!option && option.display !== currentDisplay && !option.disabledReason
        )
        .slice(0, 4)
}

export function getChartDisplayChangeWarning(
    display: ChartDisplayType,
    query: TrendsQuery
): ChartDisplayChangeWarning | null {
    const breakdownFilter = query.breakdownFilter
    const breakdown = breakdownFilter?.breakdown
    const trendsFilter = query.trendsFilter
    const dropsFormula =
        display === ChartDisplayType.BoxPlot &&
        (!!trendsFilter?.formula || !!trendsFilter?.formulas?.length || !!trendsFilter?.formulaNodes?.length)
    const expectedMapBreakdownType = ['dau', 'weekly_active', 'monthly_active'].includes(query.series?.[0]?.math ?? '')
        ? 'person'
        : 'event'
    const changesMapBreakdown =
        display === ChartDisplayType.WorldMap &&
        (breakdown !== '$geoip_country_code' ||
            !!breakdownFilter?.breakdowns?.length ||
            breakdownFilter?.breakdown_type !== expectedMapBreakdownType)

    if (dropsFormula) {
        return {
            title: 'This chart type removes the formula',
            body: 'The box plot uses the numeric property values directly.',
        }
    }
    if (changesMapBreakdown) {
        return {
            title: 'This chart type changes the breakdown to Country code',
            body: `The map uses ${expectedMapBreakdownType === 'person' ? 'person' : 'event'} properties for this metric.`,
        }
    }
    return null
}
