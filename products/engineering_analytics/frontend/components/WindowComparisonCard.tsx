// A window-comparison card for the repo hub's headline sections. Each metric's question is "this
// window vs the previous window", a comparison of exactly two values, so the graphic is two labeled
// horizontal bars on a shared zero-based scale rather than a time series: the daily buckets behind
// these metrics are noise at this grain. Rates use a pass/fail split bar per window, where the
// status colors are the data.

import { ReactNode } from 'react'

import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { DoraBand, DoraBenchmark } from '../lib/doraBenchmark'
import { percent } from '../lib/format'
import { ComparisonBarRow } from './ComparisonBarRow'
import { DeltaBadge, percentChange, pointChange } from './MetricTile'

const BENCHMARK_EDGE_CLASS: Record<DoraBand, string> = {
    elite: 'border-l-success',
    high: 'border-l-purple',
    medium: 'border-l-warning',
    low: 'border-l-danger',
}

function PassFailSplit({ rate }: { rate: number }): JSX.Element {
    return (
        <Tooltip title={`${percent(rate, 1)} passed, ${percent(1 - rate, 1)} failed`}>
            <div className="flex h-full">
                <div className="h-full bg-success" style={{ width: `${rate * 100}%` }} />
                <div className="h-full flex-1 bg-danger" />
            </div>
        </Tooltip>
    )
}

function ComparisonRow({
    label,
    value,
    max,
    formatValue,
    share,
    current,
}: {
    label: string
    value: number
    max: number
    formatValue: (value: number) => string
    /** Render the value as a pass/fail split of the whole bar instead of a length. */
    share: boolean
    current: boolean
}): JSX.Element {
    if (share) {
        return (
            <ComparisonBarRow label={label} value={value} formatValue={formatValue}>
                <PassFailSplit rate={value} />
            </ComparisonBarRow>
        )
    }
    return <ComparisonBarRow label={label} value={value} max={max} formatValue={formatValue} muted={!current} />
}

export function WindowComparisonCard({
    title,
    value,
    previousValue,
    formatValue,
    goodWhenDown = false,
    share = false,
    deltaUnit,
    deltaPrecision,
    tooltip,
    benchmark,
    loading = false,
    emptyText,
}: {
    title: string
    /** This window's value. */
    value: number | null | undefined
    /** The previous window's value; without one the card shows this window's bar alone. */
    previousValue: number | null | undefined
    formatValue: (value: number) => string
    goodWhenDown?: boolean
    /** Rate mode: bars become a full-width pass/fail split instead of a length. */
    share?: boolean
    /** 'pt' renders the delta as percentage points; default is relative percent. */
    deltaUnit?: 'pt'
    /** Decimal places shown in the delta badge. */
    deltaPrecision?: number
    /** Definition or methodology, shown on title hover. */
    tooltip?: ReactNode
    /** Where the value lands on its DORA ladder: a colored left edge plus the ladder in the title tooltip. */
    benchmark?: DoraBenchmark | null
    loading?: boolean
    emptyText: string
}): JSX.Element {
    const max = Math.max(value ?? 0, previousValue ?? 0)
    const delta = deltaUnit === 'pt' ? pointChange(value, previousValue) : percentChange(value, previousValue)
    const tooltipContent = benchmark ? (
        <div className="flex flex-col gap-1">
            {tooltip}
            <div>
                DORA band: {benchmark.label.toLowerCase()}. {benchmark.tooltip}
            </div>
        </div>
    ) : (
        tooltip
    )

    return (
        <LemonCard
            hoverEffect={false}
            className={cn('flex flex-col p-4', benchmark && `border-l-4 ${BENCHMARK_EDGE_CLASS[benchmark.band]}`)}
        >
            <h3 className="mb-1 text-xs font-semibold text-secondary">
                {tooltipContent ? (
                    <Tooltip title={tooltipContent}>
                        <span className="cursor-default">{title}</span>
                    </Tooltip>
                ) : (
                    title
                )}
            </h3>
            {loading ? (
                <LemonSkeleton className="h-20 w-full" />
            ) : value != null ? (
                <>
                    <div className="mb-3 flex items-baseline gap-2">
                        <span className="text-2xl font-semibold leading-none tabular-nums">{formatValue(value)}</span>
                        <DeltaBadge
                            value={delta}
                            unit={deltaUnit ?? '%'}
                            goodWhenDown={goodWhenDown}
                            precision={deltaPrecision}
                        />
                    </div>
                    <div className="flex flex-col gap-1.5">
                        <ComparisonRow
                            label="This window"
                            value={value}
                            max={max}
                            formatValue={formatValue}
                            share={share}
                            current
                        />
                        {previousValue != null && (
                            <ComparisonRow
                                label="Previous window"
                                value={previousValue}
                                max={max}
                                formatValue={formatValue}
                                share={share}
                                current={false}
                            />
                        )}
                    </div>
                </>
            ) : (
                <div className="flex h-20 items-center text-xs text-secondary">{emptyText}</div>
            )}
        </LemonCard>
    )
}
