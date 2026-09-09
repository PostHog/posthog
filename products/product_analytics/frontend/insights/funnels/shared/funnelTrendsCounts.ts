import { humanFriendlyNumber } from 'lib/utils/numbers'

/** Per-period conversion counts that a funnel trends series carries next to its rates. The runner
 *  returns one entry per period, index-aligned with the series `data`. The base FunnelStep types
 *  do not declare these fields because only the trends viz has them. */
export interface FunnelTrendsCounts {
    /** People who entered the funnel in each period. This is the denominator of the period's rate. */
    reached_from_step_count?: number[]
    /** People who went on to convert in each period. This is the numerator of the period's rate. */
    reached_to_step_count?: number[]
}

/** Formats one period's conversion as `converted/entered`, so a rate can be read against the
 *  number of people it came from. Returns null when the series carries no counts for the period,
 *  which is how a result that the query cache filled before the runner returned counts looks. */
export function formatFunnelTrendsCounts(series: FunnelTrendsCounts, periodIndex: number): string | null {
    const converted = series.reached_to_step_count?.[periodIndex]
    const entered = series.reached_from_step_count?.[periodIndex]
    if (converted == null || entered == null) {
        return null
    }
    return `${humanFriendlyNumber(converted)}/${humanFriendlyNumber(entered)}`
}
