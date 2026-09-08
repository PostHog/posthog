import { humanFriendlyNumber } from 'lib/utils/numbers'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

export const FUNNEL_CONVERSION_SERIES_LABEL = 'Conversion'

export type FunnelSeriesMeta = {
    days?: string[]
    // Narrower than BreakdownKeyType — matches SeriesDatum so the tooltip adapter needs no cast.
    breakdown_value?: SeriesDatum['breakdown_value']
    // Present in compare-to-previous mode; lets the tooltip split current/previous into separate rows.
    compare_label?: SeriesDatum['compare_label']
    order: number
    label?: string | null
    reached_from_step_count?: number[]
    reached_to_step_count?: number[]
}

/** Conversion rate for one period, with the counts it came from when the response carries them.
 *  `groupTypeLabel` is the plural aggregation target, empty when the funnel aggregates by property. */
export function formatFunnelConversionValue(
    value: number,
    dataIndex: number,
    meta?: FunnelSeriesMeta,
    groupTypeLabel?: string
): string {
    const reachedFrom = meta?.reached_from_step_count?.[dataIndex]
    const reachedTo = meta?.reached_to_step_count?.[dataIndex]
    if (reachedFrom == null || reachedTo == null) {
        return `${value}%`
    }
    const target = groupTypeLabel ? ` ${groupTypeLabel}` : ''
    return `${humanFriendlyNumber(reachedTo)} of ${humanFriendlyNumber(reachedFrom)}${target} (${value}%)`
}
