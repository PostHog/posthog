import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { percentileSorted } from '../lib/runHealth'
import { VERDICT_COLOR, verdictTag } from '../lib/runStatus'
import { type ActivityRun, formatAxisMinutes, isPlottable } from './RunActivityChart'

interface RunActivityMiniBarsProps {
    runs: ActivityRun[]
    title?: string
    /** The runs list was capped server-side, so the strip shows the most recent runs, not the full window. */
    truncated?: boolean
    /** Singular noun for each bar in the header count — 'run' by default, 'commit' on the repo-health view. */
    noun?: string
    className?: string
}

const CHART_HEIGHT = 52
const MIN_BAR_PX = 3
// A hub preview, not the full record — keep the strip short so each bar stays legible. The full scatter
// (start-time axis, in-flight band, zoom) lives on the workflow page for anyone who wants every run.
const MAX_BARS = 48

/**
 * A compact, scannable version of {@link RunActivityChart} for hub previews: one bar per run, height =
 * CI duration, color = verdict, with a dashed median line. Drops the scatter's time axis, in-flight band,
 * and zoom brush. Renders nothing below 2 completed runs, so callers can drop it in unconditionally.
 */
export function RunActivityMiniBars({
    runs,
    title = 'Run activity',
    truncated = false,
    noun = 'run',
    className,
}: RunActivityMiniBarsProps): JSX.Element | null {
    const plottable = runs.filter(isPlottable)
    if (plottable.length < 2) {
        return null
    }

    // Oldest → newest so the strip reads left-to-right as a trend, then keep the most recent MAX_BARS.
    const ordered = [...plottable].sort((a, b) => dayjs(a.startedAt).valueOf() - dayjs(b.startedAt).valueOf())
    const shown = ordered.slice(-MAX_BARS)
    const capped = truncated || shown.length < plottable.length

    // Median over the full set (not just the shown bars), so it agrees with the scatter and the KPI tiles.
    const sortedMin = plottable.map((run) => run.durationSeconds / 60).sort((a, b) => a - b)
    const medianMin = percentileSorted(sortedMin, 0.5) ?? 0

    const maxSeconds = Math.max(...shown.map((run) => run.durationSeconds))
    const barHeight = (seconds: number): number =>
        maxSeconds > 0 ? Math.max(MIN_BAR_PX, Math.round((seconds / maxSeconds) * CHART_HEIGHT)) : MIN_BAR_PX
    const medianTopPx = maxSeconds > 0 ? CHART_HEIGHT * (1 - Math.min((medianMin * 60) / maxSeconds, 1)) : CHART_HEIGHT

    return (
        <div className={cn('flex flex-col gap-2', className)}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="mb-0">{title}</h3>
                <span className="text-xs whitespace-nowrap text-secondary tabular-nums">
                    {capped ? 'recent ' : ''}
                    {shown.length} {noun}s
                </span>
            </div>
            <LemonCard hoverEffect={false} className="p-4">
                <div className="relative flex items-end gap-px" style={{ height: CHART_HEIGHT }}>
                    <div
                        className="absolute inset-x-0 border-t border-dashed border-secondary"
                        style={{ top: medianTopPx }}
                    />
                    {/* Labels the dashed line and, by naming a duration, signals that bar height is CI time —
                        the job the dropped Y axis used to do. Anchored left: no Y axis here, so the eye meets
                        it first (left-to-right) and reads the line's meaning before scanning the bars. */}
                    <span
                        className="absolute left-0 z-10 -translate-y-1/2 rounded bg-surface-primary px-1 text-[9px] text-secondary"
                        style={{ top: Math.max(6, medianTopPx) }}
                    >
                        median {formatAxisMinutes(medianMin)}
                    </span>
                    {shown.map((run, i) => {
                        const tag = verdictTag(run.conclusion)
                        const color = VERDICT_COLOR[tag.type] ?? VERDICT_COLOR.muted
                        return (
                            <Tooltip
                                key={`${run.runId ?? 'run'}-${i}`}
                                delayMs={60}
                                placement="top"
                                title={
                                    <div className="flex flex-col gap-0.5 text-xs">
                                        <span className="font-semibold" style={{ color }}>
                                            {tag.label}
                                        </span>
                                        <span>Duration {humanFriendlyDuration(run.durationSeconds)}</span>
                                        <span>Started {dayjs(run.startedAt).format('MMM D, HH:mm')}</span>
                                        {run.headBranch && <span className="font-mono">{run.headBranch}</span>}
                                        {run.prNumber != null && run.prNumber > 0 && <span>PR #{run.prNumber}</span>}
                                    </div>
                                }
                            >
                                <div
                                    className="min-w-[3px] flex-1 rounded-t-sm opacity-75 transition-opacity hover:opacity-100"
                                    style={{ height: barHeight(run.durationSeconds), background: color }}
                                />
                            </Tooltip>
                        )
                    })}
                </div>
            </LemonCard>
        </div>
    )
}
