import type {
    GoalLineConfig,
    TimeSeriesBarChartConfig,
    TimeSeriesLineChartConfig,
    ValueDomain,
    XAxisConfig,
    YAxisConfig,
} from '@posthog/quill-charts'

import type { GoalLine, MetricsDisplaySettings, MetricsYAxisSettings } from '~/queries/schema/schema-general'

/** The config keys metrics sets. `TimeSeriesLineChartConfig` and `TimeSeriesBarChartConfig` declare
 * these identically, so one builder serves both charts. */
export type MetricsChartConfig = Pick<
    TimeSeriesLineChartConfig & TimeSeriesBarChartConfig,
    'xAxis' | 'yAxis' | 'goalLines' | 'legend' | 'tooltip'
>

/** Field rename from the persisted schema shape onto quill's. Product analytics has an equivalent
 * mapper, but it maps its own `GoalLineLike` and lives across a product boundary we can't import
 * over; promoting one copy into `lib/charts` is worth doing once a third caller appears. */
function goalLineToConfig(line: GoalLine): GoalLineConfig {
    return {
        value: line.value,
        label: line.label,
        displayLabel: line.displayLabel,
        color: line.borderColor,
        labelPosition: line.position,
        displayIfCrossed: line.displayIfCrossed,
    }
}

function goalLinesToConfigs(goalLines: GoalLine[] | undefined): GoalLineConfig[] | undefined {
    return goalLines?.length ? goalLines.map(goalLineToConfig) : undefined
}

function yAxisToConfig(yAxis: MetricsYAxisSettings | undefined): YAxisConfig | undefined {
    if (!yAxis) {
        return undefined
    }
    const config: YAxisConfig = {}
    if (yAxis.scale) {
        config.scale = yAxis.scale
    }
    if (yAxis.startAtZero !== undefined) {
        config.startAtZero = yAxis.startAtZero
    }
    if (yAxis.min !== undefined) {
        config.min = yAxis.min
    }
    if (yAxis.max !== undefined) {
        config.max = yAxis.max
    }
    // An all-defaults object would still override quill's own defaults, so emit nothing.
    return Object.keys(config).length > 0 ? config : undefined
}

/** Bar charts ignore `YAxisConfig.min`/`max` — a bar encodes magnitude as length from zero, so quill
 * reads bounds from `valueDomain` instead. Without this the y-axis range control silently does
 * nothing on the bar display. */
export function metricsBarValueDomain(yAxis: MetricsYAxisSettings | undefined): ValueDomain | undefined {
    if (yAxis?.min === undefined && yAxis?.max === undefined) {
        return undefined
    }
    return {
        ...(yAxis.min !== undefined ? { min: yAxis.min } : {}),
        ...(yAxis.max !== undefined ? { max: yAxis.max } : {}),
    }
}

export function buildMetricsChartConfig({
    display,
    xAxis,
    seriesCount,
    labelFormatter,
}: {
    display: MetricsDisplaySettings | undefined
    xAxis: XAxisConfig
    seriesCount: number
    labelFormatter: (label: string) => string
}): MetricsChartConfig {
    const yAxis = yAxisToConfig(display?.yAxis)
    const goalLines = goalLinesToConfigs(display?.goalLines)
    return {
        xAxis,
        // Keys stay absent rather than explicitly undefined: `useChartConfig` filters undefined
        // values out before spreading quill's defaults, so an emitted key would win over them.
        ...(yAxis ? { yAxis } : {}),
        ...(goalLines ? { goalLines } : {}),
        legend: { show: seriesCount > 1, interactive: true },
        tooltip: { placement: 'cursor', pinnable: true, labelFormatter },
    }
}
