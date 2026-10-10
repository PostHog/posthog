import { normalizeAxisLabel } from '@posthog/quill-charts'

import {
    METRIC_COLOR_BY_DIRECTION_DEFAULT,
    METRIC_SHOW_CHANGE_DEFAULT,
    METRIC_SUMMARY_DEFAULT,
} from 'lib/components/Metric/metricSummary'
import { smoothingOptions } from 'lib/components/SmoothingFilter/smoothings'
import { PART_OF_WHOLE_DISPLAY_TYPES, PIE_DISPLAY_TYPES } from 'lib/constants'
import { DEFAULT_DECIMAL_PLACES } from 'lib/utils/numbers'
import { defaultAggregationAxisFormatForDisplay } from 'scenes/insights/aggregationAxisFormat'
import type { AggregationAxisFormat } from 'scenes/insights/aggregationAxisFormat'

import { BAR_DISPLAYS, LINE_DISPLAYS, displayMatches } from '~/queries/nodes/InsightViz/displayTypes'
import { ResultCustomizationBy } from '~/queries/schema/schema-general'
import type { TrendsFilter } from '~/queries/schema/schema-general'
import { AnnotationScope, ChartDisplayType } from '~/types'
import type { IntervalType } from '~/types'

/** Also the suffix of each control's `data-attr`, so these are frozen once shipped. */
export type ChartSettingId =
    | 'legend'
    | 'legend-position'
    | 'value-labels'
    | 'percent-stack'
    | 'stack-breakdown'
    | 'slice-names'
    | 'pie-total'
    | 'exclude-outliers'
    | 'metric-summary'
    | 'metric-show-change'
    | 'metric-color-by-trend'
    | 'annotations'
    | 'color-by'
    | 'unit'
    | 'unit-prefix'
    | 'unit-suffix'
    | 'decimal-places'
    | 'x-axis-label'
    | 'y-axis-label'
    | 'multiple-y-axes'
    | 'scale'
    | 'begin-at-zero'
    | 'y-axis-min'
    | 'y-axis-max'
    | 'line-style'
    | 'smoothing'
    | 'trend-lines'
    | 'moving-average'
    | 'moving-average-intervals'
    | 'confidence-intervals'
    | 'confidence-level'
    | 'alert-threshold-lines'

export type ChartSettingValue = string | number | boolean | null

export interface ChartSettingOption {
    value: string
    label: string
}

interface ChartSettingBase {
    id: ChartSettingId
    label: string
    /** Why the setting cannot change right now. The control is disabled and shows this text. */
    disabledReason?: string
    /** The setting refines the one above it, so it is indented under it. */
    nested?: boolean
}

export type ChartSetting =
    | (ChartSettingBase & { kind: 'switch'; checked: boolean })
    /** A few options that fit side by side. */
    | (ChartSettingBase & { kind: 'choice'; value: string; options: ChartSettingOption[] })
    | (ChartSettingBase & { kind: 'select'; value: string; options: ChartSettingOption[] })
    | (ChartSettingBase & { kind: 'text'; value: string; placeholder: string })
    | (ChartSettingBase & {
          kind: 'number'
          value: number | null
          placeholder?: string
          min?: number
          max?: number
          /** The value is a count, so a fraction is rounded. */
          integer?: boolean
          suffix?: string
          error?: string
      })

export interface ChartSettingsGroup {
    key: 'general' | 'values' | 'axes' | 'lines' | 'overlays'
    title: string
    settings: ChartSetting[]
}

export interface ChartSettingsInput {
    display: ChartDisplayType | null | undefined
    trendsFilter: TrendsFilter | null | undefined
    interval: IntervalType | null | undefined
    hasBreakdown: boolean
    isNonTimeSeriesDisplay: boolean
    hasLegend: boolean
    usesInChartLegend: boolean
    showLegend: boolean
    legendPosition: string | null | undefined
    supportsValueOnSeries: boolean
    showValuesOnSeries: boolean
    showLabelOnSeries: boolean
    supportsPercentStackView: boolean
    showPercentStackView: boolean
    supportsBarValueStacking: boolean
    supportsResultCustomizationBy: boolean
    resultCustomizationBy: ResultCustomizationBy
    yAxisScaleType: string | null | undefined
    showMultipleYAxes: boolean
    showAlertThresholdLines: boolean
    showAnnotations: boolean | null | undefined
    annotationsScope: AnnotationScope | null | undefined
    mightContainFractionalNumbers: boolean
    showConfidenceIntervals: boolean
    confidenceLevel: number
    showMovingAverage: boolean
    movingAverageIntervals: number
    pieTotalShown: boolean
}

