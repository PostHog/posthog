import { type ReactNode, useMemo } from 'react'

import { MetricCard, type ChangeColor, type MetricChange, type Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { AppMetricsTimeSeriesResponse } from 'lib/components/AppMetrics/appMetricsLogic'
import { formatPercentageDiff, humanFriendlyNumber } from 'lib/utils/numbers'

// A summary tile built on quill's MetricCard, adapting our app-metrics series shape. The chrome
// (border/padding/background) is passed through MetricCard's className so the whole tile — padding
// included — is the clickable target when `onClick` is set, matching the surrounding tiles.
const CARD_CHROME = 'flex-1 border rounded p-3 bg-surface-primary min-w-[16rem]'

// The period-over-period pill stays neutral (grey), matching how these tiles reported change before —
// several workflow metrics (Failed, Bounced, Rate Limited) are "bad when rising", so green/red good/bad
// coloring would mislead. The chevron still shows direction.
function neutralChange(): ChangeColor {
    return { background: 'transparent', foreground: getColorVar('muted') }
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

// Collapse a multi-series response into one sparkline line (per-index sum) plus the grand total. A
// single-metric tile has one series; the combined "messages" tile sums its email + push channels.
function sumSeries(ts: AppMetricsTimeSeriesResponse | null | undefined): { data: number[]; total: number } {
    if (!ts || ts.series.length === 0) {
        return { data: [], total: 0 }
    }
    const data = ts.labels.map((_, i) => ts.series.reduce((acc, series) => acc + (series.values[i] ?? 0), 0))
    return { data, total: data.reduce((acc, v) => acc + v, 0) }
}

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
            color: seriesColors?.[s.name],
        }))
    }, [timeSeries, seriesColors])

    // Only surface a comparison when there's a non-zero baseline — formatPercentageDiff returns null on
    // a zero/absent previous period, so the pill is hidden rather than showing a bogus ∞%.
    const change = useMemo<MetricChange | null>(() => {
        const label = formatPercentageDiff(total, totalPreviousPeriod)
        return label == null ? null : { value: total - totalPreviousPeriod, label }
    }, [total, totalPreviousPeriod])

    const neutral = neutralChange()

    return (
        <MetricCard
            className={CARD_CHROME}
            title={name}
            titleTooltip={description}
            value={total}
            data={data.length > 0 ? data : undefined}
            series={sparklineSeries}
            labels={timeSeries?.labels}
            theme={theme}
            color={total === 0 ? colorIfZero : color}
            change={change}
            positiveColor={neutral}
            negativeColor={neutral}
            formatValue={(v) => humanFriendlyNumber(v)}
            loading={loading}
            onClick={onClick}
            onClickTooltip={onClickTooltip}
            footer={footer}
            sparklineHeight={160}
            sparklineClassName="mt-3 -mx-3 -mb-3"
        />
    )
}
