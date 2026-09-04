import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { FlakinessEntryApi } from '../generated/api.schemas'

// Sub-pixel jitter and a small real change both round to tiny percentages, so
// two decimals is the smallest precision that keeps them apart.
function formatDiff(diffPercentage: number): string {
    return `${diffPercentage.toFixed(2)}%`
}

/**
 * How much of the diff threshold this snapshot still has to spare.
 *
 * A snapshot passes only while its diff stays under the threshold, so a story
 * absorbed at 0.01% and one absorbed just under the line are not equally safe,
 * even though both pass today and both show the same count of variants.
 */
export function MarginCell({ entry }: { entry: FlakinessEntryApi }): JSX.Element {
    const variants = `${entry.variant_count} ${entry.variant_count === 1 ? 'variant' : 'variants'}`
    if (entry.headroom === null || entry.headroom === undefined) {
        return (
            <div className="flex flex-col gap-1 items-end">
                <span className="text-muted">—</span>
                <span className="text-[11px] text-muted font-mono">{variants}</span>
            </div>
        )
    }

    const tight = entry.headroom < 0.2
    return (
        <div className="flex flex-col gap-1 items-end">
            <Tooltip
                title={
                    `Its worst absorbed run differed by ${formatDiff(entry.worst_soft_diff_percentage ?? 0)}, ` +
                    `leaving ${Math.round(entry.headroom * 100)}% of the threshold free. ` +
                    (tight
                        ? 'The next unrelated rendering change is likely to push it over.'
                        : 'It has room before it would start failing.')
                }
            >
                <span className={`font-mono font-semibold tabular-nums ${tight ? 'text-warning-dark' : 'text-muted'}`}>
                    {Math.round(entry.headroom * 100)}% left
                </span>
            </Tooltip>
            <span className="text-[11px] text-muted font-mono">
                {formatDiff(entry.worst_soft_diff_percentage ?? 0)} worst · {variants}
            </span>
        </div>
    )
}