interface ChartKind {
    isLine: boolean
    isBar: boolean
    isPie: boolean
    isPartOfWhole: boolean
    isBoxPlot: boolean
    isSlopeGraph: boolean
    isMetric: boolean
    isCalendarHeatmap: boolean
    /** The chart has no points between its first and last interval to draw axes, scales and overlays on. */
    isNotContinuous: boolean
}

const GOAL_LINE_DISPLAYS = [
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsLineGraphCumulative,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsUnstackedBar,
]

const LEGEND_POSITION_OPTIONS: ChartSettingOption[] = [
    { value: 'top', label: 'Top' },
    { value: 'bottom', label: 'Bottom' },
    { value: 'left', label: 'Left' },
    { value: 'right', label: 'Right' },
]

const ANNOTATION_OPTIONS: ChartSettingOption[] = [
    { value: 'all', label: 'All' },
    { value: 'none', label: 'None' },
    { value: AnnotationScope.Insight, label: 'Insight' },
    { value: AnnotationScope.Dashboard, label: 'Dashboard' },
    { value: AnnotationScope.Project, label: 'Project' },
    { value: AnnotationScope.Organization, label: 'Organization' },
]

const UNIT_OPTIONS: { value: AggregationAxisFormat; label: string }[] = [
    { value: 'numeric', label: 'None' },
    { value: 'duration', label: 'Duration (s)' },
    { value: 'duration_ms', label: 'Duration (ms)' },
    { value: 'duration_ns', label: 'Duration (ns)' },
    { value: 'percentage', label: 'Percent (0 to 100)' },
    { value: 'percentage_scaled', label: 'Percent (0 to 1)' },
    { value: 'currency', label: 'Currency' },
    { value: 'short', label: 'Short number' },
]

function chartKind({ display, isNonTimeSeriesDisplay }: ChartSettingsInput): ChartKind {
    const isSlopeGraph = display === ChartDisplayType.SlopeGraph
    const isMetric = display === ChartDisplayType.Metric
    return {
        // A trends insight with no display set draws a line chart.
        isLine: !display || displayMatches(display, LINE_DISPLAYS),
        isBar: displayMatches(display, BAR_DISPLAYS),
        isPie: !!display && PIE_DISPLAY_TYPES.includes(display),
        isPartOfWhole: !!display && PART_OF_WHOLE_DISPLAY_TYPES.includes(display),
        isBoxPlot: display === ChartDisplayType.BoxPlot,
        isSlopeGraph,
        isMetric,
        isCalendarHeatmap: display === ChartDisplayType.CalendarHeatmap,
        isNotContinuous: isNonTimeSeriesDisplay || isMetric || isSlopeGraph,
    }
}

function legendSettings(input: ChartSettingsInput): ChartSetting[] {
    if (!input.hasLegend) {
        return []
    }
    const settings: ChartSetting[] = [{ kind: 'switch', id: 'legend', label: 'Legend', checked: input.showLegend }]
    if (input.usesInChartLegend && input.showLegend) {
        settings.push({
            kind: 'choice',
            id: 'legend-position',
            label: 'Legend position',
            // An insight saved before positions existed draws its legend on the right.
            value: input.legendPosition ?? 'right',
            options: LEGEND_POSITION_OPTIONS,
            nested: true,
        })
    }
    return settings
}

