// Merged-PR throughput card for the PR page: daily merged counts as a recessive line under a
// sentiment-colored 7-day-average trend line, led by the average-per-day headline and its
// week-over-week delta. Mirrors TrendCard's chrome; separate because it overlays two series
// (raw + rolling average) where TrendCard draws one.

import { LemonButton, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'

import { MERGE_TREND_WINDOW_DAYS, MergedPerDayData } from '../scenes/engineeringAnalyticsLogic'
import { DeltaBadge } from './MetricTile'

export function MergedPerDayCard({
    data,
    loading = false,
    error = false,
    onRetry,
}: {
    data: MergedPerDayData | null
    loading?: boolean
    /** Last load failed: render a retry state, never the "no merges" copy or a stale series. */
    error?: boolean
    onRetry?: () => void
}): JSX.Element {
    // More merges is the good direction; the trend line follows the delta's sentiment like TrendCard.
    const deltaPct = data?.weekOverWeekPct ?? null
    const trendColor = deltaPct == null || deltaPct === 0 ? 'muted' : deltaPct > 0 ? 'success' : 'danger'

    return (
        <LemonCard hoverEffect={false} className="flex flex-col p-4">
            <h3 className="mb-1 text-xs font-semibold text-secondary">Merged per day</h3>
            {loading ? (
                <LemonSkeleton className="h-20 w-full" />
            ) : error ? (
                <div className="flex h-20 items-center gap-2 text-xs text-secondary">
                    <span>Couldn't load merge activity.</span>
                    {onRetry && (
                        <LemonButton type="secondary" size="xsmall" onClick={onRetry}>
                            Retry
                        </LemonButton>
                    )}
                </div>
            ) : data ? (
                <>
                    <div className="mb-1 flex items-baseline gap-2">
                        <span className="text-2xl font-semibold leading-none tabular-nums">
                            {data.avgPerDay.toFixed(1)}
                        </span>
                        <span className="text-xs text-secondary">avg per day</span>
                        <DeltaBadge value={deltaPct} vs="last 7 days vs the 7 before" />
                    </div>
                    <Sparkline
                        data={[
                            { name: 'Merged', values: data.values, color: 'muted' },
                            { name: `${MERGE_TREND_WINDOW_DAYS}-day average`, values: data.trend, color: trendColor },
                        ]}
                        labels={data.labels}
                        type="line"
                        maximumIndicator={false}
                        // The legacy sparkline stacks every scale; two overlaid lines must not sum.
                        withYScale={(y) => ({ ...y, stacked: false })}
                        className="h-16 w-full"
                        renderLabel={(label) => label}
                    />
                </>
            ) : (
                <div className="flex h-20 items-center text-xs text-secondary">
                    No merge data to show yet. The trend appears once a full day of data lands.
                </div>
            )}
            <div className="mt-2 border-t border-primary pt-2 text-[11px] text-tertiary">
                {data && !loading && !error
                    ? `${data.totalMerged} merged in the last ${data.values.length} full days. `
                    : ''}
                Pull requests merged per complete day, bots excluded; the trend line is the {MERGE_TREND_WINDOW_DAYS}
                -day average. Today is still in progress and not shown.
            </div>
        </LemonCard>
    )
}
