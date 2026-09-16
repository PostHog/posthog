import { convertPropertyGroupToProperties } from 'lib/components/PropertyFilters/utils'
import { DISPLAY_TYPES_TO_CATEGORIES, NON_BREAKDOWN_DISPLAY_TYPES, PIE_DISPLAY_TYPES } from 'lib/constants'
import { isPropertyValueMath } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/mathUtils'

import type { BreakdownFilter, TrendsFilter, TrendsQuery } from '~/queries/schema/schema-general'
import { hasBreakdownFilter } from '~/queries/utils'
import { ChartDisplayCategory, ChartDisplayType, PropertyMathType } from '~/types'
import type { AnyPropertyFilter } from '~/types'

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

const COUNTRY_PROPERTIES = new Set(['$geoip_country_code', '$geoip_country_name'])

function isCountryProperty(value: unknown): boolean {
    return typeof value === 'string' && COUNTRY_PROPERTIES.has(value)
}

// Trends writes breakdowns as a list; older queries carry a single breakdown. Both count.
export function breakdownProperties(breakdownFilter?: BreakdownFilter | null): (string | number)[] {
    if (breakdownFilter?.breakdowns?.length) {
        return breakdownFilter.breakdowns.map((entry) => entry.property)
    }
    const single = breakdownFilter?.breakdown
    if (single == null) {
        return []
    }
    return Array.isArray(single) ? single : [single]
}

function breakdownTypeOf(breakdownFilter?: BreakdownFilter | null): string | null | undefined {
    return breakdownFilter?.breakdowns?.length ? breakdownFilter.breakdowns[0].type : breakdownFilter?.breakdown_type
}

function isSingleCountryBreakdown(breakdownFilter?: BreakdownFilter | null): boolean {
    const properties = breakdownProperties(breakdownFilter)
    return properties.length === 1 && isCountryProperty(properties[0])
}

export function hasTrendsFormula(trendsFilter?: TrendsFilter | null): boolean {
    return !!trendsFilter?.formula || !!trendsFilter?.formulas?.length || !!trendsFilter?.formulaNodes?.length
}

function worldMapBreakdownFilter(query: TrendsQuery): BreakdownFilter {
    const math = query.series?.[0]?.math ?? ''
    return {
        breakdown: '$geoip_country_code',
        breakdown_type: ['dau', 'weekly_active', 'monthly_active'].includes(math) ? 'person' : 'event',
    }
}

// The query a display selection produces; previews derive from it and selecting a tile applies it.
export function applyChartDisplay(query: TrendsQuery, display: ChartDisplayType): TrendsQuery {
    const next: TrendsQuery = { ...query, trendsFilter: { ...query.trendsFilter, display } }
    if (NON_BREAKDOWN_DISPLAY_TYPES.includes(display)) {
        next.breakdownFilter = undefined
    }
    if (display === ChartDisplayType.BoxPlot) {
        next.trendsFilter = { ...next.trendsFilter, formula: undefined, formulas: undefined, formulaNodes: [] }
    }
    if (display === ChartDisplayType.WorldMap) {
        next.breakdownFilter = worldMapBreakdownFilter(query)
    }
    return next
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
    const breakdownProps = breakdownProperties({ breakdown, breakdowns })
    const worldMapBreakdownDisabled =
        breakdownProps.length > 1 || breakdownProps.some((property) => !isCountryProperty(property))
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
                            : worldMapBreakdownDisabled
                              ? "This type isn't available, because there's a breakdown other than by Country Code or Country Name properties."
                              : undefined),
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

function hasCountryContext(query: TrendsQuery): boolean {
    if (isSingleCountryBreakdown(query.breakdownFilter)) {
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
        (query.series ?? []).some((node) => isPropertyValueMath(node.math) && node.math !== PropertyMathType.Sum) ||
        (query.trendsFilter?.smoothingIntervals ?? 1) > 1
    )
}

function rankRecommendations(query: TrendsQuery | null, currentDisplay: ChartDisplayType): ChartDisplayType[] {
    const boosted: ChartDisplayType[] = []
    if (query) {
        if (hasCountryContext(query)) {
            boosted.push(ChartDisplayType.WorldMap)
        }
        if (isStatistical(query)) {
            boosted.push(ChartDisplayType.BoxPlot)
        }
    }
    if (DISPLAY_TYPES_TO_CATEGORIES[currentDisplay] === ChartDisplayCategory.TotalValue) {
        boosted.push(...PIE_DISPLAY_TYPES, ChartDisplayType.ActionsBarValue)
    }
    return [...new Set([...boosted, ...DEFAULT_RECOMMENDATION_ORDER])]
}

export function getChartAlternatives(
    options: ChartDisplayOptionGroup[] | null | undefined,
    query: TrendsQuery | null
): ChartDisplayOption[] {
    const optionsByDisplay = new Map(
        (options ?? []).flatMap((group) => group.options).map((option) => [option.display, option])
    )
    const currentDisplay = query?.trendsFilter?.display ?? ChartDisplayType.ActionsLineGraph
    const hasBreakdown = hasBreakdownFilter(query?.breakdownFilter)
    return rankRecommendations(query, currentDisplay)
        .filter((recommended) => !hasBreakdown || !NON_BREAKDOWN_DISPLAY_TYPES.includes(recommended))
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
    if (display === ChartDisplayType.BoxPlot && hasTrendsFormula(query.trendsFilter)) {
        return {
            title: 'This chart type removes the formula',
            body: 'The box plot uses the numeric property values directly.',
        }
    }
    if (display === ChartDisplayType.WorldMap) {
        const current = query.breakdownFilter
        const next = worldMapBreakdownFilter(query)
        const properties = breakdownProperties(current)
        const alreadyMapBreakdown =
            properties.length === 1 &&
            properties[0] === next.breakdown &&
            breakdownTypeOf(current) === next.breakdown_type
        if (!alreadyMapBreakdown) {
            return {
                title: 'This chart type changes the breakdown to Country code',
                body: `The map uses ${next.breakdown_type} properties for this metric.`,
            }
        }
    }
    return null
}
