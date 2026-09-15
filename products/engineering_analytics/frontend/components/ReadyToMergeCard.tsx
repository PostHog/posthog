// Ready for review to merged, split at the first approval. Medians of the two legs do not add up to
// the median of the whole, so the bar length is the whole median and the split is the share of summed
// hours on each side of the approval. The leg medians sit under the bars as separate numbers.

import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import type { DeliverySummaryApi } from '../generated/api.schemas'
import { compactAgeLabel, percent } from '../lib/format'
import { ComparisonBarRow } from './ComparisonBarRow'

const BEFORE_APPROVAL_COLOR = 'var(--data-color-3)'
const AFTER_APPROVAL_COLOR = 'var(--data-color-1)'

function ApprovalSplit({ beforeShare }: { beforeShare: number | null }): JSX.Element {
    if (beforeShare == null) {
        return <div className="h-full bg-[var(--muted)]" />
    }
    return (
        <div className="flex h-full gap-px">
            <Tooltip title={`Before the first approval: ${percent(beforeShare)} of the hours`}>
                <div
                    className="h-full"
                    style={{ flex: `${beforeShare} 1 0`, backgroundColor: BEFORE_APPROVAL_COLOR }}
                />
            </Tooltip>
            <Tooltip title={`After the first approval: ${percent(1 - beforeShare)} of the hours`}>
                <div
                    className="h-full"
                    style={{ flex: `${1 - beforeShare} 1 0`, backgroundColor: AFTER_APPROVAL_COLOR }}
                />
            </Tooltip>
        </div>
    )
}

function SplitRow({
    label,
    value,
    p90,
    beforeShare,
    max,
    isScope,
}: {
    label: string
    value: number
    p90: number | null
    beforeShare: number | null
    max: number
    isScope: boolean
}): JSX.Element {
    return (
        <ComparisonBarRow
            label={label}
            value={compactAgeLabel(value)}
            fraction={value / max}
            muted={!isScope}
            marker={p90 != null ? { fraction: p90 / max, tooltip: `90th percentile ${compactAgeLabel(p90)}` } : null}
        >
            <ApprovalSplit beforeShare={beforeShare} />
        </ComparisonBarRow>
    )
}

function LegRow({
    color,
    label,
    scope,
    repo,
}: {
    color: string
    label: string
    scope: number | null
    repo: number | null
}): JSX.Element {
    return (
        <div className="grid grid-cols-[minmax(0,1fr)_auto_5rem] items-baseline gap-2 border-t border-primary py-1 text-xs text-secondary">
            <span className="flex min-w-0 items-center gap-1.5">
                <span className="size-2 shrink-0 rounded-sm" style={{ backgroundColor: color }} />
                <span className="truncate">{label}</span>
            </span>
            <span className="font-semibold tabular-nums text-primary">{compactAgeLabel(scope)}</span>
            <span className="text-right tabular-nums text-tertiary">repo {compactAgeLabel(repo)}</span>
        </div>
    )
}

export function ReadyToMergeCard({
    summary,
    scopeLabel,
    loading,
}: {
    summary: DeliverySummaryApi | null
    /** The row label for the scope's bar, e.g. "This author" or "This team". */
    scopeLabel: string
    loading: boolean
}): JSX.Element {
    const median = summary?.median_ready_to_merge_seconds
    const p90 = summary?.p90_ready_to_merge_seconds
    const share = summary?.before_first_approval_share
    const reviewsSynced = !!summary?.review_data_available
    const max = Math.max(...[median?.scope, median?.repo, p90?.scope, p90?.repo].map((value) => value ?? 0))

    return (
        <LemonCard
            hoverEffect={false}
            className="flex h-full flex-col p-4"
            data-attr="engineering-analytics-delivery-ready"
        >
            <h3 className="mb-1 text-xs font-semibold text-secondary">
                <Tooltip title="Median calendar time from the last ready for review to the merge, over pull requests merged in the window. The bar length is that median. Its split is the share of all those hours spent before and after the first approval, so long pull requests weigh more. The two medians below are separate medians and do not add up to the total.">
                    <span className="cursor-default">Ready for review to merged</span>
                </Tooltip>
            </h3>
            {loading ? (
                <LemonSkeleton className="h-24 w-full" />
            ) : median?.scope != null ? (
                <>
                    <div className="mb-3 flex flex-wrap items-baseline gap-2">
                        <span className="text-2xl font-semibold leading-none tabular-nums">
                            {compactAgeLabel(median.scope)}
                        </span>
                        {median.repo != null && (
                            <span className="text-xs tabular-nums text-tertiary">
                                repo {compactAgeLabel(median.repo)}
                            </span>
                        )}
                    </div>
                    <div className="flex flex-col gap-1.5">
                        <SplitRow
                            label={scopeLabel}
                            value={median.scope}
                            p90={p90?.scope ?? null}
                            beforeShare={reviewsSynced ? (share?.scope ?? null) : null}
                            max={max}
                            isScope
                        />
                        {median.repo != null && (
                            <SplitRow
                                label="Repo"
                                value={median.repo}
                                p90={p90?.repo ?? null}
                                beforeShare={reviewsSynced ? (share?.repo ?? null) : null}
                                max={max}
                                isScope={false}
                            />
                        )}
                    </div>
                    {reviewsSynced ? (
                        <div className="mt-3 flex flex-col">
                            <LegRow
                                color={BEFORE_APPROVAL_COLOR}
                                label="Ready to first approval, median"
                                scope={summary?.median_ready_to_first_approval_seconds.scope ?? null}
                                repo={summary?.median_ready_to_first_approval_seconds.repo ?? null}
                            />
                            <LegRow
                                color={AFTER_APPROVAL_COLOR}
                                label="First approval to merged, median"
                                scope={summary?.median_first_approval_to_merge_seconds.scope ?? null}
                                repo={summary?.median_first_approval_to_merge_seconds.repo ?? null}
                            />
                        </div>
                    ) : (
                        <div className="mt-2 text-[11px] text-tertiary">
                            Sync the reviews table on this GitHub source to split the wait at the first approval.
                        </div>
                    )}
                </>
            ) : (
                <div className="flex h-20 items-center text-xs text-secondary">
                    {summary && !summary.ready_data_available
                        ? 'Ready time appears once the issue events table on this GitHub source is synced.'
                        : 'No merged pull requests with a known ready time in the window.'}
                </div>
            )}
        </LemonCard>
    )
}
