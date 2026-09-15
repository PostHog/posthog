import type { BreakdownFilter } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

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

const COUNTRY_PROPERTIES = new Set(['$geoip_country_code', '$geoip_country_name'])

function isCountryProperty(value: unknown): boolean {
    return typeof value === 'string' && COUNTRY_PROPERTIES.has(value)
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
    const hasSupportedCountryBreakdown = !hasMultipleBreakdowns && isCountryProperty(breakdown)
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
