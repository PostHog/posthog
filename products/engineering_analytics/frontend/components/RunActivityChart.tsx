import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'
import {
    BoxPlot,
    type BoxPlotDatum,
    type BoxPlotSeries,
    type BoxPlotTooltipContext,
    TimeSeriesLineChart,
    TooltipSurface,
    TooltipSwatch,
    useChartTheme,
} from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { teamLogic } from 'scenes/teamLogic'

import { isDecisiveFailure } from '../lib/lifecycle'
import { percentileSorted } from '../lib/runHealth'
import { VERDICT_COLOR } from '../lib/runStatus'

export interface ActivityRun {
    runId: number | null
    conclusion: string | null
    startedAt: string | null
    durationSeconds: number | null
    headBranch?: string | null
    prNumber?: number | null
    headSha?: string | null
}

interface RunActivityChartProps {
    runs: ActivityRun[]
    title?: string
    /** The runs list was capped server-side, so the chart shows the most recent runs, not the full window. */
    truncated?: boolean
    /** Singular noun for each plotted point in the header count — 'run' by default, 'commit' on the repo-health
     *  view where every dot is a whole commit's collapsed workflows. */
    noun?: string
    className?: string
}

interface RunInterval {
    start: number
    end: number
}

interface ConcurrencyPoint {
    timestamp: string
    total: number
}

const MIN_POINTS = 2
const MAX_IN_FLIGHT_MS = 60 * 60 * 1000
type BoxPlotSummaryKey = Exclude<keyof BoxPlotDatum, 'day'>
const BOX_PLOT_ROWS: { label: string; key: BoxPlotSummaryKey }[] = [
    { label: 'Max', key: 'max' },
    { label: '75th percentile', key: 'p75' },
    { label: 'Median', key: 'median' },
    { label: 'Mean', key: 'mean' },
    { label: '25th percentile', key: 'p25' },
    { label: 'Min', key: 'min' },
]

export const isPlottable = (run: ActivityRun): run is ActivityRun & { startedAt: string; durationSeconds: number } =>
    run.startedAt != null && run.durationSeconds != null && run.durationSeconds >= 0

/** False when RunActivityChart would render null, so callers can show their empty state instead. */
export function hasEnoughRunActivity(runs: ActivityRun[]): boolean {
    return runs.filter(isPlottable).length >= MIN_POINTS
}

/** Compact minutes label for the duration axis: "45m", "1h", "1h 30m". */
export function formatAxisMinutes(min: number): string {
    const rounded = Math.round(min)
    if (rounded < 60) {
        return `${rounded}m`
    }
    const hours = Math.floor(rounded / 60)
    const minutes = rounded % 60
    return minutes ? `${hours}h ${minutes}m` : `${hours}h`
}

function summarizeDurations(durationsSeconds: number[]): BoxPlotDatum | null {
    if (durationsSeconds.length === 0) {
        return null
    }

    const sortedMinutes = durationsSeconds.map((duration) => duration / 60).sort((a, b) => a - b)
    const mean = sortedMinutes.reduce((sum, duration) => sum + duration, 0) / sortedMinutes.length

    return {
        min: sortedMinutes[0],
        p25: percentileSorted(sortedMinutes, 0.25) ?? sortedMinutes[0],
        median: percentileSorted(sortedMinutes, 0.5) ?? sortedMinutes[0],
        mean,
        p75: percentileSorted(sortedMinutes, 0.75) ?? sortedMinutes.at(-1)!,
        max: sortedMinutes.at(-1)!,
    }
}

function buildDurationSeries(runs: (ActivityRun & { durationSeconds: number })[]): BoxPlotSeries[] {
    const passing = summarizeDurations(
        runs.filter((run) => run.conclusion === 'success').map((run) => run.durationSeconds)
    )
    const failing = summarizeDurations(
        runs.filter((run) => isDecisiveFailure(run.conclusion)).map((run) => run.durationSeconds)
    )

    return [
        { key: 'passing', label: 'Passing', color: VERDICT_COLOR.success, data: [passing, null] },
        { key: 'failing', label: 'Failing', color: VERDICT_COLOR.danger, data: [null, failing] },
    ].filter((series) => series.data.some((datum) => datum !== null))
}

function buildConcurrencyTrend(intervals: RunInterval[]): ConcurrencyPoint[] {
    if (intervals.length === 0) {
        return []
    }

    const events = intervals
        .flatMap((interval) => [
            { timestamp: interval.start, delta: 1 },
            { timestamp: interval.end, delta: -1 },
        ])
        .sort((a, b) => a.timestamp - b.timestamp)

    const points: ConcurrencyPoint[] = []
    let total = 0
    for (let index = 0; index < events.length; index++) {
        total += events[index].delta
        if (index + 1 === events.length || events[index + 1].timestamp !== events[index].timestamp) {
            points.push({ timestamp: new Date(events[index].timestamp).toISOString(), total })
        }
    }
    return points
}

