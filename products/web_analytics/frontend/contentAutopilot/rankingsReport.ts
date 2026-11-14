import type { AEOPromptSetRankingsApi } from 'products/web_analytics/frontend/generated/api.schemas'

export interface RankingsChartSeries {
    domain: string
    label: string
    data: number[]
}

export interface RankingsChart {
    labels: string[]
    series: RankingsChartSeries[]
}

/** One line per brand over every day of the window, the project's own first. A day without answers is NaN, so the line breaks instead of dropping to 0. */
export function rankingsChart(rankings: AEOPromptSetRankingsApi): RankingsChart {
    const labels: string[] = []
    const day = new Date(`${rankings.window_from}T00:00:00Z`)
    const last = new Date(`${rankings.window_to}T00:00:00Z`)
    while (day <= last) {
        labels.push(day.toISOString().slice(0, 10))
        day.setUTCDate(day.getUTCDate() + 1)
    }
    const visibility = new Map(rankings.daily.map((row) => [`${row.domain}|${row.date}`, row.visibility]))
    return {
        labels,
        // The project's brand first, then competitors by domain, so a brand keeps its color between loads.
        series: [...rankings.brands]
            .sort((a, b) => Number(b.is_target) - Number(a.is_target) || a.domain.localeCompare(b.domain))
            .map((brand) => ({
                domain: brand.domain,
                label: brand.domain,
                data: labels.map((date) => visibility.get(`${brand.domain}|${date}`) ?? NaN),
            })),
    }
}

/** Change in visibility against the previous window, in percentage points. Null when either window had no answers. */
export function visibilityChange(visibility: number | null, previous: number | null): number | null {
    return visibility === null || previous === null ? null : Math.round((visibility - previous) * 1000) / 10
}
