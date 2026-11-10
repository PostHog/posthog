import { ReactNode } from 'react'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { Metric, MetricSubtitle, MetricTitle, MetricValue } from '@posthog/quill-components/metric'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'

export function percentChange(current: number | null | undefined, previous: number | null | undefined): number | null {
    if (current == null || previous == null || previous === 0) {
        return null
    }
    return ((current - previous) / previous) * 100
}

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
}: {
    value: number | null
    unit?: string
    goodWhenDown?: boolean
    precision?: number
}): JSX.Element | null {
    if (value == null) {
        return null
    }
    const rounded = Number(value.toFixed(precision))
    if (rounded === 0) {
        return (
            <Tooltip title="vs the previous window">
                <span className="text-xs font-medium text-tertiary whitespace-nowrap">±0{unit}</span>
            </Tooltip>
        )
    }
    const up = rounded > 0
    const good = goodWhenDown ? !up : up
    // A near-zero baseline turns growth into a meaningless five-digit percentage, so clamp the display.
    const display = Math.abs(rounded) > 999 ? '>999' : Math.abs(rounded).toFixed(precision)
    return (
        <Tooltip title="vs the previous window">
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
    sub,
    loading = false,
    className,
}: {
    label: string
    tooltip?: ReactNode
    value: string
    sub?: ReactNode
    loading?: boolean
    className?: string
}): JSX.Element {
    const labelNode = tooltip ? (
        <Tooltip title={tooltip}>
            <span className="cursor-default">{label}</span>
        </Tooltip>
    ) : (
        label
    )
    return (
        <LemonCard
            hoverEffect={false}
            className={cn('flex min-w-44 flex-1 flex-col justify-center px-5 py-4', className)}
        >
            {/* Metric has no loading prop, so the whole tile skeletons during a reload. */}
            {loading ? (
                <div className="flex flex-col gap-2 py-1">
                    <LemonSkeleton className="h-3 w-24" />
                    <LemonSkeleton className="h-7 w-20" />
                </div>
            ) : (
                // The headline is often non-numeric ("3 / 5", "2h 10m"), so it renders as children.
                <Metric value={0} subtitle={sub} className="px-0">
                    <MetricTitle>{labelNode}</MetricTitle>
                    <MetricValue className="mt-2">{value}</MetricValue>
                    <MetricSubtitle className="mt-1" />
                </Metric>
            )}
        </LemonCard>
    )
}