function DurationTooltip({ context }: { context: BoxPlotTooltipContext }): JSX.Element | null {
    const entries = context.seriesData.flatMap((entry) => {
        const datum = entry.series.meta?.datums?.[context.dataIndex]
        return datum ? [{ datum, color: entry.color, label: entry.series.label, key: entry.series.key }] : []
    })
    if (entries.length === 0) {
        return null
    }

    return (
        <TooltipSurface>
            <div className="mb-1 font-semibold">Run duration</div>
            {entries.map((entry, index) => (
                <div key={entry.key} className={index > 0 ? 'mt-2' : undefined}>
                    <div className="mb-1 flex items-center gap-2">
                        <TooltipSwatch color={entry.color} />
                        <span className="font-semibold">{entry.label}</span>
                    </div>
                    <table className="border-collapse">
                        <tbody>
                            {BOX_PLOT_ROWS.map((row) => (
                                <tr key={row.key}>
                                    <td className="pr-3 opacity-70">{row.label}</td>
                                    <td className="font-medium">{humanFriendlyDuration(entry.datum[row.key] * 60)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            ))}
        </TooltipSurface>
    )
}

export function RunActivityChart({
    runs,
    title = 'Run activity',
    truncated = false,
    noun = 'run',
    className,
}: RunActivityChartProps): JSX.Element | null {
    const { timezone } = useValues(teamLogic)
    const chartTheme = useChartTheme()
    const now = dayjs().valueOf()
    const plottable = runs.filter(isPlottable)
    if (plottable.length < MIN_POINTS) {
        return null
    }

    const intervals = runs
        .filter((run): run is ActivityRun & { startedAt: string } => run.startedAt != null)
        .map((run): RunInterval => {
            const start = dayjs(run.startedAt).valueOf()
            return {
                start,
                end:
                    run.durationSeconds != null && run.durationSeconds >= 0
                        ? start + run.durationSeconds * 1000
                        : Math.min(now, start + MAX_IN_FLIGHT_MS),
            }
        })
    const durationSeries = buildDurationSeries(plottable)
    const concurrencyTrend = buildConcurrencyTrend(intervals)
    const peakConcurrency = concurrencyTrend.length ? Math.max(...concurrencyTrend.map((point) => point.total)) : 0
    const trendSpan = intervals.length
        ? Math.max(...intervals.map((interval) => interval.end)) -
          Math.min(...intervals.map((interval) => interval.start))
        : 0

    return (
        <div className={cn('flex flex-col gap-2', className)}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="mb-0">{title}</h3>
                <Tooltip
                    title={
                        truncated
                            ? `Covers the most recent ${plottable.length} ${noun}s, not the full window.`
                            : undefined
                    }
                >
                    <span className="text-xs whitespace-nowrap text-secondary tabular-nums">
                        {truncated ? 'recent ' : ''}
                        {plottable.length} {noun}s · peak {peakConcurrency} in flight
                    </span>
                </Tooltip>
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
                <LemonCard hoverEffect={false} className="flex min-h-72 flex-col p-4">
                    <div className="mb-2">
                        <h4 className="mb-0">Run duration</h4>
                        <p className="mb-0 text-xs text-secondary">Passing and failing run distributions</p>
                    </div>
                    <div className="min-h-0 flex-1">
                        <BoxPlot
                            series={durationSeries}
                            labels={['Passing', 'Failing']}
                            theme={chartTheme}
                            config={{
                                showGrid: true,
                                yTickFormatter: formatAxisMinutes,
                                tooltip: { placement: 'cursor' },
                            }}
                            tooltip={(context) => <DurationTooltip context={context} />}
                            dataAttr="run-duration-box-plot"
                        />
                    </div>
                </LemonCard>
                <LemonCard hoverEffect={false} className="flex min-h-72 flex-col p-4">
                    <div className="mb-2">
                        <h4 className="mb-0">Runs in flight</h4>
                        <p className="mb-0 text-xs text-secondary">Concurrent workflow runs over time</p>
                    </div>
                    <div className="min-h-0 flex-1">
                        <TimeSeriesLineChart
                            series={[
                                {
                                    key: 'runs_in_flight',
                                    label: 'Runs in flight',
                                    data: concurrencyTrend.map((point) => point.total),
                                    color: 'var(--brand-blue)',
                                    points: { radius: 2 },
                                },
                            ]}
                            labels={concurrencyTrend.map((point) => point.timestamp)}
                            theme={chartTheme}
                            config={{
                                xAxis: { timezone, interval: trendSpan <= 2 * 24 * 60 * 60 * 1000 ? 'hour' : 'day' },
                                yAxis: {
                                    startAtZero: true,
                                    showGrid: true,
                                    tickFormatter: (value) => Math.round(value).toString(),
                                },
                                showCrosshair: true,
                                tooltip: {
                                    placement: 'top',
                                    valueFormatter: (value) =>
                                        `${Math.round(value)} ${noun}${Math.round(value) === 1 ? '' : 's'}`,
                                },
                            }}
                            dataAttr="runs-in-flight-trend"
                        />
                    </div>
                </LemonCard>
            </div>
        </div>
    )
}
