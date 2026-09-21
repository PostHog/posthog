// Ready for review to merged, split at the first approval. Medians of the two legs do not add up to
// the median of the whole, so the bar length is the whole median and the split is the share of summed
// hours on each side of the approval. The leg medians sit under the bars as separate numbers.

import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { compactAgeLabel, percent } from '../lib/format'
import { ReadyToMergeRow } from '../lib/readyToMergeRows'
import { ComparisonBarRow } from './ComparisonBarRow'

const BEFORE_APPROVAL_COLOR = 'var(--data-color-3)'
const AFTER_APPROVAL_COLOR = 'var(--data-color-1)'

function ApprovalSplit({ beforeShare }: { beforeShare: number | null }): JSX.Element {
    // A plain data color would read as one side of the approval split, so an unsplit bar stays grey.
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

function baselineText(rows: ReadyToMergeRow[], seconds: (row: ReadyToMergeRow) => number | null): string {
    return rows
        .filter((row) => seconds(row) != null)
        .map((row) => `${row.shortLabel} ${compactAgeLabel(seconds(row))}`)
        .join(' · ')
}

function LegRow({
    color,
    label,
    value,
    baselines,
}: {
    color: string
    label: string
    value: number | null
    baselines: string
}): JSX.Element {
    return (
        <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,auto)] items-baseline gap-2 border-t border-primary py-1 text-xs text-secondary">
            <span className="flex min-w-0 items-center gap-1.5">
                <span className="size-2 shrink-0 rounded-sm" style={{ backgroundColor: color }} />
                <span className="truncate">{label}</span>
            </span>
            <span className="font-semibold tabular-nums text-primary">{compactAgeLabel(value)}</span>
            <span className="truncate text-right tabular-nums text-tertiary">{baselines}</span>
        </div>
    )
}

export function ReadyToMergeCard({
    rows,
    reviewsSynced,
    loading,
    emptyText,
    title = 'Ready for review to merged',
    tooltip = 'Median calendar time from the last ready for review to the merge, over pull requests merged in the window. The bar length is that median. Its split is the share of all those hours spent before and after the first approval, so long pull requests weigh more. The two medians below are separate medians and do not add up to the total.',
    footnote,
    dataAttr = 'engineering-analytics-delivery-ready',
}: {
    /** The row being compared first, then its baselines, drawn muted. */
    rows: ReadyToMergeRow[]
    reviewsSynced: boolean
    loading: boolean
    emptyText: string
    title?: string
    tooltip?: string
    footnote?: string | null
    dataAttr?: string
}): JSX.Element {
    const [focus, ...baselines] = rows
    const shown = rows.filter((row): row is ReadyToMergeRow & { seconds: number } => row.seconds != null)
    const max = Math.max(...shown.flatMap((row) => [row.seconds, row.p90Seconds ?? 0]))

    return (
        <LemonCard hoverEffect={false} className="flex h-full flex-col p-4" data-attr={dataAttr}>
            <h3 className="mb-1 text-xs font-semibold text-secondary">
                <Tooltip title={tooltip}>
                    <span className="cursor-default">{title}</span>
                </Tooltip>
            </h3>
            {loading ? (
                <LemonSkeleton className="h-24 w-full" />
            ) : focus?.seconds != null ? (
                <>
                    <div className="mb-3 flex flex-wrap items-baseline gap-2">
                        <span className="text-2xl font-semibold leading-none tabular-nums">
                            {compactAgeLabel(focus.seconds)}
                        </span>
                        <span className="text-xs tabular-nums text-tertiary">
                            {baselineText(baselines, (row) => row.seconds)}
                        </span>
                    </div>
                    <div className="flex flex-col gap-1.5">
                        {shown.map((row, index) => (
                            <ComparisonBarRow
                                // A handle can equal a team slug, so the label alone is no unique key.
                                key={`${index}:${row.label}`}
                                label={row.label}
                                labelTooltip={row.labelTooltip}
                                value={row.seconds}
                                max={max}
                                formatValue={compactAgeLabel}
                                muted={row !== focus}
                                marker={
                                    row.p90Seconds != null ? { value: row.p90Seconds, label: '90th percentile' } : null
                                }
                            >
                                <ApprovalSplit beforeShare={reviewsSynced ? row.beforeShare : null} />
                            </ComparisonBarRow>
                        ))}
                    </div>
                    {reviewsSynced ? (
                        <div className="mt-3 flex flex-col">
                            <LegRow
                                color={BEFORE_APPROVAL_COLOR}
                                label="Ready to first approval"
                                value={focus.beforeApprovalSeconds}
                                baselines={baselineText(baselines, (row) => row.beforeApprovalSeconds)}
                            />
                            <LegRow
                                color={AFTER_APPROVAL_COLOR}
                                label="First approval to merged"
                                value={focus.afterApprovalSeconds}
                                baselines={baselineText(baselines, (row) => row.afterApprovalSeconds)}
                            />
                        </div>
                    ) : (
                        <div className="mt-2 text-[11px] text-tertiary">
                            Sync the reviews table on this GitHub source to split the wait at the first approval.
                        </div>
                    )}
                    {footnote && <div className="mt-2 text-[11px] text-tertiary">{footnote}</div>}
                </>
            ) : (
                <div className="flex h-20 items-center text-xs text-secondary">{emptyText}</div>
            )}
        </LemonCard>
    )
}
