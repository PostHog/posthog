import { type ReactElement, type ReactNode, useMemo } from 'react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { ChartTheme, PointClickData, TooltipConfig, TooltipContext } from '@posthog/quill-charts'

import type { CiRangesFn, GoalLineLike, TrendsChartDisplayOptions } from '../shared/trendsChartDisplayOptions'
import { buildTrendsLineTimeSeriesConfig, buildTrendsSeries, type TrendsResultLike } from './trendsChartTransforms'

// Presentational, dependency-neutral trends line chart. No kea, no `lib/*` / `~/*` imports — it
// turns plain results + display options into a quill `TimeSeriesLineChart`, so both the web trends
// container and the MCP UI app render the exact same view. Callers inject everything host-specific
// (theme, colors, tooltip, click handling, overlays).
export interface TrendsLineChartViewProps<R extends TrendsResultLike, M = unknown> {
    results: R[]
    labels: string[]
    theme: ChartTheme
    getColor: (r: R, index: number) => string
    displayOptions?: TrendsChartDisplayOptions
    getHidden?: (r: R) => boolean
    buildMeta?: (r: R, index: number) => M
    goalLines?: GoalLineLike[] | null
    ciRanges?: CiRangesFn
    incompletenessOffsetFromEnd?: number
    isStickiness?: boolean
    /** Overrides the auto date formatter (hosts without interval/timezone, e.g. MCP). */
    xAxisTickFormatter?: (value: string, index: number) => string | null
    valueLabelFormatter?: (value: number) => string
    tooltip?: (ctx: TooltipContext<M>) => ReactElement
    tooltipConfig?: TooltipConfig
    onPointClick?: (data: PointClickData) => void
    className?: string
    dataAttr?: string
    onError?: (error: Error) => void
    /** Overlays (annotations, alert thresholds) rendered inside the chart's layout context. */
    children?: ReactNode
}

export function TrendsLineChartView<R extends TrendsResultLike, M = unknown>({
    results,
    labels,
    theme,
    getColor,
    displayOptions = {},
    getHidden,
    buildMeta,
    goalLines,
    ciRanges,
    incompletenessOffsetFromEnd,
    isStickiness,
    xAxisTickFormatter,
    valueLabelFormatter,
    tooltip,
    tooltipConfig,
    onPointClick,
    className,
    dataAttr,
    onError,
    children,
}: TrendsLineChartViewProps<R, M>): ReactElement {
    const series = useMemo(
        () =>
            buildTrendsSeries<R, M>(results, {
                isArea: displayOptions.isArea,
                showMultipleYAxes: displayOptions.showMultipleYAxes,
                incompletenessOffsetFromEnd,
                isStickiness,
                getColor,
                getHidden,
                buildMeta,
            }),
        [results, displayOptions, incompletenessOffsetFromEnd, isStickiness, getColor, getHidden, buildMeta]
    )

    const config = useMemo(
        () =>
            buildTrendsLineTimeSeriesConfig<R>({
                results,
                trendsFilter: displayOptions.yFormatterFields,
                baseCurrency: displayOptions.baseCurrency,
                isPercentStackView: !!displayOptions.isPercentStackView,
                isStickiness,
                yAxisScaleType: displayOptions.yAxisScaleType,
                interval: displayOptions.interval,
                timezone: displayOptions.timezone,
                allDays: displayOptions.allDays,
                xAxisLabel: displayOptions.xAxisLabel,
                yAxisLabel: displayOptions.yAxisLabel,
                xAxisTickFormatter,
                goalLines,
                incompletenessOffsetFromEnd,
                getHidden,
                showConfidenceIntervals: displayOptions.showConfidenceIntervals,
                confidenceLevel: displayOptions.confidenceLevel,
                ciRanges,
                showMovingAverage: displayOptions.showMovingAverage,
                movingAverageIntervals: displayOptions.movingAverageIntervals,
                showTrendLines: displayOptions.showTrendLines,
                valueLabels:
                    displayOptions.showValuesOnSeries && valueLabelFormatter
                        ? { formatter: valueLabelFormatter }
                        : false,
                showCrosshair: displayOptions.showCrosshair,
                tooltip: tooltipConfig,
            }),
        [
            results,
            displayOptions,
            goalLines,
            ciRanges,
            isStickiness,
            incompletenessOffsetFromEnd,
            getHidden,
            xAxisTickFormatter,
            valueLabelFormatter,
            tooltipConfig,
        ]
    )

    return (
        <TimeSeriesLineChart<M>
            series={series}
            labels={labels}
            theme={theme}
            config={config}
            tooltip={tooltip}
            onPointClick={onPointClick}
            className={className}
            dataAttr={dataAttr}
            onError={onError}
        >
            {children}
        </TimeSeriesLineChart>
    )
}
