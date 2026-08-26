import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

interface VariantStripProps {
    /** Variants recorded per day, oldest first. The backend always sends a dense series. */
    dailyCounts: number[]
    /**
     * Position of the baseline move inside the series, or null when it moved before the
     * window opened. Days before it are drawn faint: their variants were recorded against
     * the old baseline hash and can never match again.
     */
    baselineMovedDayIndex: number | null
}

// Every day that recorded a variant gets the same full-strength tick. A tick is
// 3px wide, so dimming single-variant days to encode magnitude made the most
// common case the hardest to see. Magnitude is already in the count beside the
// strip; the strip only has to answer when.
function tickClassName(count: number, isBeforeBaselineMove: boolean): string {
    if (isBeforeBaselineMove) {
        return count > 0 ? 'bg-border-bold' : 'bg-border-light'
    }
    return count > 0 ? 'bg-danger' : 'bg-border'
}

/**
 * Day-by-day view of when a snapshot recorded new allowed variants.
 *
 * Exists because a bare count cannot separate a burst from a chronic flake: a
 * story that produced twenty variants in one week and then stopped is a change
 * that settled, and one that produces two a day forever is not.
 */
export function VariantStrip({ dailyCounts, baselineMovedDayIndex }: VariantStripProps): JSX.Element {
    const total = dailyCounts.reduce((sum, count) => sum + count, 0)
    const windowStart = dayjs().subtract(dailyCounts.length - 1, 'day')
    const summary =
        total === 0
            ? `No new variants in the last ${dailyCounts.length} days`
            : `${total} ${total === 1 ? 'variant' : 'variants'} in the last ${dailyCounts.length} days, since ${windowStart.format('MMM D')}`

    return (
        <Tooltip
            title={
                <>
                    <div>{summary}</div>
                    {baselineMovedDayIndex !== null && (
                        <div>Faint days are from before the baseline moved, so they no longer count</div>
                    )}
                </>
            }
        >
            <div className="flex gap-px items-stretch h-3" aria-label={summary}>
                {dailyCounts.map((count, index) => (
                    <div
                        key={index}
                        className={`w-[3px] ${tickClassName(
                            count,
                            baselineMovedDayIndex !== null && index < baselineMovedDayIndex
                        )}`}
                    />
                ))}
            </div>
        </Tooltip>
    )
}
