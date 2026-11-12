import { dayjs } from 'lib/dayjs'
import { percentage } from 'lib/utils/numbers'

import type {
    AEOPromptDailyEngineStatsApi,
    AEOPromptStatsApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { isNoSearchEngine } from './utils'

export type PromptVisibilityMetric = 'cited' | 'mentioned' | 'position'
/** The metrics a single answer can only pass or fail, so the prompt page can count yes and no answers. */
export type PromptOutcomeMetric = Exclude<PromptVisibilityMetric, 'position'>

export interface PromptRateKpi {
    /** Pooled rate over the window: all answers that qualify over all answers. */
    average: number | null
    /** Rate on the latest day of the window that had an answer. */
    latest: number | null
    latestDate: string | null
    /** `latest - average`, in rate units (0.12 is 12 percentage points). */
    delta: number | null
}

/** The change shown next to a KPI value, already worded for the card. */
export interface KpiDelta {
    label: string
    direction: 'up' | 'down' | 'flat'
    tooltip: string
}

export interface KpiCardContent {
    value: string
    note: string
    delta: KpiDelta | null
}

export interface PromptPositionKpi {
    /** Mean rank of your first link among the sources, over the cited answers in the window. Lower is better. */
    average: number | null
    latest: number | null
    latestDate: string | null
}

export interface PromptReportKpis {
    answers: number
    days: number
    visibility: PromptRateKpi
    citation: PromptRateKpi
    position: PromptPositionKpi
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

/** `delta` is in rate units (0.12 is 12 percentage points), shown as whole points. */
export const pointsDelta = (delta: number, tooltip: string): KpiDelta => {
    const points = Math.round(delta * 100)
    return {
        label: points === 0 ? 'No change' : `${points > 0 ? '+' : ''}${points} pts`,
        direction: points === 0 ? 'flat' : points > 0 ? 'up' : 'down',
        tooltip,
    }
}

export const POSITION_DESCRIPTION =
    'Where your site sits among the sources of an answer that cites it. #1 is the first source listed. Lower is better.'

export const positionLabel = (position: number): string => `#${Math.round(position * 10) / 10}`

/** A rank is better when it is lower, so a drop in the number reads as a gain. */
export const positionDelta = (change: number, tooltip: string): KpiDelta => {
    const rounded = Math.round(change * 10) / 10
    return {
        label: rounded === 0 ? 'No change' : `${Math.abs(rounded)} ${rounded < 0 ? 'better' : 'worse'}`,
        direction: rounded === 0 ? 'flat' : rounded < 0 ? 'up' : 'down',
        tooltip,
    }
}

/** Mean of per-row averages, weighted by the cited answers each one covers. */
export const pooledPosition = (rows: { cited: number; avg_position?: number | null }[]): number | null => {
    let cited = 0
    let total = 0
    for (const row of rows) {
        if (row.avg_position !== null && row.avg_position !== undefined && row.cited > 0) {
            cited += row.cited
            total += row.avg_position * row.cited
        }
    }
    return cited > 0 ? total / cited : null
}

const positionKpi = (
    dates: string[],
    byDate: Map<string, AEOPromptDailyEngineStatsApi[]>,
    all: AEOPromptDailyEngineStatsApi[]
): PromptPositionKpi => {
    const latestDate = [...dates].reverse().find((date) => pooledPosition(byDate.get(date) ?? []) !== null) ?? null
    return {
        average: pooledPosition(all),
        latest: latestDate ? pooledPosition(byDate.get(latestDate) ?? []) : null,
        latestDate,
    }
}

export const positionKpiCard = (kpi: PromptPositionKpi): KpiCardContent => ({
    value: kpi.average === null ? 'Not cited' : positionLabel(kpi.average),
    note:
        kpi.average === null
            ? 'No cited answers in the last 30 days'
            : kpi.latest === null || !kpi.latestDate
              ? 'Average over the last 30 days'
              : `Average over the last 30 days. On ${dayjs(kpi.latestDate).format('MMM D')}: ${positionLabel(kpi.latest)}`,
    delta:
        kpi.average === null || kpi.latest === null
            ? null
            : positionDelta(kpi.latest - kpi.average, 'The latest day against the 30-day average. Lower is better'),
})

export const countDelta = (change: number, tooltip: string): KpiDelta => ({
    label: change === 0 ? 'No change' : `${change > 0 ? '+' : ''}${change}`,
    direction: change === 0 ? 'flat' : change > 0 ? 'up' : 'down',
    tooltip,
})

export const rateKpiCard = (kpi: PromptRateKpi): KpiCardContent => ({
    value: kpi.average === null ? 'No answers' : percentage(kpi.average, 0),
    note:
        kpi.latest === null || !kpi.latestDate
            ? 'Average over the last 30 days'
            : `Average over the last 30 days. On ${dayjs(kpi.latestDate).format('MMM D')}: ${percentage(kpi.latest, 0)}`,
    delta:
        kpi.delta === null
            ? null
            : pointsDelta(kpi.delta, 'The latest day against the 30-day average, in percentage points'),
})

/** Window-wide visibility and citation rates, with the latest day and how far it sits from the average.
 *  They read web-search answers only, as the overview does: a no-search engine never cites, so it keeps its own row. */
export const promptReportKpis = (stats: AEOPromptStatsApi): PromptReportKpis => {
    const dates = statsWindowDates(stats)
    const daily = stats.daily.filter((row) => !isNoSearchEngine(row.engine))
    const byDate = new Map<string, AEOPromptDailyEngineStatsApi[]>()
    for (const row of daily) {
        byDate.set(row.date, [...(byDate.get(row.date) ?? []), row])
    }
    const days = dates.map((date) => ({ date, ...sumDaily(byDate.get(date) ?? []) }))
    const totals = sumDaily(daily)
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
        position: positionKpi(dates, byDate, daily),
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
