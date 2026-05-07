import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { dayjs } from 'lib/dayjs'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { shortTimeZone } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import {
    LogsAlertConfigurationStateEnumApi,
    LogsAlertStateIntervalApi,
} from 'products/logs/frontend/generated/api.schemas'

// Snap the hairline to the nearest state-transition boundary when the cursor is within
// this many pixels — users care about "when did it change" far more than arbitrary mid-
// interval timestamps.
const SNAP_THRESHOLD_PX = 6

// Minimum rendered width for an interval. At 5 min/px a 1-min fire is 0.2px and disappears;
// enforcing 2px ensures every transition is visible. Short intervals steal a bit of width
// from long neighbors — a worthwhile trade since "did it fire at all" matters more than
// exact proportional fidelity for long quiet periods.
const MIN_INTERVAL_PX = 2

const PX_PER_AXIS_LABEL = 64
const AXIS_HOUR_STEPS = [1, 2, 3, 4, 6, 8, 12] as const

const STATE_LABELS: Record<LogsAlertConfigurationStateEnumApi, string> = {
    [LogsAlertConfigurationStateEnumApi.NotFiring]: 'OK',
    [LogsAlertConfigurationStateEnumApi.Firing]: 'Firing',
    [LogsAlertConfigurationStateEnumApi.PendingResolve]: 'Resolving',
    [LogsAlertConfigurationStateEnumApi.Errored]: 'Errored',
    [LogsAlertConfigurationStateEnumApi.Snoozed]: 'Snoozed',
    [LogsAlertConfigurationStateEnumApi.Broken]: 'Broken',
}

const STATE_BG: Record<LogsAlertConfigurationStateEnumApi, string> = {
    [LogsAlertConfigurationStateEnumApi.NotFiring]: 'bg-success',
    [LogsAlertConfigurationStateEnumApi.Firing]: 'bg-danger',
    [LogsAlertConfigurationStateEnumApi.PendingResolve]: 'bg-warning',
    [LogsAlertConfigurationStateEnumApi.Errored]: 'bg-warning',
    [LogsAlertConfigurationStateEnumApi.Snoozed]: 'bg-muted',
    [LogsAlertConfigurationStateEnumApi.Broken]: 'bg-danger-highlight',
}

function bgForInterval(state: LogsAlertConfigurationStateEnumApi, enabled: boolean): string {
    if (!enabled) {
        return 'bg-surface-tertiary'
    }
    return STATE_BG[state] ?? 'bg-muted'
}

function labelForInterval(state: LogsAlertConfigurationStateEnumApi, enabled: boolean): string {
    if (!enabled) {
        return 'Disabled'
    }
    return STATE_LABELS[state] ?? state
}

interface HoverState {
    barLeft: number
    barTop: number
    barX: number
}

export interface LogsAlertStateTimelineProps {
    timeline: readonly LogsAlertStateIntervalApi[] | undefined
    className?: string
    // Render a time axis below the bar — HH:mm labels at a responsive hour granularity,
    // falling back to "24h ago" / "Now" when the bar is too narrow for multiple labels.
    showAxis?: boolean
}

