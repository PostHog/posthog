import { MarketingAnalyticsRetentionSummaryRow } from '~/queries/schema/schema-general'

export type ReturnRow = MarketingAnalyticsRetentionSummaryRow & {
    comparison?: MarketingAnalyticsRetentionSummaryRow
}

/** Null when nobody has had the full window yet, which is not the same as nobody returning. */
export function returnRate(row: MarketingAnalyticsRetentionSummaryRow | undefined, days: 7 | 30): number | null {
    const eligible = days === 7 ? row?.eligible7d : row?.eligible30d
    const returned = days === 7 ? row?.returned7d : row?.returned30d
    return eligible ? (returned ?? 0) / eligible : null
}

/** The response interleaves both periods, tagged by `previous`. */
export function pairWithPrevious(rows: MarketingAnalyticsRetentionSummaryRow[]): ReturnRow[] {
    const previous = new Map(rows.filter((row) => row.previous).map((row) => [row.breakdownValue, row]))
    return rows.filter((row) => !row.previous).map((row) => ({ ...row, comparison: previous.get(row.breakdownValue) }))
}
