import { humanFriendlyNumber } from 'lib/utils/numbers'

/** Per-period conversion counts a funnel trends series carries next to its rates, index-aligned with `data`. */
export interface FunnelTrendsCounts {
    /** People who entered the funnel in each period: the denominator of the period's rate. */
    reached_from_step_count?: number[]
    /** People who converted in each period: the numerator of the period's rate. */
    reached_to_step_count?: number[]
}

/** Returns null when the series has no counts for the period. A cached response can lack them. */
export function formatFunnelTrendsCounts(series: FunnelTrendsCounts, periodIndex: number): string | null {
    const converted = series.reached_to_step_count?.[periodIndex]
    const entered = series.reached_from_step_count?.[periodIndex]
    if (converted == null || entered == null) {
        return null
    }
    return `${humanFriendlyNumber(converted)}/${humanFriendlyNumber(entered)}`
}
