import { dayjs } from 'lib/dayjs'

import type {
    AEOPromptDailyEngineStatsApi,
    AEOPromptStatsApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

export type PromptVisibilityMetric = 'cited' | 'mentioned'

export interface PromptRateKpi {
    /** Pooled rate over the window: all answers that qualify over all answers. */
    average: number | null
    /** Rate on the latest day of the window that had an answer. */
    latest: number | null
    latestDate: string | null
    /** `latest - average`, in rate units (0.12 is 12 percentage points). */
    delta: number | null
}

export interface PromptReportKpis {
    answers: number
    days: number
    visibility: PromptRateKpi
    citation: PromptRateKpi
}

export interface PromptConsensusCell {
    domain: string
    checksCiting: number
    /** Share of the engine's answers that cited the domain. Null when the engine answered nothing. */
    share: number | null
}

export interface PromptConsensusMatrix {
    domains: string[]
    rows: { engine: string; checks: number; cells: PromptConsensusCell[] }[]
}

export interface PromptSentimentCounts {
    positive: number
    neutral: number
    negative: number
}

export interface PromptSentimentSummary extends PromptSentimentCounts {
    scored: number
    unscored: number
    byEngine: ({ engine: string; scored: number } & PromptSentimentCounts)[]
}

interface DailyTotals {
    checks: number
    cited: number
    mentioned: number
    failed: number
}

/** Every day of the stats window as YYYY-MM-DD, oldest first. */
export const statsWindowDates = (stats: Pick<AEOPromptStatsApi, 'daily_from' | 'daily_to'>): string[] => {
    const dates: string[] = []
    for (let day = dayjs(stats.daily_from); !day.isAfter(dayjs(stats.daily_to), 'day'); day = day.add(1, 'day')) {
        dates.push(day.format('YYYY-MM-DD'))
    }
    return dates
}

const sumDaily = (rows: AEOPromptDailyEngineStatsApi[]): DailyTotals =>
    rows.reduce(
        (totals, row) => ({
            checks: totals.checks + row.checks,
            cited: totals.cited + row.cited,
            mentioned: totals.mentioned + row.mentioned,
            failed: totals.failed + row.failed,
        }),
        { checks: 0, cited: 0, mentioned: 0, failed: 0 }
    )

const rate = (part: number, whole: number): number | null => (whole > 0 ? part / whole : null)

const rateKpi = (
    byDay: { date: string; checks: number; failed: number; count: number }[],
    totals: { checks: number; failed: number; count: number }
): PromptRateKpi => {
    const average = rate(totals.count, totals.checks - totals.failed)
    const latestDay = [...byDay].reverse().find((day) => day.checks - day.failed > 0) ?? null
    const latest = latestDay ? rate(latestDay.count, latestDay.checks - latestDay.failed) : null
    return {
        average,
        latest,
        latestDate: latestDay?.date ?? null,
        delta: average !== null && latest !== null ? latest - average : null,
    }
}

/** Window-wide visibility and citation rates, with the latest day and how far it sits from the average. */
export const promptReportKpis = (stats: AEOPromptStatsApi): PromptReportKpis => {
    const dates = statsWindowDates(stats)
    const byDate = new Map<string, AEOPromptDailyEngineStatsApi[]>()
    for (const row of stats.daily) {
        byDate.set(row.date, [...(byDate.get(row.date) ?? []), row])
    }
    const days = dates.map((date) => ({ date, ...sumDaily(byDate.get(date) ?? []) }))
    const totals = sumDaily(stats.daily)
    return {
        answers: totals.checks - totals.failed,
        days: dates.length,
        visibility: rateKpi(
            days.map((day) => ({ ...day, count: day.mentioned })),
            { ...totals, count: totals.mentioned }
        ),
        citation: rateKpi(
            days.map((day) => ({ ...day, count: day.cited })),
            { ...totals, count: totals.cited }
        ),
    }
}

/** Engines as rows, the most cited domains as columns, each cell the share of the engine's answers citing it. */
export const promptConsensusMatrix = (stats: AEOPromptStatsApi, engines: string[]): PromptConsensusMatrix => {
    const domains = [...new Set(stats.consensus.map((row) => row.domain))]
    const byKey = new Map(stats.consensus.map((row) => [`${row.engine}|${row.domain}`, row]))
    return {
        domains,
        rows: engines
            .map((engine) => {
                const checks = stats.consensus.find((row) => row.engine === engine)?.checks ?? 0
                return {
                    engine,
                    checks,
                    cells: domains.map((domain) => {
                        const checksCiting = byKey.get(`${engine}|${domain}`)?.checks_citing ?? 0
                        return { domain, checksCiting, share: rate(checksCiting, checks) }
                    }),
                }
            })
            .filter((row) => row.checks > 0),
    }
}

/** Sentiment counts across engines, plus one row per engine that has at least one scored answer. */
export const promptSentimentSummary = (stats: AEOPromptStatsApi, engines: string[]): PromptSentimentSummary => {
    const byEngine = engines.flatMap((engine) => {
        const row = stats.sentiment.find((item) => item.engine === engine)
        if (!row) {
            return []
        }
        const scored = row.positive + row.neutral + row.negative
        return scored > 0
            ? [{ engine, scored, positive: row.positive, neutral: row.neutral, negative: row.negative }]
            : []
    })
    const totals = stats.sentiment.reduce(
        (sum, row) => ({
            positive: sum.positive + row.positive,
            neutral: sum.neutral + row.neutral,
            negative: sum.negative + row.negative,
            unscored: sum.unscored + row.unscored,
        }),
        { positive: 0, neutral: 0, negative: 0, unscored: 0 }
    )
    return { ...totals, scored: totals.positive + totals.neutral + totals.negative, byEngine }
}
