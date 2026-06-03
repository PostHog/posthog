import type { ErrorInfo, ReactElement, ReactNode } from 'react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type {
    ChartTheme,
    GoalLineConfig,
    PointClickData,
    Series,
    TimeSeriesLineChartConfig,
    TooltipContext,
    XAxisConfig,
    YAxisConfig,
} from '@posthog/quill-charts'

import { buildDerivedConfigs, buildTrendsSeries, type TrendsResultLike } from './trendsSeriesTransforms'

// Presentational, dependency-clean trends line chart: takes trends results + display
// options and renders the canvas chart, doing the series + derived-config assembly via the
// shared transforms. Imports only `react` and `@posthog/quill-charts` (+ the dep-clean
// transforms), so both the web app and the MCP UI app build can bundle it. Callers compute
// their own axis / value-label / goal-line config (those are framework-specific) and pass
// them in as Quill-level config objects.
export interface TrendsLineChartViewProps<R extends TrendsResultLike, M = unknown> {
    results: R[]
    labels: string[]
    theme: ChartTheme

    getColor: (r: R, index: number) => string
    getLabel?: (r: R, index: number) => string
    /** A `ChartDisplayType` value; `'ActionsAreaGraph'` fills the area under each line. */
    display?: string

    // Display options → derived series.
    showTrendLines?: boolean
    showMovingAverage?: boolean
    movingAverageIntervals?: number
    showConfidenceIntervals?: boolean
    confidenceLevel?: number

    // Quill-level config the caller computes for itself.
    xAxis?: XAxisConfig
    yAxis?: YAxisConfig
    valueLabels?: TimeSeriesLineChartConfig['valueLabels']
    goalLines?: GoalLineConfig[]
    percentStackView?: boolean
    showCrosshair?: boolean

    // Forwarded straight to the canvas chart.
    tooltip?: (ctx: TooltipContext<M>) => ReactNode
    onPointClick?: (data: PointClickData<M>) => void
    children?: ReactNode
    className?: string
    dataAttr?: string
    onError?: (error: Error, info: ErrorInfo) => void
}

export function TrendsLineChartView<R extends TrendsResultLike, M = unknown>({
    results,
    labels,
    theme,
    getColor,
    getLabel,
    display,
    showTrendLines,
    showMovingAverage,
    movingAverageIntervals,
    showConfidenceIntervals,
    confidenceLevel,
    xAxis,
    yAxis,
    valueLabels,
    goalLines,
    percentStackView,
    showCrosshair,
    tooltip,
    onPointClick,
    children,
    className,
    dataAttr,
    onError,
}: TrendsLineChartViewProps<R, M>): ReactElement {
    const series: Series<M>[] = buildTrendsSeries<R, M>(results, {
        getColor,
        ...(getLabel ? { getLabel } : {}),
        ...(display !== undefined ? { display } : {}),
    })

    const derived = buildDerivedConfigs(results, {
        ...(showTrendLines !== undefined ? { showTrendLines } : {}),
        ...(showMovingAverage !== undefined ? { showMovingAverage } : {}),
        ...(movingAverageIntervals !== undefined ? { movingAverageIntervals } : {}),
        ...(showConfidenceIntervals !== undefined ? { showConfidenceIntervals } : {}),
        ...(confidenceLevel !== undefined ? { confidenceLevel } : {}),
    })

    const config: TimeSeriesLineChartConfig = {
        ...derived,
        ...(xAxis !== undefined ? { xAxis } : {}),
        ...(yAxis !== undefined ? { yAxis } : {}),
        ...(valueLabels !== undefined ? { valueLabels } : {}),
        ...(goalLines !== undefined ? { goalLines } : {}),
        ...(percentStackView ? { percentStackView: true } : {}),
        ...(showCrosshair ? { showCrosshair: true } : {}),
    }

    return (
        <TimeSeriesLineChart
            series={series}
            labels={labels}
            theme={theme}
            config={config}
            {...(tooltip ? { tooltip } : {})}
            {...(onPointClick ? { onPointClick } : {})}
            {...(className !== undefined ? { className } : {})}
            {...(dataAttr !== undefined ? { dataAttr } : {})}
            {...(onError ? { onError } : {})}
        >
            {children}
        </TimeSeriesLineChart>
    )
}
