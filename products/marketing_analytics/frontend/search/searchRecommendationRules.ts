import { MarketingAnalyticsSearchRow } from '~/queries/schema/schema-general'

export interface SearchRecommendation {
    row: MarketingAnalyticsSearchRow
    kind: 'spend_without_conversions' | 'higher_cpa' | 'lower_organic_ctr'
    current: number
    previous: number
}

export function searchRecommendations(
    rows: MarketingAnalyticsSearchRow[],
    goalId: string | null
): SearchRecommendation[] {
    return rows.flatMap((row): SearchRecommendation[] => {
        const previous = row.previous
        if (
            !previous ||
            ![row.clicks, row.impressions, previous.clicks, previous.impressions].every(
                (value) => Number.isFinite(value) && value >= 0
            )
        ) {
            return []
        }
        if (row.platform === 'GoogleSearchConsole') {
            const currentCtr = row.impressions > 0 ? row.clicks / row.impressions : 0
            const previousCtr = previous.impressions > 0 ? previous.clicks / previous.impressions : 0
            return row.impressions >= 1000 &&
                previous.impressions >= 1000 &&
                previous.clicks >= 30 &&
                currentCtr <= previousCtr * 0.7
                ? [{ row, kind: 'lower_organic_ctr', current: currentCtr, previous: previousCtr }]
                : []
        }
        if (
            !row.currency ||
            row.cost == null ||
            row.cost <= 0 ||
            previous.cost == null ||
            previous.cost <= 0 ||
            !Number.isFinite(row.cost) ||
            !Number.isFinite(previous.cost)
        ) {
            return []
        }
        const goal = goalId ? row.posthogConversions?.find((goal) => goal.id === goalId) : null
        const conversions = goalId ? goal?.conversions : row.conversions
        const previousConversions = goalId ? goal?.previousConversions : previous.conversions
        if (
            conversions == null ||
            previousConversions == null ||
            previousConversions < 5 ||
            conversions < 0 ||
            !Number.isFinite(conversions) ||
            !Number.isFinite(previousConversions)
        ) {
            return []
        }
        if (conversions === 0 && row.clicks >= 100) {
            return [{ row, kind: 'spend_without_conversions', current: 0, previous: previousConversions }]
        }
        if (conversions < 10 || previousConversions < 10) {
            return []
        }
        const currentCpa = row.cost / conversions
        const previousCpa = previous.cost / previousConversions
        return currentCpa >= previousCpa * 1.5
            ? [{ row, kind: 'higher_cpa', current: currentCpa, previous: previousCpa }]
            : []
    })
}
