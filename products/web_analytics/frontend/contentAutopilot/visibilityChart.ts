import type { AEOPromptDailyEngineStatsApi } from 'products/web_analytics/frontend/generated/api.schemas'

import type { PromptOutcomeMetric, PromptVisibilityMetric } from './promptReport'
import { engineColor, engineLabel, sortEngines } from './utils'

export interface EngineVisibilitySeries {
    engine: string
    label: string
    color: string | undefined
    data: number[]
}

export interface EngineVisibilityChart {
    labels: string[]
    series: EngineVisibilitySeries[]
}

const dayValue = (row: AEOPromptDailyEngineStatsApi | undefined, metric: PromptVisibilityMetric): number => {
    if (!row) {
        return NaN
    }
    if (metric === 'position') {
        return row.avg_position ?? NaN
    }
    const answered = row.checks - row.failed
    return answered > 0 ? (metric === 'cited' ? row.cited : row.mentioned) / answered : NaN
}

/** The positions of the days to draw: from the first day where some series has a value to the end of the range.
 *  The axis starts at the first day of data, so one day of data is one date. A later day without data stays on the
 *  axis as a gap, where the line breaks, and is never drawn as 0. */
export const daysFromFirstData = (dayCount: number, series: number[][]): number[] => {
    const first = Array.from({ length: dayCount }, (_, index) => index).find((index) =>
        series.some((data) => Number.isFinite(data[index]))
    )
    return first === undefined ? [] : Array.from({ length: dayCount - first }, (_, offset) => first + offset)
}

/** One line per engine from the first day in `dates` with data. A day an engine didn't answer is NaN, so its line
 *  breaks there instead of dropping to 0. */
export function engineVisibilityChart(
    daily: AEOPromptDailyEngineStatsApi[],
    dates: string[],
    metric: PromptVisibilityMetric
): EngineVisibilityChart {
    const byDay = new Map(daily.map((row) => [`${row.engine}|${row.date}`, row]))
    const series = sortEngines(daily.map((row) => row.engine)).map((engine) => ({
        engine,
        label: engineLabel(engine),
        color: engineColor(engine),
        data: dates.map((date) => dayValue(byDay.get(`${engine}|${date}`), metric)),
    }))
    const days = daysFromFirstData(
        dates.length,
        series.map(({ data }) => data)
    )
    return {
        labels: days.map((index) => dates[index]),
        series: series.map((line) => ({ ...line, data: days.map((index) => line.data[index]) })),
    }
}

/** A dot on every day of a visibility line, so a range with one day of data shows one dot per series and a few
 *  days read as points rather than a line too short to see. */
export const DAY_POINTS = { radius: 3 }

export interface AnswerOutcomeChart {
    labels: string[]
    yes: number[]
    no: number[]
}

/** Answers per day across every engine, split into the ones that met `metric` and the ones that didn't. Failed checks
 *  have no answer, so they are in neither count. */
export function answerOutcomeChart(
    daily: AEOPromptDailyEngineStatsApi[],
    dates: string[],
    metric: PromptOutcomeMetric
): AnswerOutcomeChart {
    const yes = new Map<string, number>()
    const no = new Map<string, number>()
    for (const row of daily) {
        const met = metric === 'cited' ? row.cited : row.mentioned
        yes.set(row.date, (yes.get(row.date) ?? 0) + met)
        no.set(row.date, (no.get(row.date) ?? 0) + row.checks - row.failed - met)
    }
    // The axis starts at the first day with answers, the same as on the visibility charts.
    const first = dates.findIndex((date) => (yes.get(date) ?? 0) + (no.get(date) ?? 0) > 0)
    const days = first === -1 ? [] : dates.slice(first)
    return {
        labels: days,
        yes: days.map((date) => yes.get(date) ?? 0),
        no: days.map((date) => no.get(date) ?? 0),
    }
}
