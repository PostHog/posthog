import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { WorkflowRunActivityPointApi } from '../generated/api.schemas'
import { TimeRange, clampFocus, defaultFocus, panFocus, pxToTime, resizeFocus, timeToFrac } from '../lib/brush'
import { isDecisiveFailure } from '../lib/lifecycle'
import { percentileSorted } from '../lib/runHealth'
import { VERDICT_COLOR, verdictTag } from '../lib/runStatus'

// Both WorkflowRunRow and PrRunRow satisfy this shape, so either page can pass its own run list.
export interface ActivityRun {
    ciEngine?: WorkflowRunActivityPointApi['ci_engine']
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
    noun?: string
    className?: string
}

const DOT_COLOR = VERDICT_COLOR

export const LEGEND_LABEL: Record<string, string> = {
    success: 'Passed',
    danger: 'Failed',
    muted: 'Cancelled / skipped',
    warning: 'Other',
}
export const LEGEND_ORDER = ['success', 'danger', 'muted', 'warning']

const SCATTER_HEIGHT = 156
const BAND_HEIGHT = 56
const STRIP_HEIGHT = 26
const Y_TICK_COUNT = 4
const X_TICK_COUNT = 5
// One point shows no spread, so the chart draws from two.
const MIN_POINTS = 2

export const isPlottable = (run: ActivityRun): run is ActivityRun & { startedAt: string; durationSeconds: number } =>
    run.startedAt != null && run.durationSeconds != null && run.durationSeconds >= 0

/** False when RunActivityChart would render null, so callers can show their empty state instead. */
export function hasEnoughRunActivity(runs: ActivityRun[]): boolean {
    return runs.filter(isPlottable).length >= MIN_POINTS
}
// Below this total span the chart is already readable without a zoom brush.
const BRUSH_THRESHOLD_MS = 24 * 60 * 60 * 1000
// The lens never narrows below this, so it stays grabbable and the zoomed axis keeps a readable span.
const MIN_LENS_MS = 15 * 60 * 1000
// A run with no final duration counts as in flight up to now, capped here. One that started longer ago
// and never settled almost certainly lost its completion webhook, and uncapped it would stretch the
// in-flight band and time axis by days.
const MAX_IN_FLIGHT_MS = 60 * 60 * 1000

/** Rounds up to 1, 2, or 5 times a power of ten, so axis ticks land on readable values. */
function niceStep(rough: number): number {
    if (rough <= 0) {
        return 1
    }
    const pow = Math.pow(10, Math.floor(Math.log10(rough)))
    const n = rough / pow
    const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10
    return step * pow
}

export function formatAxisMinutes(min: number): string {
    const rounded = Math.round(min)
    if (rounded < 60) {
        return `${rounded}m`
    }
    const h = Math.floor(rounded / 60)
    const m = rounded % 60
    return m ? `${h}h ${m}m` : `${h}h`
}

interface Interval {
    start: number
    end: number
    conclusion: string | null
    completed: boolean
}

interface Point {
    key: string
    leftPct: number
    topPx: number
    color: string
    tooltip: JSX.Element
}

