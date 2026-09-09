// Headline-metric tile: label · value · delta pill vs the previous window · caption, rendered
// with quill's MetricCard inside the product's card chrome. Every entity page builds its stat
// strip from this tile.

import { ReactNode } from 'react'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { MetricCard, type MetricChange } from '@posthog/quill-charts'

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

/** Compact inline delta for table cells — tiles use `MetricTile`'s `delta` prop instead. */
export function DeltaBadge({
    value,
    unit = '%',
    goodWhenDown = false,
    precision = 0,
}: {
    /** The delta to show; null hides the badge (no baseline to compare against). */
    value: number | null
    unit?: string
    /** For costs, durations, failures — a drop is the good direction. */
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
    // A near-zero baseline turns growth into a meaningless five-digit percentage — clamp the display.
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

export interface TileDelta {
    /** The delta to show; null (no baseline) and ±0 both hide the pill. */
    value: number | null
    unit?: string
    /** For costs, durations, failures — a drop is the good direction. */
    goodWhenDown?: boolean
    precision?: number
    /** What the delta compares against, shown on pill hover. */
    vs?: string
}

/** DeltaBadge's display rules (rounding, ±0 suppression, >999 clamp) as a MetricCard change pill. */
function deltaToChange(delta: TileDelta | undefined): MetricChange | null {
    if (!delta || delta.value == null) {
        return null
    }
    const precision = delta.precision ?? 0
    const rounded = Number(delta.value.toFixed(precision))
    if (rounded === 0) {
        return null
    }
    // A near-zero baseline turns growth into a meaningless five-digit percentage — clamp the display.
    const display = Math.abs(rounded) > 999 ? '>999' : Math.abs(rounded).toFixed(precision)
    return { value: rounded, label: `${display}${delta.unit ?? '%'}` }
}

export interface TileBenchmark {
    /** The band name (e.g. 'Elite'), named in the label tooltip. */
    label: string
    band: 'elite' | 'high' | 'medium' | 'low'
    /** The full benchmark ladder, shown in the label tooltip. */
    tooltip: string
}

// Left accent per band: border-l-4 + a token class, the same accent recipe as WorkflowsHealthHeader.
const BENCHMARK_EDGE_CLASS: Record<TileBenchmark['band'], string> = {
    elite: 'border-l-success',
    high: 'border-l-purple',
    medium: 'border-l-warning',
    low: 'border-l-danger',
}

export function MetricTile({
    label,
    tooltip,
    value,
    delta,
    benchmark,
    sub,
    loading = false,
    className,
}: {
    label: string
    /** Definition or methodology, shown on label hover. */
    tooltip?: ReactNode
    /** Pre-formatted headline value; '—' for no data. */
    value: string
    delta?: TileDelta
    /** Where the value lands against a published benchmark ladder, shown as a coloured edge on the
     *  card plus the ladder detail in the label tooltip. */
    benchmark?: TileBenchmark | null
    /** Visible caption — only for an answer worth a glance (what's failing, why there's no value). */
    sub?: ReactNode
    /** Backend load in flight: skeleton the value so it doesn't flash a stale/zero number. Only for a
     *  genuine reload — client-side-instant derivations should never pass this. */
    loading?: boolean
    className?: string
}): JSX.Element {
    const tooltipContent =
        tooltip || benchmark ? (
            <div className="flex flex-col gap-1">
                {tooltip && <div>{tooltip}</div>}
                {benchmark && (
                    <div>
                        DORA band: {benchmark.label.toLowerCase()}. {benchmark.tooltip}
                    </div>
                )}
            </div>
        ) : undefined
    const labelNode = tooltipContent ? (
        <Tooltip title={tooltipContent}>
            <span className="cursor-default">{label}</span>
        </Tooltip>
    ) : (
        label
    )
    return (
        <LemonCard
            hoverEffect={false}
            className={cn(
                'flex min-w-44 flex-1 flex-col justify-center px-5 py-4',
                benchmark && `border-l-4 ${BENCHMARK_EDGE_CLASS[benchmark.band]}`,
                className
            )}
        >
            {/* MetricCard has no loading prop; skeleton the whole tile on a genuine reload so it never
                flashes a stale/zero headline (the loading-states rule). */}
            {loading ? (
                <div className="flex flex-col gap-2 py-1">
                    <LemonSkeleton className="h-3 w-24" />
                    <LemonSkeleton className="h-7 w-20" />
                </div>
            ) : (
                <MetricCard
                    title={labelNode}
                    // These tiles have no series data and often a non-numeric headline ("3 / 5", "2h 10m"),
                    // so the pre-formatted display string rides through MetricCard's formatter.
                    value={0}
                    formatValue={() => value}
                    change={deltaToChange(delta)}
                    goodDirection={delta?.goodWhenDown ? 'down' : 'up'}
                    changeTooltip={delta ? (delta.vs ?? 'vs the previous window') : undefined}
                    subtitle={sub}
                />
            )}
        </LemonCard>
    )
}
