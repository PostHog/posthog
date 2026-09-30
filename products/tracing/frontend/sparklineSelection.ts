// Pure mapping from a selection on the activity chart onto a date range. Kept out of the
// component so the bucket-edge convention is unit-testable on its own, like heatmapBrush.ts.

import { DateRange } from '~/queries/schema/schema-general'

/** How the user picked the range on the activity chart — reported with the filter-change event. */
export type TracingDateRangeSource = 'sparkline_drag' | 'sparkline_bar_click'

/**
 * Date range spanned by an inclusive run of sparkline buckets, or null when the run starts past
 * the rendered buckets.
 *
 * Buckets are anchored at their start, so the range ends at the START of the bucket after the
 * last selected one. The final bucket has no successor — fall back to the window's own end, the
 * same convention `heatmapBrushToFilters` uses, so selecting the last bar can't stretch an
 * absolute window forward to now.
 */
export function bucketRangeToDateRange(
    dates: string[],
    startIndex: number,
    endIndex: number,
    currentDateTo?: string | null
): DateRange | null {
    const dateFrom = dates[startIndex]
    if (!dateFrom) {
        return null
    }
    return { date_from: dateFrom, date_to: dates[endIndex + 1] ?? currentDateTo ?? null }
}
