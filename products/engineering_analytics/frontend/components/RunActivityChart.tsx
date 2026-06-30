import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { TimeRange, clampFocus, defaultFocus, panFocus, pxToTime, resizeFocus, timeToFrac } from '../lib/brush'
import { isDecisiveFailure } from '../lib/lifecycle'
import { percentileSorted } from '../lib/runHealth'
import { verdictTag } from '../lib/runStatus'

// A run reduced to what the chart needs. Both WorkflowRunRow and PrRunRow satisfy this, so either page
// can drop the chart in over its own run list; the optional branch/PR fields enrich the hover card.
export interface ActivityRun {
    runId: number | null
    conclusion: string | null
    startedAt: string | null
    durationSeconds: number | null
    headBranch?: string | null
    prNumber?: number | null
}

interface RunActivityChartProps {
    runs: ActivityRun[]
    title?: string
    /** The runs list was capped server-side, so the chart shows the most recent runs, not the full window. */
    truncated?: boolean
    className?: string
}

// Dot/series color from the verdict mapping the run tables' StatusDot uses, so colors agree across the page.
const DOT_COLOR: Record<string, string> = {
    success: 'var(--success)',
    danger: 'var(--danger)',
    warning: 'var(--warning)',
    muted: 'var(--muted)',
}

const LEGEND_LABEL: Record<string, string> = {
    success: 'Passed',
    danger: 'Failed',
    muted: 'Cancelled / skipped',
    warning: 'Other',
}
const LEGEND_ORDER = ['success', 'danger', 'muted', 'warning']

const SCATTER_HEIGHT = 156
const BAND_HEIGHT = 56
const STRIP_HEIGHT = 26
const Y_TICK_COUNT = 4
const X_TICK_COUNT = 5
// A scatter of one point says nothing; only draw once there's a spread to read.
const MIN_POINTS = 2
// The focus lens defaults to the most recent day — the "live" view — over a window that's wider than that.
// Below this much total span there's nothing to pan over, so the brush is hidden and the chart shows it all.
const LENS_MS = 24 * 60 * 60 * 1000
// The lens never narrows below 15 min, so it stays grabbable and the zoomed axis keeps a readable span.
const MIN_LENS_MS = 15 * 60 * 1000
// A run with no final duration is treated as in flight up to now — but only up to this cap. A run that
// started longer ago than this and still hasn't settled almost certainly never will (its completion webhook
// was missed); without the cap its interval would stretch to now and inflate the in-flight band — and the
// time axis — by hours or days. Capping bounds that phantom load while still counting a genuinely-running
// recent run right up to now.
const MAX_IN_FLIGHT_MS = 60 * 60 * 1000

/** Round up to a "nice" number (1/2/5 × 10ⁿ) so axis ticks land on readable values. */
function niceStep(rough: number): number {
    if (rough <= 0) {
        return 1
    }
    const pow = Math.pow(10, Math.floor(Math.log10(rough)))
    const n = rough / pow
    const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10
    return step * pow
}

