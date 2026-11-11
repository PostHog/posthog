import type { AEOPromptDailyEngineStatsApi } from 'products/web_analytics/frontend/generated/api.schemas'

import type { PromptVisibilityMetric } from './promptReport'
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

/** One line per engine over every day in `dates`. A day the engine didn't answer is NaN, so the line breaks there
 *  instead of dropping to 0. */
export function engineVisibilityChart(
    daily: AEOPromptDailyEngineStatsApi[],
    dates: string[],
    metric: PromptVisibilityMetric
): EngineVisibilityChart {
    const byDay = new Map(daily.map((row) => [`${row.engine}|${row.date}`, row]))
    return {
        labels: dates,
        series: sortEngines(daily.map((row) => row.engine)).map((engine) => ({
            engine,
            label: engineLabel(engine),
            color: engineColor(engine),
            data: dates.map((date) => dayValue(byDay.get(`${engine}|${date}`), metric)),
        })),
    }
}
