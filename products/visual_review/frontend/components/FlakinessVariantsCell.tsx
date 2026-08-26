import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { FlakinessEntryApi } from '../generated/api.schemas'
import { VariantStrip } from './VariantStrip'

// Sub-pixel jitter and a small real change both round to tiny percentages, so
// two decimals is the smallest precision that keeps them apart.
function formatJitter(avgDiffPercentage: number | null | undefined): string | null {
    if (avgDiffPercentage === null || avgDiffPercentage === undefined) {
        return null
    }
    return `${avgDiffPercentage.toFixed(2)}% avg`
}

function formatBaselineAge(baselineAgeDays: number | null | undefined): string {
    if (baselineAgeDays === null || baselineAgeDays === undefined) {
        return 'baseline never moved'
    }
    return `baseline ${baselineAgeDays}d old`
}

export function VariantsCell({ entry }: { entry: FlakinessEntryApi }): JSX.Element {
    const jitter = formatJitter(entry.avg_diff_percentage)
    return (
        <div className="flex flex-col gap-1 items-end">
            <Tooltip
                title={`This snapshot is currently allowed to produce ${entry.variant_count} different ${
                    entry.variant_count === 1 ? 'image' : 'images'
                } and still pass`}
            >
                <span className="font-mono font-semibold tabular-nums">{entry.variant_count.toLocaleString()}</span>
            </Tooltip>
            <VariantStrip
                dailyCounts={entry.daily_variant_counts}
                baselineMovedDayIndex={entry.baseline_moved_day_index ?? null}
            />
            <span className="text-[11px] text-muted font-mono">
                {jitter ? `${jitter} · ` : ''}
                {formatBaselineAge(entry.baseline_age_days)}
            </span>
        </div>
    )
}