function generalSettings(input: ChartSettingsInput): ChartSetting[] {
    const kind = chartKind(input)
    const { trendsFilter, display } = input
    if (kind.isCalendarHeatmap) {
        return []
    }
    if (kind.isBoxPlot) {
        return [
            ...legendSettings(input),
            {
                kind: 'switch',
                id: 'exclude-outliers',
                label: 'Exclude outliers',
                checked: trendsFilter?.excludeBoxPlotOutliers !== false,
            },
        ]
    }
    // A slope graph draws only the first and last interval of each series, so only the legend applies.
    if (kind.isSlopeGraph) {
        return legendSettings(input)
    }

    const settings: ChartSetting[] = []
    if (kind.isMetric) {
        settings.push(
            {
                kind: 'choice',
                id: 'metric-summary',
                label: 'Headline value',
                value: trendsFilter?.metricSummary ?? METRIC_SUMMARY_DEFAULT,
                options: [
                    { value: 'total', label: 'Total' },
                    { value: 'average', label: 'Average' },
                    { value: 'latest', label: 'Latest' },
                ],
            },
            {
                kind: 'switch',
                id: 'metric-show-change',
                label: 'Show change',
                checked: trendsFilter?.metricShowChange ?? METRIC_SHOW_CHANGE_DEFAULT,
            },
            {
                kind: 'switch',
                id: 'metric-color-by-trend',
                label: 'Color by trend',
                checked: trendsFilter?.metricColorByDirection ?? METRIC_COLOR_BY_DIRECTION_DEFAULT,
            }
        )
    }
    if (input.supportsValueOnSeries) {
        settings.push({
            kind: 'switch',
            id: 'value-labels',
            label: 'Values on series',
            checked: input.showValuesOnSeries,
        })
    }
    if (input.supportsPercentStackView) {
        settings.push({
            kind: 'switch',
            id: 'percent-stack',
            label: 'Show as % of total',
            checked: input.showPercentStackView,
        })
    }
    if (input.supportsBarValueStacking) {
        settings.push({
            kind: 'switch',
            id: 'stack-breakdown',
            label: 'Stack breakdown values',
            checked: !!trendsFilter?.stackBreakdownValues,
        })
    }
    settings.push(...legendSettings(input))
    if (kind.isPie) {
        settings.push({ kind: 'switch', id: 'slice-names', label: 'Names on slices', checked: input.showLabelOnSeries })
    }
    if (kind.isPartOfWhole) {
        settings.push({
            kind: 'switch',
            id: 'pie-total',
            label: display === ChartDisplayType.ActionsDonut ? 'Total in center' : 'Total below chart',
            checked: input.pieTotalShown,
        })
    }
    if (!kind.isNotContinuous) {
        settings.push({
            kind: 'select',
            id: 'annotations',
            label: 'Annotations',
            value: input.showAnnotations === false ? 'none' : (input.annotationsScope ?? 'all'),
            options: ANNOTATION_OPTIONS,
        })
    }
    if (input.supportsResultCustomizationBy) {
        settings.push({
            kind: 'choice',
            id: 'color-by',
            label: 'Assign colors by',
            value: input.resultCustomizationBy,
            options: [
                { value: ResultCustomizationBy.Value, label: 'Name' },
                { value: ResultCustomizationBy.Position, label: 'Rank' },
            ],
        })
    }
    return settings
}

function valueSettings(input: ChartSettingsInput): ChartSetting[] {
    const kind = chartKind(input)
    const { trendsFilter } = input
    if (kind.isCalendarHeatmap) {
        return []
    }
    const settings: ChartSetting[] = []
    // Percentages replace the raw values, so no unit applies. A pie can show both together.
    if (!input.showPercentStackView || (kind.isPie && input.showValuesOnSeries)) {
        settings.push(
            {
                kind: 'select',
                id: 'unit',
                label: 'Unit',
                value:
                    trendsFilter?.aggregationAxisFormat ??
                    defaultAggregationAxisFormatForDisplay(input.display) ??
                    'numeric',
                options: UNIT_OPTIONS,
            },
            {
                kind: 'text',
                id: 'unit-prefix',
                label: 'Prefix',
                value: trendsFilter?.aggregationAxisPrefix ?? '',
                placeholder: 'None',
            },
            {
                kind: 'text',
                id: 'unit-suffix',
                label: 'Suffix',
                value: trendsFilter?.aggregationAxisPostfix ?? '',
                placeholder: 'None',
            }
        )
    }
    if (input.mightContainFractionalNumbers) {
        settings.push({
            kind: 'number',
            id: 'decimal-places',
            label: 'Decimal places',
            value: trendsFilter?.decimalPlaces ?? null,
            placeholder: String(DEFAULT_DECIMAL_PLACES),
            min: 0,
            max: 9,
            integer: true,
        })
    }
    return settings
}