export function LogsAlertStateTimeline({
    timeline,
    className,
    showAxis = false,
}: LogsAlertStateTimelineProps): JSX.Element | null {
    const containerRef = useRef<HTMLDivElement>(null)
    const segmentRefs = useRef<(HTMLDivElement | null)[]>([])
    const { width: measuredWidth = 0 } = useResizeObserver<HTMLDivElement>({ ref: containerRef })
    const [hover, setHover] = useState<HoverState | null>(null)
    const [measuredEdges, setMeasuredEdges] = useState<number[] | null>(null)

    // Parse ISO timestamps once per timeline — used by every layout and hover memo.
    const intervalMs = useMemo(() => {
        if (!timeline) {
            return []
        }
        return timeline.map((i) => ({ startMs: dayjs(i.start).valueOf(), endMs: dayjs(i.end).valueOf() }))
    }, [timeline])

    const bounds = useMemo(() => {
        if (!intervalMs.length) {
            return null
        }
        const startMs = intervalMs[0].startMs
        const endMs = intervalMs[intervalMs.length - 1].endMs
        return { startMs, endMs, durationMs: Math.max(endMs - startMs, 1) }
    }, [intervalMs])

    // Read actual rendered segment positions directly from the DOM — keeps the hairline
    // locked to the visible boundaries even if the browser's flex + min-width layout
    // differs by a subpixel from what we'd compute in JS.
    useLayoutEffect(() => {
        if (!intervalMs.length || !containerRef.current || measuredWidth === 0) {
            setMeasuredEdges(null)
            return
        }
        const containerLeft = containerRef.current.getBoundingClientRect().left
        const edges: number[] = [0]
        for (let i = 0; i < intervalMs.length; i++) {
            const seg = segmentRefs.current[i]
            if (!seg) {
                return
            }
            edges.push(seg.getBoundingClientRect().right - containerLeft)
        }
        setMeasuredEdges(edges)
    }, [intervalMs, measuredWidth])

    const axisTicks = useMemo(() => {
        if (!showAxis || !bounds || measuredWidth === 0) {
            return null
        }
        const idealLabels = Math.floor(measuredWidth / PX_PER_AXIS_LABEL)
        if (idealLabels < 2) {
            return null
        }
        let chosenStep = AXIS_HOUR_STEPS[AXIS_HOUR_STEPS.length - 1]
        for (const step of AXIS_HOUR_STEPS) {
            if (24 / step + 1 <= idealLabels) {
                chosenStep = step
                break
            }
        }
        const clockTicks: { ts: number; ratio: number }[] = []
        let cursor = dayjs(bounds.endMs).startOf('hour')
        while (cursor.valueOf() >= bounds.startMs) {
            const ratio = (cursor.valueOf() - bounds.startMs) / bounds.durationMs
            if (ratio > 0 && ratio < 1) {
                clockTicks.push({ ts: cursor.valueOf(), ratio })
            }
            cursor = cursor.subtract(chosenStep, 'hour')
        }
        const collisionRatio = PX_PER_AXIS_LABEL / measuredWidth
        const middle = clockTicks.filter((t) => t.ratio > collisionRatio && t.ratio < 1 - collisionRatio)
        middle.reverse()
        return [{ ts: bounds.startMs, ratio: 0 }, ...middle, { ts: bounds.endMs, ratio: 1 }]
    }, [showAxis, bounds, measuredWidth])

    const hoverInfo = useMemo(() => {
        if (!hover || !bounds || !intervalMs.length || !measuredEdges) {
            return null
        }

        let cursorIdx = intervalMs.length - 1
        for (let i = 0; i < intervalMs.length; i++) {
            if (hover.barX >= measuredEdges[i] && hover.barX < measuredEdges[i + 1]) {
                cursorIdx = i
                break
            }
        }

        let snappedIdx = -1
        let bestDeltaPx = SNAP_THRESHOLD_PX
        for (let i = 1; i < intervalMs.length; i++) {
            const delta = Math.abs(measuredEdges[i] - hover.barX)
            if (delta < bestDeltaPx) {
                bestDeltaPx = delta
                snappedIdx = i
            }
        }

        if (snappedIdx >= 0) {
            return {
                ts: intervalMs[snappedIdx].startMs,
                interval: timeline![snappedIdx],
                previousInterval: timeline![snappedIdx - 1] ?? null,
                snapped: true,
                hairlineX: measuredEdges[snappedIdx],
            }
        }

        const { startMs, endMs } = intervalMs[cursorIdx]
        const intervalPxStart = measuredEdges[cursorIdx]
        const intervalPxWidth = Math.max(measuredEdges[cursorIdx + 1] - intervalPxStart, 1)
        const rawMs = startMs + ((hover.barX - intervalPxStart) / intervalPxWidth) * (endMs - startMs)

        return {
            ts: rawMs,
            interval: timeline![cursorIdx],
            previousInterval: null,
            snapped: false,
            hairlineX: hover.barX,
        }
    }, [hover, bounds, intervalMs, measuredEdges, timeline])

    if (!timeline || timeline.length === 0 || !bounds) {
        return <div className={cn('bg-surface-tertiary rounded-xs', className)} />
    }

    const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>): void => {
        const rect = e.currentTarget.getBoundingClientRect()
        const barX = e.clientX - rect.left
        setHover((prev) => {
            // Re-renders only when the integer pixel position changes — sub-pixel jitter
            // and repeat events at the same x are ignored.
            if (prev && Math.round(prev.barX) === Math.round(barX) && prev.barLeft === rect.left) {
                return prev
            }
            return { barLeft: rect.left, barTop: rect.top, barX }
        })
    }

    const handleMouseLeave = (): void => setHover(null)

    const tz = shortTimeZone()
    const tzSuffix = tz ? ` ${tz}` : ''
    const tooltipClientX = hover && hoverInfo ? hover.barLeft + hoverInfo.hairlineX : 0

    const bar = (
        <div
            ref={containerRef}
            className={cn('relative', className)}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
        >
            <div className="flex h-full w-full overflow-hidden rounded-xs border border-primary">
                {timeline.map((interval, idx) => {
                    const flex = Math.max(intervalMs[idx].endMs - intervalMs[idx].startMs, 0)
                    return (
                        <div
                            key={idx}
                            ref={(el) => {
                                segmentRefs.current[idx] = el
                            }}
                            className={cn('h-full', bgForInterval(interval.state, interval.enabled))}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ flex: `${flex} 0 0`, minWidth: MIN_INTERVAL_PX }}
                        />
                    )
                })}
            </div>
            {hover && hoverInfo && (
                <div
                    className={cn(
                        'absolute inset-y-0 pointer-events-none',
                        hoverInfo.snapped ? 'w-0.5 bg-text-3000' : 'w-px bg-text-3000/60'
                    )}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ left: hoverInfo.hairlineX }}
                />
            )}
            {hover &&
                hoverInfo &&
                createPortal(
                    <div
                        className="fixed whitespace-nowrap pointer-events-none text-xs px-1.5 py-0.5 rounded-xs bg-surface-primary border border-primary shadow-md"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            left: tooltipClientX,
                            top: hover.barTop - 8,
                            transform: 'translate(-50%, -100%)',
                            zIndex: 99999,
                        }}
                    >
                        <span className="font-mono mr-1.5">
                            {dayjs(hoverInfo.ts).format('HH:mm')}
                            {tzSuffix}
                        </span>
                        {hoverInfo.snapped && hoverInfo.previousInterval ? (
                            <span>
                                <span className="text-muted">
                                    {labelForInterval(
                                        hoverInfo.previousInterval.state,
                                        hoverInfo.previousInterval.enabled
                                    )}
                                </span>
                                <span className="mx-1 text-muted">→</span>
                                <span className="font-semibold">
                                    {labelForInterval(hoverInfo.interval.state, hoverInfo.interval.enabled)}
                                </span>
                            </span>
                        ) : (
                            <span className="font-semibold">
                                {labelForInterval(hoverInfo.interval.state, hoverInfo.interval.enabled)}
                            </span>
                        )}
                    </div>,
                    document.body
                )}
        </div>
    )

    if (!showAxis) {
        return bar
    }

    return (
        <div className="flex flex-col gap-1">
            {bar}
            {axisTicks && axisTicks.length >= 2 ? (
                <div className="relative h-4 text-xs text-muted font-mono">
                    {axisTicks.map((t) => {
                        const transform =
                            t.ratio < 0.04 ? 'translateX(0)' : t.ratio > 0.96 ? 'translateX(-100%)' : 'translateX(-50%)'
                        return (
                            <span
                                key={t.ts}
                                className="absolute top-0"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ left: `${t.ratio * 100}%`, transform }}
                            >
                                {dayjs(t.ts).format('HH:mm')}
                            </span>
                        )
                    })}
                </div>
            ) : (
                <div className="flex justify-between text-xs text-muted font-mono">
                    <span>24h ago</span>
                    <span>Now</span>
                </div>
            )}
        </div>
    )
}
