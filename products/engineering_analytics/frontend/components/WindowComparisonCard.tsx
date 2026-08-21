// A window-comparison card for the repo hub's headline sections. Each metric's question is "this
// window vs the previous window", a comparison of exactly two values, so the graphic is two labeled
// horizontal bars on a shared zero-based scale rather than a time series: the daily buckets behind
// these metrics are noise at this grain. Rates use a pass/fail split bar per window, where the
// status colors are the data; a duration card can pin a p90 tick on each bar to show the tail on
// the same scale as the median.

import { ReactNode } from 'react'

import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { DeltaBadge, percentChange, pointChange } from './MetricTile'

function MagnitudeBar({
    fraction,
    current,
    markerFraction,
    markerTooltip,
}: {
    fraction: number
    current: boolean
    markerFraction?: number | null
    markerTooltip?: string
}): JSX.Element {
    return (
        <div className="relative h-2.5 flex-1 rounded-sm">
            <div
                className={`h-full rounded-sm ${current ? 'bg-[var(--data-color-1)]' : 'bg-[var(--muted)]'}`}
                style={{ width: `${Math.max(fraction * 100, 2)}%` }}
            />
            {markerFraction != null && (
                <Tooltip title={markerTooltip}>
                    <div
                        className="absolute -top-0.5 h-3.5 w-0.5 -translate-x-1/2 rounded-sm bg-[var(--text-3000)]"
                        style={{ left: `${markerFraction * 100}%` }}
                    />
                </Tooltip>
            )}
        </div>
    )
}

function SplitBar({ rate }: { rate: number }): JSX.Element {
    const passedPercent = Math.round(rate * 100)
    return (
        <Tooltip title={`${passedPercent}% passed, ${100 - passedPercent}% failed`}>
            <div className="flex h-2.5 flex-1 overflow-hidden rounded-sm">
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
    marker,
    markerLabel,
}: {
    label: string
    value: number
    max: number
    formatValue: (value: number) => string
    /** Render the value as a pass/fail split of the whole bar instead of a length. */
    share: boolean
    current: boolean
    marker?: number | null
    markerLabel?: string
}): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <span className="w-24 shrink-0 text-[11px] text-tertiary">{label}</span>
            {share ? (
                <SplitBar rate={value} />
            ) : (
                <MagnitudeBar
                    fraction={max > 0 ? value / max : 0}
                    current={current}
                    markerFraction={marker != null && max > 0 ? marker / max : null}
                    markerTooltip={marker != null && markerLabel ? `${markerLabel} ${formatValue(marker)}` : undefined}
                />
            )}
            <span className="w-12 shrink-0 text-right text-xs font-medium tabular-nums">{formatValue(value)}</span>
        </div>
    )
}

export function WindowComparisonCard({
    title,
    value,
    previousValue,
    formatValue,
    goodWhenDown = false,
    share = false,
    deltaUnit,
    tooltip,
    marker,
    markerPrevious,
    markerLabel,
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
    /** Definition or methodology, shown on title hover. */
    tooltip?: ReactNode
    /** A companion figure (e.g. p90) pinned as a tick on each magnitude bar, on the same scale as
     *  the value. Ignored in `share` mode, which has no scale to pin against. */
    marker?: number | null
    markerPrevious?: number | null
    markerLabel?: string
    loading?: boolean
    emptyText: string
}): JSX.Element {
    const max = Math.max(value ?? 0, previousValue ?? 0, marker ?? 0, markerPrevious ?? 0)
    const delta = deltaUnit === 'pt' ? pointChange(value, previousValue) : percentChange(value, previousValue)

    return (
        <LemonCard hoverEffect={false} className="flex flex-col p-4">
            <h3 className="mb-1 text-xs font-semibold text-secondary">
                {tooltip ? (
                    <Tooltip title={tooltip}>
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
                            vs="vs the previous window"
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
                            marker={marker}
                            markerLabel={markerLabel}
                        />
                        {previousValue != null && (
                            <ComparisonRow
                                label="Previous window"
                                value={previousValue}
                                max={max}
                                formatValue={formatValue}
                                share={share}
                                current={false}
                                marker={markerPrevious}
                                markerLabel={markerLabel}
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
