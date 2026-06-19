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
}
