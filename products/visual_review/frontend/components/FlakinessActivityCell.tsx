import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { FlakinessEntryApi } from '../generated/api.schemas'
import { FlakeStrip } from './FlakeStrip'

function formatRate(rate: number): string {
    // Sub-percent rates are the difference between "failed once this month" and
    // "never failed", so they must not both round to 0%.
    if (rate > 0 && rate < 0.01) {
        return '<1%'
    }
    return `${Math.round(rate * 100)}%`
}

function formatBaselineAge(baselineAgeDays: number | null | undefined): string {
    if (baselineAgeDays === null || baselineAgeDays === undefined) {
        return 'baseline never moved'
    }
    return `baseline ${baselineAgeDays}d old`
}

/**
 * How often this snapshot rendered something other than its baseline, and when.
 *
 * Leads with the failing rate because that is the one that stopped somebody
 * merging. The absorbed rate sits under it as context: the same snapshot can be
 * absorbed on every single run and still never have blocked anyone.
 */
export function ActivityCell({ entry }: { entry: FlakinessEntryApi }): JSX.Element {
    const failing = entry.hard_count > 0
    return (
        <div className="flex flex-col gap-1 items-end">
            <Tooltip
                title={
                    failing
                        ? `Failed the gate on ${entry.hard_count} of the last ${entry.window_runs} runs`
                        : `Never failed the gate in the last ${entry.window_runs} runs`
                }
            >
                <span
                    className={`font-mono font-semibold tabular-nums ${failing ? 'text-danger' : 'text-muted'}`}
                    data-attr="visual-review-flakiness-hard-rate"
                >
                    {formatRate(entry.hard_rate)}
                </span>
            </Tooltip>
            <FlakeStrip
                dailyHardCounts={entry.daily_hard_counts}
                dailySoftCounts={entry.daily_soft_counts}
                baselineMovedDayIndex={entry.baseline_moved_day_index ?? null}
            />
            <span className="text-[11px] text-muted font-mono">
                {formatRate(entry.soft_rate)} absorbed · {formatBaselineAge(entry.baseline_age_days)}
            </span>
        </div>
    )
}