function axisSettings(input: ChartSettingsInput): ChartSetting[] {
    const kind = chartKind(input)
    const { trendsFilter } = input
    const settings: ChartSetting[] = []
    if (kind.isLine || kind.isBar) {
        settings.push(
            {
                kind: 'text',
                id: 'x-axis-label',
                label: 'X-axis label',
                value: trendsFilter?.xAxisLabel ?? '',
                placeholder: 'None',
            },
            {
                kind: 'text',
                id: 'y-axis-label',
                label: 'Y-axis label',
                value: trendsFilter?.yAxisLabel ?? '',
                placeholder: 'None',
            }
        )
    }
    if (kind.isNotContinuous) {
        return settings
    }
    if (!kind.isBoxPlot) {
        settings.push({
            kind: 'switch',
            id: 'multiple-y-axes',
            label: 'Multiple y-axes',
            checked: input.showMultipleYAxes,
        })
    }
    if (kind.isCalendarHeatmap) {
        return settings
    }
    settings.push({
        kind: 'choice',
        id: 'scale',
        label: 'Scale',
        value: input.yAxisScaleType || 'linear',
        options: [
            { value: 'linear', label: 'Linear' },
            { value: 'log10', label: 'Logarithmic' },
        ],
    })
    // A bar shows a value as its length from zero, so a range that starts elsewhere would misread.
    if (kind.isLine) {
        const rangeDisabledReason =
            input.yAxisScaleType === 'log10'
                ? 'Not available on a logarithmic scale.'
                : input.showPercentStackView
                  ? 'Not available while showing percentages.'
                  : undefined
        const beginsAtZero = trendsFilter?.yAxisStartAtZero !== false
        const min = typeof trendsFilter?.yAxisMin === 'number' ? trendsFilter.yAxisMin : null
        const max = typeof trendsFilter?.yAxisMax === 'number' ? trendsFilter.yAxisMax : null
        settings.push({
            kind: 'switch',
            id: 'begin-at-zero',
            label: 'Begin at zero',
            checked: beginsAtZero,
            disabledReason: rangeDisabledReason,
        })
        // The minimum is hidden and not cleared while the axis begins at zero, so it applies again later.
        if (!beginsAtZero) {
            settings.push({
                kind: 'number',
                id: 'y-axis-min',
                label: 'Minimum',
                value: min,
                placeholder: 'Auto',
                disabledReason: rangeDisabledReason,
            })
        }
        settings.push({
            kind: 'number',
            id: 'y-axis-max',
            label: 'Maximum',
            value: max,
            placeholder: 'Auto',
            disabledReason: rangeDisabledReason,
            // The chart falls back to its automatic range for an inverted pair, which looks like a broken control.
            error:
                !beginsAtZero && min !== null && max !== null && min >= max
                    ? 'Maximum must be greater than minimum.'
                    : undefined,
        })
    }
    return settings
}

function lineSettings(input: ChartSettingsInput): ChartSetting[] {
    const kind = chartKind(input)
    const { display, interval, trendsFilter } = input
    const settings: ChartSetting[] = []
    if (kind.isLine) {
        settings.push({
            kind: 'choice',
            id: 'line-style',
            label: 'Line style',
            value: trendsFilter?.chartStyle?.curve || 'smooth',
            options: [
                { value: 'smooth', label: 'Smooth' },
                { value: 'linear', label: 'Straight' },
            ],
        })
    }
    const smoothings = interval ? smoothingOptions[interval] : []
    const canSmooth =
        !input.hasBreakdown &&
        (!display || display === ChartDisplayType.ActionsLineGraph || display === ChartDisplayType.ActionsAreaGraph)
    if (canSmooth && smoothings.length > 0) {
        settings.push({
            kind: 'select',
            id: 'smoothing',
            label: 'Smoothing',
            value: String(trendsFilter?.smoothingIntervals || 1),
            options: smoothings.map(({ value, label }) => ({ value: String(value), label })),
        })
    }
    return settings
}

function overlaySettings(input: ChartSettingsInput): ChartSetting[] {
    const kind = chartKind(input)
    const { display, interval, trendsFilter } = input
    if (kind.isNotContinuous || kind.isBoxPlot) {
        return []
    }
    const scaleDisabledReason =
        input.yAxisScaleType && input.yAxisScaleType !== 'linear' ? 'Only available on a linear scale.' : undefined
    const settings: ChartSetting[] = []
    if (
        !display ||
        display === ChartDisplayType.ActionsLineGraph ||
        display === ChartDisplayType.ActionsLineGraphCumulative
    ) {
        settings.push({
            kind: 'switch',
            id: 'trend-lines',
            label: 'Trend lines',
            checked: !scaleDisabledReason && !!trendsFilter?.showTrendLines,
            disabledReason: scaleDisabledReason,
        })
    }
    if (kind.isLine && display !== ChartDisplayType.ActionsLineGraphCumulative) {
        settings.push({
            kind: 'switch',
            id: 'moving-average',
            label: 'Moving average',
            checked: input.showMovingAverage,
            disabledReason: scaleDisabledReason,
        })
        if (input.showMovingAverage) {
            settings.push({
                kind: 'number',
                id: 'moving-average-intervals',
                label: 'Intervals',
                value: input.movingAverageIntervals,
                min: 2,
                integer: true,
                suffix: `${interval ?? 'day'}s`,
                nested: true,
            })
        }
        settings.push({
            kind: 'switch',
            id: 'confidence-intervals',
            label: 'Confidence intervals',
            checked: input.showConfidenceIntervals,
            disabledReason: scaleDisabledReason,
        })
        if (input.showConfidenceIntervals) {
            settings.push({
                kind: 'number',
                id: 'confidence-level',
                label: 'Confidence level',
                value: input.confidenceLevel,
                min: 0,
                max: 100,
                suffix: '%',
                nested: true,
            })
        }
    }
    settings.push({
        kind: 'switch',
        id: 'alert-threshold-lines',
        label: 'Alert threshold lines',
        checked: input.showAlertThresholdLines,
    })
    return settings
}

