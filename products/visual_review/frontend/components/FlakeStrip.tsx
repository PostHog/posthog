import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

interface FlakeStripProps {
    /** Runs per day that failed the gate, oldest first. The backend always sends a dense series. */
    dailyHardCounts: number[]
    /** Runs per day a toleration absorbed, oldest first. Same length as the hard series. */
    dailySoftCounts: number[]
    /**
     * Position of the baseline move inside the series, or null when it moved before the
     * window opened. Days before it are drawn faint: they describe a version of the
     * snapshot that is no longer what a run compares against.
     */
    baselineMovedDayIndex: number | null
}

// Every day with activity gets the same full-strength tick. A tick is 3px wide,
// so dimming quiet days to encode magnitude made the most common case the
// hardest to see. Magnitude is already in the rate beside the strip; the strip
// only has to answer when, and which of the two rows it happened in.
function tickClassName(count: number, { isFaint, isHard }: { isFaint: boolean; isHard: boolean }): string {
    if (count === 0) {
        return isFaint ? 'bg-border-light' : 'bg-border'
    }
    if (isFaint) {
        return 'bg-border-bold'
    }
    return isHard ? 'bg-danger' : 'bg-muted'
}

/**
 * Day-by-day view of when a snapshot rendered something other than its baseline.
 *
 * Two rows rather than one, because the same total means opposite things
 * depending on which row it lands in: a full bottom row is noise the toleration
 * cache is absorbing, and a full top row is a story blocking merges every day.
 * A bare count cannot separate a burst from a chronic flake either, which is
 * what the day axis is for.
 */
export function FlakeStrip({ dailyHardCounts, dailySoftCounts, baselineMovedDayIndex }: FlakeStripProps): JSX.Element {
    // Defaulted because a rolling deploy can hand this component a response from
    // a pod that predates these fields, and a bare reduce would take the whole
    // table down rather than one strip.
    const hard = dailyHardCounts ?? []
    const soft = dailySoftCounts ?? []
    const hardTotal = hard.reduce((sum, count) => sum + count, 0)
    const softTotal = soft.reduce((sum, count) => sum + count, 0)
    const windowStart = dayjs().subtract(Math.max(hard.length, 1) - 1, 'day')
    const summary =
        hardTotal === 0 && softTotal === 0
            ? `No difference from the baseline in the last ${hard.length} days`
            : `${hardTotal} failing and ${softTotal} absorbed in the last ${hard.length} days, since ${windowStart.format('MMM D')}`

    const rows: Array<{ counts: number[]; isHard: boolean }> = [
        { counts: hard, isHard: true },
        { counts: soft, isHard: false },
    ]

    return (
        <Tooltip
            title={
                <>
                    <div>{summary}</div>
                    <div className="text-xs">Top row failed the gate, bottom row was absorbed</div>
                    {baselineMovedDayIndex !== null && (
                        <div className="text-xs">Faint days are from before the baseline moved</div>
                    )}
                </>
            }
        >
            <div className="flex flex-col gap-px" aria-label={summary}>
                {rows.map((row) => (
                    <div key={row.isHard ? 'hard' : 'soft'} className="flex gap-px items-stretch h-1.5">
                        {row.counts.map((count, index) => (
                            <div
                                key={index}
                                className={`w-[3px] ${tickClassName(count, {
                                    isFaint: baselineMovedDayIndex !== null && index < baselineMovedDayIndex,
                                    isHard: row.isHard,
                                })}`}
                            />
                        ))}
                    </div>
                ))}
            </div>
        </Tooltip>
    )
}
