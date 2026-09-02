import posthog from 'posthog-js'
import { type ErrorInfo, type ReactNode, useCallback, useMemo } from 'react'

import { IconArrowRight, IconInfo } from '@posthog/icons'
import {
    DefaultTooltip,
    useChartTheme,
    type ChangeColor,
    type MetricChange,
    type Series,
    type TooltipContext,
} from '@posthog/quill-charts'
import {
    Metric,
    MetricDelta,
    MetricHeader,
    MetricSparkline,
    MetricTitle,
    MetricValue,
} from '@posthog/quill-components/metric'
import { cn, Skeleton, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@posthog/quill-primitives'

import { getColorVar } from 'lib/colors'
import { AppMetricsTimeSeriesResponse } from 'lib/components/AppMetrics/appMetricsLogic'
import { dayjs } from 'lib/dayjs'
import { formatPercentageDiff, humanFriendlyNumber } from 'lib/utils/numbers'

const SPARKLINE_HEIGHT = 160

// `Metric` is content, not a surface, so the tile keeps the surrounding scene's chrome rather than
// quill's Card — the step tables and trends chart below it are still Lemon surfaces.
const CARD_CHROME = 'flex min-w-[16rem] flex-1 flex-col rounded border bg-surface-primary py-3'

// The period-over-period pill stays neutral (grey), matching how these tiles reported change before —
// several workflow metrics (Failed, Bounced, Rate Limited) are "bad when rising", so green/red good/bad
// coloring would mislead. The chevron still shows direction.
function neutralChange(): ChangeColor {
    return { background: 'transparent', foreground: getColorVar('muted') }
}

// `Metric` contains a render throw to this tile instead of letting it take the scene down, which also
// keeps it out of error tracking — report it so a silently broken tile is still visible.
function captureRenderError(error: Error, info: ErrorInfo): void {
    posthog.captureException(error, {
        feature: 'workflow-metric-card',
        componentStack: info.componentStack ?? undefined,
    })
}

function DrillArrow({ tooltip }: { tooltip?: string }): JSX.Element {
    const arrow = <IconArrowRight className="ml-1 inline-block align-text-bottom text-xl text-muted" aria-hidden />
    if (!tooltip) {
        return arrow
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex" />}>{arrow}</TooltipTrigger>
            <TooltipContent>{tooltip}</TooltipContent>
        </Tooltip>
    )
}

export interface WorkflowMetricCardProps {
    name: string
    /** Shown as an info tooltip on the title. */
    description?: ReactNode
    timeSeries: AppMetricsTimeSeriesResponse | null
    previousPeriodTimeSeries?: AppMetricsTimeSeriesResponse | null
    color?: string
    /** Per-series sparkline colors keyed by series name. When the response has more than one series,
     *  the tile draws one line per series (colored from here) instead of a single summed line. */
    seriesColors?: Record<string, string>
    /** Sparkline color used when the tile total is zero (e.g. a muted grey). */
    colorIfZero?: string
    loading?: boolean
    onClick?: () => void
    onClickTooltip?: string
    footer?: ReactNode
}

// Collapse a response into the numbers the tile reads (per-index sums plus the grand total). A
// single-metric tile has one series; the combined "messages" tile sums its email + push channels.
function sumSeries(ts: AppMetricsTimeSeriesResponse | null | undefined): { data: number[]; total: number } {
    if (!ts || ts.series.length === 0) {
        return { data: [], total: 0 }
    }
    const data = ts.labels.map((_, i) => ts.series.reduce((acc, series) => acc + (series.values[i] ?? 0), 0))
    return { data, total: data.reduce((acc, v) => acc + v, 0) }
}

/**
 * A summary tile built by composing quill's `Metric`, adapting our app-metrics series shape. The click
 * target, footer, title info icon and loading state are composition-level concerns, so they live here
 * rather than as `Metric` props.
 */
export function WorkflowMetricCard({
    name,
    description,
    timeSeries,
    previousPeriodTimeSeries,
    color,
    seriesColors,
    colorIfZero,
    loading,
    onClick,
    onClickTooltip,
    footer,
}: WorkflowMetricCardProps): JSX.Element {
    const theme = useChartTheme()

    const { data, total } = useMemo(() => sumSeries(timeSeries), [timeSeries])
    const totalPreviousPeriod = useMemo(() => sumSeries(previousPeriodTimeSeries).total, [previousPeriodTimeSeries])

    // A response with more than one series (e.g. the combined email + push "messages" tile) draws one
    // line per channel, colored from seriesColors; a single-series tile keeps the one summed line.
    const sparklineSeries = useMemo<Series[] | undefined>(() => {
        if (!timeSeries || timeSeries.series.length <= 1) {
            return undefined
        }
        return timeSeries.series.map((s) => ({
            key: s.name,
            label: s.name,
            data: s.values,
            // The zero-state color has to be set per series — the sparkline ignores the tile-level
            // `color` whenever `series` is set, so an empty combined tile would keep its channel colors.
            color: total === 0 ? colorIfZero : seriesColors?.[s.name],
        }))
    }, [timeSeries, seriesColors, colorIfZero, total])

    // Only surface a comparison when there's a non-zero baseline — formatPercentageDiff returns null on
    // a zero/absent previous period, so the pill is hidden rather than showing a bogus ∞%.
    const change = useMemo<MetricChange | null>(() => {
        const label = formatPercentageDiff(total, totalPreviousPeriod)
        return label == null ? null : { value: total - totalPreviousPeriod, label }
    }, [total, totalPreviousPeriod])

    const neutral = neutralChange()

    // Labels arrive pre-formatted in the team timezone ('YYYY-MM-DD', or '… HH:mm' for sub-day
    // intervals), so parse them as naive local strings for the tooltip header.
    const renderTooltip = useCallback(
        (ctx: TooltipContext) => (
            <DefaultTooltip
                {...ctx}
                sortedByValue
                showTotal
                labelFormatter={(label: string) =>
                    dayjs(label).format(label.includes(' ') ? 'MMM D, HH:mm' : 'MMM D, YYYY')
                }
                valueFormatter={(value: number) => humanFriendlyNumber(value)}
            />
        ),
        []
    )

    const cardClassName = cn(
        CARD_CHROME,
        onClick &&
            'cursor-pointer transition-colors hover:bg-surface-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent'
    )

    if (loading) {
        return (
            <div className={CARD_CHROME}>
                <div className="flex flex-col px-3">
                    <Skeleton className="h-4 w-24" />
                    <Skeleton className="mt-3 h-9 w-32" />
                    <Skeleton className="mt-4 h-40 w-full" />
                </div>
            </div>
        )
    }

    return (
        <TooltipProvider>
            <div
                className={cardClassName}
                onClick={onClick}
                role={onClick ? 'button' : undefined}
                tabIndex={onClick ? 0 : undefined}
                // Only the card itself activates the drill — a link or icon inside it keeps its own keys.
                onKeyDown={(e) => {
                    if (onClick && e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
                        e.preventDefault()
                        onClick()
                    }
                }}
            >
                <Metric
                    className="px-3"
                    onError={captureRenderError}
                    value={total}
                    data={data}
                    series={sparklineSeries}
                    labels={timeSeries?.labels}
                    theme={theme}
                    color={total === 0 ? colorIfZero : color}
                    change={change}
                    positiveColor={neutral}
                    negativeColor={neutral}
                    formatValue={(v) => humanFriendlyNumber(v)}
                    sparklineHeight={SPARKLINE_HEIGHT}
                    sparklineTooltip={renderTooltip}
                >
                    <MetricHeader>
                        <MetricTitle className="min-w-0">
                            {name}
                            {description != null && (
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <span
                                                className="ml-1 inline-flex align-text-bottom text-xl text-muted"
                                                onClick={(e) => e.stopPropagation()}
                                            />
                                        }
                                    >
                                        <IconInfo />
                                    </TooltipTrigger>
                                    <TooltipContent>{description}</TooltipContent>
                                </Tooltip>
                            )}
                            {onClick && <DrillArrow tooltip={onClickTooltip} />}
                        </MetricTitle>
                        <MetricDelta />
                    </MetricHeader>
                    <MetricValue className="mt-2" />
                    <MetricSparkline className="-mx-3 mt-4" />
                </Metric>
                {footer && (
                    // Stop clicks here from firing the tile's drill — the footer carries its own link.
                    <div className="px-3 pt-2 text-center text-xs" onClick={(e) => e.stopPropagation()}>
                        {footer}
                    </div>
                )}
            </div>
        </TooltipProvider>
    )
}