export function buildChartSettingsGroups(input: ChartSettingsInput): ChartSettingsGroup[] {
    const groups: ChartSettingsGroup[] = [
        { key: 'general', title: 'General', settings: generalSettings(input) },
        { key: 'values', title: 'Values', settings: valueSettings(input) },
        { key: 'axes', title: 'Axes', settings: axisSettings(input) },
        { key: 'lines', title: 'Lines', settings: lineSettings(input) },
        { key: 'overlays', title: 'Overlays', settings: overlaySettings(input) },
    ]
    return groups.filter((group) => group.settings.length > 0)
}

export function supportsGoalLines(display: ChartDisplayType | null | undefined): boolean {
    return GOAL_LINE_DISPLAYS.includes(display || ChartDisplayType.ActionsLineGraph)
}

function asNumber(value: ChartSettingValue): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function asText(value: ChartSettingValue): string | undefined {
    return typeof value === 'string' && value !== '' ? value : undefined
}

/** The change to the trends filter for a setting. Null for a setting stored outside the trends filter. */
export function chartSettingPatch(
    id: ChartSettingId,
    value: ChartSettingValue,
    input: ChartSettingsInput
): Partial<TrendsFilter> | null {
    switch (id) {
        case 'legend':
            return {
                showLegend: !!value,
                // Seed the position on first use, or a legend with none saved draws on the right.
                ...(value && input.usesInChartLegend && input.legendPosition == null
                    ? { legendPosition: 'bottom' as const }
                    : {}),
            }
        case 'legend-position':
            return { legendPosition: value as TrendsFilter['legendPosition'] }
        case 'value-labels':
            return { showValuesOnSeries: !!value }
        case 'percent-stack':
            return { showPercentStackView: !!value }
        case 'stack-breakdown':
            return { stackBreakdownValues: !!value }
        case 'slice-names':
            return { showLabelsOnSeries: !!value }
        case 'exclude-outliers':
            return { excludeBoxPlotOutliers: !!value }
        case 'metric-summary':
            return { metricSummary: value as TrendsFilter['metricSummary'] }
        case 'metric-show-change':
            return { metricShowChange: !!value }
        case 'metric-color-by-trend':
            return { metricColorByDirection: !!value }
        case 'annotations':
            return {
                showAnnotations: value === 'none' ? false : undefined,
                annotationsScope: value === 'all' || value === 'none' ? undefined : (value as AnnotationScope),
            }
        case 'color-by':
            return { resultCustomizationBy: value as ResultCustomizationBy }
        case 'unit':
            return { aggregationAxisFormat: value as AggregationAxisFormat }
        case 'unit-prefix':
            return { aggregationAxisPrefix: asText(value) }
        case 'unit-suffix':
            return { aggregationAxisPostfix: asText(value) }
        case 'decimal-places':
            return { decimalPlaces: asNumber(value) }
        case 'x-axis-label':
            return { xAxisLabel: normalizeAxisLabel(asText(value)) }
        case 'y-axis-label':
            return { yAxisLabel: normalizeAxisLabel(asText(value)) }
        case 'multiple-y-axes':
            return { showMultipleYAxes: !!value }
        case 'scale':
            return { yAxisScaleType: value as TrendsFilter['yAxisScaleType'] }
        case 'begin-at-zero':
            return { yAxisStartAtZero: value ? undefined : false }
        case 'y-axis-min':
            return { yAxisMin: asNumber(value) }
        case 'y-axis-max':
            return { yAxisMax: asNumber(value) }
        case 'line-style':
            return { chartStyle: { ...input.trendsFilter?.chartStyle, curve: value as 'smooth' | 'linear' } }
        case 'smoothing':
            return { smoothingIntervals: Number(value) || 1 }
        case 'trend-lines':
            return { showTrendLines: !!value }
        case 'moving-average':
            return { showMovingAverage: !!value }
        case 'moving-average-intervals':
            return { movingAverageIntervals: asNumber(value) }
        case 'confidence-intervals':
            return { showConfidenceIntervals: !!value }
        case 'confidence-level':
            return { confidenceLevel: asNumber(value) }
        case 'alert-threshold-lines':
            return { showAlertThresholdLines: !!value }
        case 'pie-total':
            return null
    }
}
