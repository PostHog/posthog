// The comparison draws two bars on a shared zero-based scale, not a time series, because the daily
// buckets behind these metrics are noise at this grain.

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

function PreviousWindowNote({ text }: { text: string }): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <span className="w-24 shrink-0 truncate text-[11px] text-tertiary">Previous window</span>
            <span className="text-[11px] text-tertiary">{text}</span>
        </div>
    )
}

function previousWindowGap(
    previousValue: number | null | undefined,
    formatValue: (value: number) => string,
    relative: boolean
): string | null {
    if (previousValue == null) {
        return 'No data'
    }
    // A relative change against a value that displays as zero (a 9s median shown as "0m") reads as a
    // huge swing that the shown numbers can't explain.
    if (relative && previousValue > 0 && formatValue(previousValue) === formatValue(0)) {
        return 'Too close to zero to compare'
    }
    return null
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
    value: number | null | undefined
    previousValue: number | null | undefined
    formatValue: (value: number) => string
    goodWhenDown?: boolean
    /** Rate mode: each bar becomes a full-width pass/fail split instead of a length. */
    share?: boolean
    /** 'pt' renders the delta as percentage points. The default is relative percent. */
    deltaUnit?: 'pt'
    deltaPrecision?: number
    tooltip?: ReactNode
    benchmark?: DoraBenchmark | null
    loading?: boolean
    emptyText: string
}): JSX.Element {
    const previousGap = previousWindowGap(previousValue, formatValue, deltaUnit !== 'pt')
    const comparablePrevious = previousGap == null ? previousValue : null
    const max = Math.max(value ?? 0, comparablePrevious ?? 0)
    const delta = deltaUnit === 'pt' ? pointChange(value, comparablePrevious) : percentChange(value, comparablePrevious)
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
                        {comparablePrevious != null ? (
                            <ComparisonRow
                                label="Previous window"
                                value={comparablePrevious}
                                max={max}
                                formatValue={formatValue}
                                share={share}
                                current={false}
                            />
                        ) : (
                            <PreviousWindowNote text={previousGap ?? 'No data'} />
                        )}
                    </div>
                </>
            ) : (
                <div className="flex h-20 items-center text-xs text-secondary">{emptyText}</div>
            )}
        </LemonCard>
    )
}