/** Compact minutes label for the duration axis: "45m", "1h", "1h 30m". */
function formatAxisMinutes(min: number): string {
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

/** The focus lens: a thin strip spanning the whole loaded window with a draggable window selecting the
 *  sub-range the scatter and band zoom into. Drag the body to pan back to older runs; drag an edge to widen
 *  or narrow (zoom). The geometry (pan/resize/clamp) lives in lib/brush so it's unit-tested without a DOM. */
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

    // Track the pointer on the window (not just the lens) so a fast drag that outruns the cursor keeps
    // panning; the listeners attach once per drag (deps don't include the moving bounds — they're frozen in
    // dragRef) and tear down on pointer-up.
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

/**
 * Two views of one workflow's runs on a shared time axis: a scatter of each completed run by start time
 * (X) and wall-clock duration (Y), colored by verdict with a dashed median line; and below it an
 * "in-flight" band showing how many runs were executing at once (the red fill is the failing share, the
 * peak is labeled). The scatter answers "are runs slow / failing?"; the band answers "how much parallel
 * load?". Renders nothing below `MIN_POINTS` completed runs, so callers drop it in unconditionally.
 */
export function RunActivityChart({
    runs,
    title = 'Run activity',
    truncated = false,
    className,
}: RunActivityChartProps): JSX.Element | null {
    // The lens sub-range the scatter/band zoom into; null = the default (most recent day). Declared before
    // the early return so the hook order is stable when there aren't enough points to draw.
    const [focus, setFocus] = useState<TimeRange | null>(null)
    // Drop a manual pan when the runs change (e.g. the shared window changed and reloaded) so the lens
    // returns to the live default instead of clamping a stale range onto an unrelated slice of new data.
    useEffect(() => {
        setFocus(null)
    }, [runs])
    const now = dayjs().valueOf()
    // Every run with a start contributes an interval to the band; a still-running run extends to now, but
    // only up to MAX_IN_FLIGHT_MS so an abandoned run that never settled doesn't stretch the band by days.
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

    // Only completed runs land on the scatter — a still-running run has no final duration to place on Y.
    const plottable = runs.filter(
        (run): run is ActivityRun & { startedAt: string; durationSeconds: number } =>
            run.startedAt != null && run.durationSeconds != null && run.durationSeconds >= 0
    )
    if (plottable.length < MIN_POINTS) {
        return null
    }

    // Full extent of the loaded runs, then the focus lens the scatter/band actually render. tMin/tMax below
    // are the lens bounds, so the existing x-axis/band code zooms to the focus without further changes; the
    // y (duration) scale and median stay over the full set, so panning never jumps the vertical axis.
    const fullMin = Math.min(...intervals.map((iv) => iv.start))
    const fullMax = Math.max(...intervals.map((iv) => iv.end))
    const brushable = fullMax - fullMin > LENS_MS
    const view = clampFocus(focus ?? defaultFocus(fullMin, fullMax, LENS_MS), fullMin, fullMax, MIN_LENS_MS)
    const tMin = view.start
    const tMax = view.end
    const tSpan = Math.max(1, tMax - tMin)
    const xPct = (ms: number): number => ((ms - tMin) / tSpan) * 100

    const durationsMin = plottable.map((run) => run.durationSeconds / 60)
    const maxMin = Math.max(...durationsMin)
    // Tick interval is a "nice" number ~maxMin/4; the axis top is the smallest multiple of it that clears
    // the slowest run, so ticks read as round values and there's little dead space above the points.
    const step = niceStep(maxMin / Y_TICK_COUNT)
    const niceMaxMin = Math.max(step, Math.ceil(maxMin / step) * step)
    const yPx = (min: number): number => SCATTER_HEIGHT * (1 - min / niceMaxMin)

    // Same median as the health summary's medianSeconds (one implementation), so chart and KPIs agree.
    const sortedMin = [...durationsMin].sort((a, b) => a - b)
    const medianMin = percentileSorted(sortedMin, 0.5) ?? 0

    // Only the runs inside the focus lens are plotted; the duration scale and median above stay over the
    // full set so the y-axis holds still while you pan.
    const visible = plottable.filter((run) => {
        const t = dayjs(run.startedAt).valueOf()
        return t >= tMin && t <= tMax
    })

    // Collected here so the legend reuses the per-run verdict instead of re-deriving it for every type.
    const presentTypeSet = new Set<string>()
    const points: Point[] = visible.map((run, i) => {
        const tag = verdictTag(run.conclusion)
        presentTypeSet.add(tag.type)
        return {
            key: `${run.runId ?? 'run'}-${i}`,
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

    // Clip each interval to the focus lens so the band shows concurrency within the zoomed window, sharing
    // the scatter's x-axis. Intervals that don't overlap the focus drop out.
    const focusIntervals = intervals
        .map((iv) => ({ ...iv, start: Math.max(iv.start, tMin), end: Math.min(iv.end, tMax) }))
        .filter((iv) => iv.end > iv.start)

    // In-flight band: exact concurrency via a sweep line over each run's start/end. Sampling fixed instants
    // misses any run that begins and ends between two samples (minute-long runs on a 30-day window) — those
    // would never be counted, so the band could read empty with the wrong peak even with runs on the scatter.
    const bandEvents = focusIntervals.flatMap((iv) => {
        const failDelta = isDecisiveFailure(iv.conclusion) ? 1 : 0
        return [
            { t: iv.start, dTotal: 1, dFailing: failDelta },
            { t: iv.end, dTotal: -1, dFailing: -failDelta },
        ]
    })
    bandEvents.sort((a, b) => a.t - b.t)
    // Walk the events, holding each concurrency level until the next; coalesce events at the same instant.
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
    // True peak concurrency for the label — 0 when the lens covers a gap with no runs. The band height
    // divides by it, so use a separate denominator that's never 0.
    const peak = steps.length ? Math.max(...steps.map((s) => s.total)) : 0
    const bandScale = Math.max(1, peak)
    const bandX = (t: number): string => (((t - tMin) / tSpan) * 1000).toFixed(1)
    const bandY = (v: number): string => (BAND_HEIGHT - (v / bandScale) * (BAND_HEIGHT - 2)).toFixed(1)
    // Concurrency is piecewise-constant, so draw step areas: hold the prior level to the event's x, then jump.
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
                            ? `Over the most recent ${plottable.length} runs — the list is capped, so this isn't the full window.`
                            : undefined
                    }
                >
                    <span className="text-xs whitespace-nowrap text-secondary tabular-nums">
                        {truncated ? 'recent ' : ''}
                        {brushable ? `${visible.length} of ${plottable.length}` : plottable.length} runs · median{' '}
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
                        {/* X axis: time ticks; first/last anchor to the edges so labels don't clip. */}
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
                        {/* Focus lens over the full window — drag to pan to older runs, drag an edge to zoom. */}
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
