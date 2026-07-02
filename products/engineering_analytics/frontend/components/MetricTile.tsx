// The one headline-metric tile of the lens stack: label · value (+suffix) · delta vs the previous
// window · muted caption · optional sparkline. Every entity page (repo, workflow, PR, author) builds
// its stat strip from exactly this tile so the levels read identically.

import { ReactNode } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
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
    return (
        <Tooltip title={vs}>
            <span className={cn('text-xs font-semibold whitespace-nowrap', good ? 'text-success' : 'text-danger')}>
                {up ? '▲' : '▼'} {Math.abs(rounded).toFixed(precision)}
                {unit}
            </span>
        </Tooltip>
    )
}

export function MetricTile({
    label,
    value,
    valueSuffix,
    delta,
    sub,
    sparkline,
    className,
}: {
    label: string
    /** Pre-formatted headline value; '—' for no data. */
    value: string
    valueSuffix?: string
    delta?: ReactNode
    sub?: ReactNode
    /** Small in-flow trend line at the tile's bottom edge. */
    sparkline?: { values: number[]; labels?: string[]; name?: string }
    className?: string
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className={cn('flex min-w-44 flex-1 flex-col gap-1 px-5 py-4', className)}>
            <span className="text-xs text-secondary">{label}</span>
            <span className="flex items-baseline gap-2">
                <span className="text-2xl font-semibold leading-none tabular-nums">{value}</span>
                {valueSuffix && <span className="text-xs font-medium text-tertiary">{valueSuffix}</span>}
                {delta}
            </span>
            <span className="min-h-4 text-xs text-tertiary">{sub}</span>
            {sparkline && sparkline.values.length > 1 && (
                <Sparkline
                    type="line"
                    className="mt-1 h-6 w-full"
                    data={[{ name: sparkline.name ?? label, values: sparkline.values, color: 'muted' }]}
                    labels={sparkline.labels}
                    maximumIndicator={false}
                />
            )}
        </LemonCard>
    )
}