function RunActivityBrush({
    fullMin,
    fullMax,
    view,
    onChange,
    onReset,
    isDefault,
}: {
    fullMin: number
    fullMax: number
    view: TimeRange
    onChange: (range: TimeRange) => void
    onReset: () => void
    isDefault: boolean
}): JSX.Element {
    const stripRef = useRef<HTMLDivElement>(null)
    // The extent is frozen at pointer-down: on a live workflow fullMax tracks `now` and would otherwise
    // drift every render mid-drag, churning the listeners and applying the pan against a moving span.
    const dragRef = useRef<{ x: number; view: TimeRange; fullMin: number; fullMax: number } | null>(null)
    const [dragMode, setDragMode] = useState<null | 'pan' | 'start' | 'end'>(null)

    // The listeners sit on the window, so a fast drag that outruns the lens keeps panning. They attach
    // once per drag, because the moving bounds are frozen in dragRef.
    useEffect(() => {
        if (!dragMode) {
            return
        }
        const onMove = (e: PointerEvent): void => {
            const strip = stripRef.current
            const start = dragRef.current
            if (!strip || !start) {
                return
            }
            const width = strip.clientWidth
            if (dragMode === 'pan') {
                const deltaMs = ((e.clientX - start.x) / Math.max(1, width)) * (start.fullMax - start.fullMin)
                onChange(panFocus(start.view, deltaMs, start.fullMin, start.fullMax))
            } else {
                const t = pxToTime(e.clientX - strip.getBoundingClientRect().left, width, start.fullMin, start.fullMax)
                onChange(resizeFocus(start.view, dragMode, t, start.fullMin, start.fullMax, MIN_LENS_MS))
            }
        }
        const onUp = (): void => setDragMode(null)
        window.addEventListener('pointermove', onMove)
        window.addEventListener('pointerup', onUp)
        return () => {
            window.removeEventListener('pointermove', onMove)
            window.removeEventListener('pointerup', onUp)
        }
    }, [dragMode, onChange])

    const begin =
        (mode: 'pan' | 'start' | 'end') =>
        (e: ReactPointerEvent): void => {
            e.preventDefault()
            e.stopPropagation()
            dragRef.current = { x: e.clientX, view, fullMin, fullMax }
            setDragMode(mode)
        }

    const leftPct = timeToFrac(view.start, fullMin, fullMax) * 100
    const widthPct = Math.max(
        2,
        (timeToFrac(view.end, fullMin, fullMax) - timeToFrac(view.start, fullMin, fullMax)) * 100
    )

    return (
        <div className="mt-1 flex items-center gap-2">
            <div
                ref={stripRef}
                className="relative flex-1 overflow-hidden rounded border border-border"
                style={{ height: STRIP_HEIGHT }}
            >
                <div
                    className="absolute inset-y-0 cursor-grab touch-none border active:cursor-grabbing"
                    style={{
                        left: `${leftPct}%`,
                        width: `${widthPct}%`,
                        borderColor: 'var(--brand-blue)',
                        background: 'color-mix(in srgb, var(--brand-blue) 18%, transparent)',
                    }}
                    onPointerDown={begin('pan')}
                    role="slider"
                    aria-label="Zoom window"
                    aria-valuemin={fullMin}
                    aria-valuemax={fullMax}
                    aria-valuenow={view.start}
                >
                    <div
                        className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize touch-none"
                        style={{ background: 'var(--brand-blue)' }}
                        onPointerDown={begin('start')}
                    />
                    <div
                        className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize touch-none"
                        style={{ background: 'var(--brand-blue)' }}
                        onPointerDown={begin('end')}
                    />
                </div>
            </div>
            {!isDefault && (
                <button
                    type="button"
                    className="text-xs whitespace-nowrap text-secondary hover:underline"
                    onClick={onReset}
                >
                    Reset
                </button>
            )}
        </div>
    )
}

