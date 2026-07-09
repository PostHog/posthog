// Headline-metric tile: label · value (+suffix) · delta vs the previous window · caption.
// Every entity page builds its stat strip from this tile.

import { ReactNode } from 'react'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'

/** Relative change in percent, or null when there's no meaningful baseline. */
export function percentChange(current: number | null | undefined, previous: number | null | undefined): number | null {
    if (current == null || previous == null || previous === 0) {
        return null
    }
    return ((current - previous) / previous) * 100
}

/** Percentage-point change for 0–1 rates, or null when either window has no signal. */
export function pointChange(current: number | null | undefined, previous: number | null | undefined): number | null {
    if (current == null || previous == null) {
        return null
    }
    return (current - previous) * 100
}

export function DeltaBadge({
    value,
    unit = '%',
    goodWhenDown = false,
    precision = 0,
    vs = 'vs the previous window',
}: {
    /** The delta to show; null hides the badge (no baseline to compare against). */
    value: number | null
    unit?: string
    /** For costs, durations, failures — a drop is the good direction. */
    goodWhenDown?: boolean
    precision?: number
    vs?: string
}): JSX.Element | null {
    if (value == null) {
        return null
    }
    const rounded = Number(value.toFixed(precision))
    if (rounded === 0) {
        return (
            <Tooltip title={vs}>
                <span className="text-xs font-medium text-tertiary whitespace-nowrap">±0{unit}</span>
            </Tooltip>
        )
    }
    const up = rounded > 0
    const good = goodWhenDown ? !up : up
    // A near-zero baseline turns growth into a meaningless five-digit percentage — clamp the display.
    const display = Math.abs(rounded) > 999 ? '>999' : Math.abs(rounded).toFixed(precision)
    return (
        <Tooltip title={vs}>
            <span className={cn('text-xs font-semibold whitespace-nowrap', good ? 'text-success' : 'text-danger')}>
                {up ? '▲' : '▼'} {display}
                {unit}
            </span>
        </Tooltip>
    )
}

export function MetricTile({
    label,
    tooltip,
    value,
    valueSuffix,
    delta,
    sub,
    loading = false,
    className,
}: {
    label: string
    /** Definition or methodology, shown on label hover. */
    tooltip?: ReactNode
    /** Pre-formatted headline value; '—' for no data. */
    value: string
    valueSuffix?: string
    delta?: ReactNode
    /** Visible caption — only for an answer worth a glance (what's failing, why there's no value). */
    sub?: ReactNode
    /** Backend load in flight: skeleton the value so it doesn't flash a stale/zero number. Only for a
     *  genuine reload — client-side-instant derivations should never pass this. */
    loading?: boolean
    className?: string
}): JSX.Element {
    const labelSpan = <span className="text-xs text-secondary">{label}</span>
    return (
        <LemonCard
            hoverEffect={false}
            className={cn('flex min-w-44 flex-1 flex-col justify-center gap-1 px-5 py-4', className)}
        >
            {tooltip ? (
                <Tooltip title={tooltip}>
                    <span className="self-start cursor-default">{labelSpan}</span>
                </Tooltip>
            ) : (
                labelSpan
            )}
            {loading ? (
                <LemonSkeleton className="my-1 h-6 w-20" />
            ) : (
                <>
                    <span className="flex items-baseline gap-2">
                        <span className="text-2xl font-semibold leading-none tabular-nums">{value}</span>
                        {valueSuffix && <span className="text-xs font-medium text-tertiary">{valueSuffix}</span>}
                        {delta}
                    </span>
                    {sub && <span className="text-xs text-tertiary">{sub}</span>}
                </>
            )}
        </LemonCard>
    )
}
