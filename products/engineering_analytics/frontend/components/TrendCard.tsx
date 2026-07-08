// A stat-plus-trend card for the repo hub's Trends strip: lead with the current value and its change
// across the window (the answer), over a sentiment-colored sparkline (the context). `goodWhenDown` colors
// both the delta and the line green when the metric is falling (time-to-green, cost), red when rising.

import { ReactNode } from 'react'

import { LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'

import { DeltaBadge, percentChange } from './MetricTile'

export interface TrendSeries {
    values: number[]
    labels: string[]
}

export function TrendCard({
    title,
    series,
    formatValue,
    renderTooltipValue,
    goodWhenDown = false,
    caption,
    loading = false,
    emptyText,
}: {
    title: string
    series: TrendSeries | null
    /** Formats the headline (latest) value, e.g. minutes or USD. */
    formatValue: (value: number) => string
    renderTooltipValue: (value: number) => string
    goodWhenDown?: boolean
    caption: ReactNode
    loading?: boolean
    emptyText: string
}): JSX.Element {
    const values = series?.values ?? []
    const latest = values.length ? values[values.length - 1] : null
    // Baseline for the delta is the first non-zero point, so leading zero-filled buckets (empty early
    // window) don't null the comparison or read as an infinite jump off zero.
    const first = values.find((value) => value !== 0) ?? (values.length ? values[0] : null)
    const deltaPct = percentChange(latest, first)
    // Line color follows the delta's sentiment so the card reads at a glance: green the good way, red the
    // bad way, muted when flat or without a baseline.
    const lineColor =
        deltaPct == null || deltaPct === 0 ? 'muted' : deltaPct < 0 === goodWhenDown ? 'success' : 'danger'

    return (
        <LemonCard hoverEffect={false} className="flex flex-col p-4">
            <h3 className="mb-1 text-xs font-semibold text-secondary">{title}</h3>
            {loading ? (
                <LemonSkeleton className="h-20 w-full" />
            ) : values.length ? (
                <>
                    <div className="mb-1 flex items-baseline gap-2">
                        <span className="text-2xl font-semibold leading-none tabular-nums">
                            {formatValue(latest as number)}
                        </span>
                        <DeltaBadge
                            value={deltaPct}
                            goodWhenDown={goodWhenDown}
                            vs="latest vs the start of the window"
                        />
                    </div>
                    <Sparkline
                        data={values}
                        labels={series?.labels}
                        name={title}
                        type="line"
                        color={lineColor}
                        maximumIndicator={false}
                        className="h-16 w-full"
                        renderLabel={(label) => label}
                        renderTooltipValue={renderTooltipValue}
                    />
                </>
            ) : (
                <div className="flex h-20 items-center text-xs text-secondary">{emptyText}</div>
            )}
            <div className="mt-2 border-t border-primary pt-2 text-[11px] text-tertiary">{caption}</div>
        </LemonCard>
    )
}