export function RunActivityChart({
    runs,
    title = 'Run activity',
    truncated = false,
    noun = 'run',
    className,
}: RunActivityChartProps): JSX.Element | null {
    // Null means the full loaded window. Declared before the early return so the hook order is stable.
    const [focus, setFocus] = useState<TimeRange | null>(null)
    // Drop a manual pan when the runs change (e.g. the shared window changed and reloaded) so the lens
    // returns to the full window instead of clamping a stale range onto an unrelated slice of new data.
    useEffect(() => {
        setFocus(null)
    }, [runs])
    const now = dayjs().valueOf()
    // A still-running run extends to now, capped at MAX_IN_FLIGHT_MS. No-op gate runs never reach this
    // component, because the workflow activity endpoint hides them server-side.
    const intervals: Interval[] = runs
        .filter((run): run is ActivityRun & { startedAt: string } => run.startedAt != null)
        .map((run) => {
            const start = dayjs(run.startedAt).valueOf()
            const completed = run.durationSeconds != null && run.durationSeconds >= 0
            return {
                start,
                end: completed
                    ? start + (run.durationSeconds as number) * 1000
                    : Math.min(now, start + MAX_IN_FLIGHT_MS),
                conclusion: run.conclusion,
                completed,
            }
        })

    // A still-running run has no final duration to place on the Y axis.
    const plottable = runs.filter(isPlottable)
    if (plottable.length < MIN_POINTS) {
        return null
    }

    // tMin and tMax below are the lens bounds. The duration scale and the median stay over the full set,
    // so panning never moves the vertical axis.
    const fullMin = Math.min(...intervals.map((iv) => iv.start))
    const fullMax = Math.max(...intervals.map((iv) => iv.end))
    const brushable = fullMax - fullMin > BRUSH_THRESHOLD_MS
    const view = clampFocus(focus ?? defaultFocus(fullMin, fullMax), fullMin, fullMax, MIN_LENS_MS)
    const tMin = view.start
    const tMax = view.end
    const tSpan = Math.max(1, tMax - tMin)
    const xPct = (ms: number): number => ((ms - tMin) / tSpan) * 100

    const durationsMin = plottable.map((run) => run.durationSeconds / 60)
    const maxMin = Math.max(...durationsMin)
    // The axis top is the smallest multiple of the step that clears the slowest run.
    const step = niceStep(maxMin / Y_TICK_COUNT)
    const niceMaxMin = Math.max(step, Math.ceil(maxMin / step) * step)
    const yPx = (min: number): number => SCATTER_HEIGHT * (1 - min / niceMaxMin)

    // percentileSorted also computes the health summary's medianSeconds, so the chart and the summary agree.
    const sortedMin = [...durationsMin].sort((a, b) => a - b)
    const medianMin = percentileSorted(sortedMin, 0.5) ?? 0

    const visible = plottable.filter((run) => {
        const t = dayjs(run.startedAt).valueOf()
        return t >= tMin && t <= tMax
    })

    const presentTypeSet = new Set<string>()
    const points: Point[] = visible.map((run, i) => {
        const tag = verdictTag(run.conclusion)
        presentTypeSet.add(tag.type)
        return {
            key: `${run.ciEngine ?? ''}:${run.runId ?? 'run'}-${i}`,
            leftPct: xPct(dayjs(run.startedAt).valueOf()),
            topPx: Math.max(3, Math.min(SCATTER_HEIGHT - 3, yPx(run.durationSeconds / 60))),
            color: DOT_COLOR[tag.type] ?? DOT_COLOR.muted,
            tooltip: (
                <div className="flex flex-col gap-0.5 text-xs">
                    <span className="font-semibold" style={{ color: DOT_COLOR[tag.type] ?? DOT_COLOR.muted }}>
                        {tag.label}
                    </span>
                    <span>Duration {humanFriendlyDuration(run.durationSeconds)}</span>
                    <span>Started {dayjs(run.startedAt).format('MMM D, HH:mm')}</span>
                    {run.headBranch && <span className="font-mono">{run.headBranch}</span>}
                    {run.prNumber != null && run.prNumber > 0 && <span>PR #{run.prNumber}</span>}
                </div>
            ),
        }
    })

    const yTicks = Array.from({ length: Math.round(niceMaxMin / step) + 1 }, (_, i) => {
        const min = step * i
        return { min, topPx: yPx(min), label: formatAxisMinutes(min) }
    })

    // Span under ~36h reads as time-of-day; a wider window reads as calendar days.
    const xFormat = tSpan / 3_600_000 <= 36 ? 'HH:mm' : 'MMM D'
    const xTicks = Array.from({ length: X_TICK_COUNT }, (_, i) => ({
        leftPct: (i / (X_TICK_COUNT - 1)) * 100,
        label: dayjs(tMin + (tSpan * i) / (X_TICK_COUNT - 1)).format(xFormat),
    }))

    const focusIntervals = intervals
        .map((iv) => ({ ...iv, start: Math.max(iv.start, tMin), end: Math.min(iv.end, tMax) }))
        .filter((iv) => iv.end > iv.start)

    // A sweep line over each run's start and end gives exact concurrency. Sampling fixed instants would
    // miss a run that begins and ends between two samples.
    const bandEvents = focusIntervals.flatMap((iv) => {
        const failDelta = isDecisiveFailure(iv.conclusion) ? 1 : 0
        return [
            { t: iv.start, dTotal: 1, dFailing: failDelta },
            { t: iv.end, dTotal: -1, dFailing: -failDelta },
        ]
    })
    bandEvents.sort((a, b) => a.t - b.t)
    const steps: { t: number; total: number; failing: number }[] = []
    let runningTotal = 0
    let runningFailing = 0
    bandEvents.forEach((event, i) => {
        runningTotal += event.dTotal
        runningFailing += event.dFailing
        if (i + 1 === bandEvents.length || bandEvents[i + 1].t !== event.t) {
            steps.push({ t: event.t, total: runningTotal, failing: runningFailing })
        }
    })
    // The peak is 0 when the lens covers a gap with no runs. The band height divides by it, so the
    // denominator is clamped to 1.
    const peak = steps.length ? Math.max(...steps.map((s) => s.total)) : 0
    const bandScale = Math.max(1, peak)
    const bandX = (t: number): string => (((t - tMin) / tSpan) * 1000).toFixed(1)
    const bandY = (v: number): string => (BAND_HEIGHT - (v / bandScale) * (BAND_HEIGHT - 2)).toFixed(1)
    // Concurrency is piecewise-constant, so the areas are drawn as steps.
    const stepArea = (key: 'total' | 'failing'): string => {
        let d = `M0,${bandY(0)}`
        let level = 0
        for (const s of steps) {
            const x = bandX(s.t)
            d += ` L${x},${bandY(level)} L${x},${bandY(s[key])}`
            level = s[key]
        }
        return `${d} L1000,${bandY(level)} L1000,${BAND_HEIGHT} L0,${BAND_HEIGHT} Z`
    }
    const areaTotal = stepArea('total')
    const areaFailing = stepArea('failing')
    let line = `M0,${bandY(0)}`
    let lineLevel = 0
    for (const s of steps) {
        const x = bandX(s.t)
        line += ` L${x},${bandY(lineLevel)} L${x},${bandY(s.total)}`
        lineLevel = s.total
    }
    line += ` L1000,${bandY(lineLevel)}`

    const presentTypes = LEGEND_ORDER.filter((type) => presentTypeSet.has(type))

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
                        {brushable ? `${visible.length} of ${plottable.length}` : plottable.length} {noun}s · median{' '}
                        {formatAxisMinutes(medianMin)} · peak {peak} in flight
                    </span>
                </Tooltip>
            </div>
            <LemonCard hoverEffect={false} className="p-4">
                <div className="flex gap-2">
                    {/* Y axis: duration tick labels in their own gutter, aligned to the scatter gridlines. */}
                    <div className="relative w-12 shrink-0" style={{ height: SCATTER_HEIGHT }}>
                        {yTicks.map((tick) => (
                            <span
                                key={tick.min}
                                className="absolute right-1 -translate-y-1/2 font-mono text-[9px] text-tertiary"
                                style={{ top: tick.topPx }}
                            >
                                {tick.label}
                            </span>
                        ))}
                    </div>
                    <div className="min-w-0 flex-1">
                        <div className="relative" style={{ height: SCATTER_HEIGHT }}>
                            {yTicks.map((tick) => (
                                <div
                                    key={tick.min}
                                    className="absolute inset-x-0 h-px bg-border"
                                    style={{ top: tick.topPx }}
                                />
                            ))}
                            <div
                                className="absolute inset-x-0 border-t border-dashed border-secondary"
                                style={{ top: yPx(medianMin) }}
                            />
                            <span
                                className="absolute right-0 -translate-y-1/2 rounded bg-surface-primary px-1 text-[9px] text-secondary"
                                style={{ top: yPx(medianMin) }}
                            >
                                median {formatAxisMinutes(medianMin)}
                            </span>
                            {points.map((p) => (
                                <Tooltip key={p.key} title={p.tooltip} delayMs={60} placement="top">
                                    <div
                                        className="absolute h-[7px] w-[7px] -translate-x-1/2 -translate-y-1/2 cursor-default rounded-full transition-transform hover:scale-150"
                                        style={{
                                            left: `${p.leftPct}%`,
                                            top: p.topPx,
                                            background: p.color,
                                            opacity: 0.6,
                                        }}
                                    />
                                </Tooltip>
                            ))}
                        </div>
                        {/* In-flight concurrency band, sharing the scatter's time axis. */}
                        <div className="relative mt-2" style={{ height: BAND_HEIGHT }}>
                            <span
                                className="absolute left-1 top-0 z-10 text-[10px] font-medium"
                                style={{ color: 'var(--brand-blue)' }}
                            >
                                In flight · peak {peak}
                            </span>
                            <svg
                                viewBox={`0 0 1000 ${BAND_HEIGHT}`}
                                preserveAspectRatio="none"
                                width="100%"
                                height={BAND_HEIGHT}
                                className="block"
                                role="img"
                                aria-label="Runs in flight over time"
                            >
                                <path d={areaTotal} fill="var(--brand-blue)" fillOpacity={0.14} />
                                <path d={areaFailing} fill="var(--danger)" fillOpacity={0.3} />
                                <path d={line} fill="none" stroke="var(--brand-blue)" strokeWidth={1.5} />
                            </svg>
                        </div>
                        {/* The first and last ticks anchor to the edges so their labels don't clip. */}
                        <div className="relative mt-1 h-4">
                            {xTicks.map((tick, i) => {
                                const isEdge = i === 0 || i === xTicks.length - 1
                                return (
                                    <span
                                        key={i}
                                        className={cn(
                                            'absolute top-0 text-[9.5px] text-tertiary tabular-nums',
                                            i === 0 && 'left-0',
                                            i === xTicks.length - 1 && 'right-0',
                                            !isEdge && '-translate-x-1/2'
                                        )}
                                        style={isEdge ? undefined : { left: `${tick.leftPct}%` }}
                                    >
                                        {tick.label}
                                    </span>
                                )
                            })}
                        </div>
                        {/* Focus lens over the full window. */}
                        {brushable && (
                            <RunActivityBrush
                                fullMin={fullMin}
                                fullMax={fullMax}
                                view={view}
                                onChange={setFocus}
                                onReset={() => setFocus(null)}
                                isDefault={focus === null}
                            />
                        )}
                    </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1">
                    {presentTypes.map((type) => (
                        <span key={type} className="flex items-center gap-1.5 text-xs text-secondary">
                            <span
                                className="h-1.5 w-1.5 shrink-0 rounded-full"
                                style={{ background: DOT_COLOR[type] }}
                            />
                            {LEGEND_LABEL[type]}
                        </span>
                    ))}
                    <span className="flex items-center gap-1.5 text-xs text-secondary">
                        <span
                            className="h-1.5 w-3 shrink-0 rounded-sm"
                            style={{ background: 'var(--brand-blue)', opacity: 0.5 }}
                        />
                        In flight
                    </span>
                </div>
            </LemonCard>
        </div>
    )
}
