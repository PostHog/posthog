// Turns the cost endpoint's facts — spend, runs, priced runs, reports touched — into the three
// rates the roster and the scout page show. The API stays a fact table on purpose, so the
// definitions of cost per day, per run, and per report live here and nowhere else.

import type { ScoutCostsApi } from 'products/signals/frontend/generated/api.schemas'

import { formatRunCost } from './scoutRunsWindow'

export interface ScoutCostRollup {
    /** Spend attributed to the scout's runs in the window. */
    spendUsd: number
    windowDays: number
    /** Spend over the whole window, whatever part of it the scout was enabled for. */
    perDay: number
    /** Spend over the runs that had spend attributed, not over every run the scout started. */
    perRun: number
    /** Null when the scout filed or added to nothing, so there is no report to price. */
    perReport: number | null
    runCount: number
    pricedRunCount: number
    reportsTouched: number
}

/**
 * A rollup per scout that spent something in the window. A scout with no priced run gets no entry:
 * its spend is unknown rather than zero, the same way the per-run tooltip omits a cost it cannot
 * attribute, so every surface omits the line instead of printing `$0.00`.
 */
export function computeScoutCostRollups(costs: ScoutCostsApi | null): Map<string, ScoutCostRollup> {
    const rollups = new Map<string, ScoutCostRollup>()
    if (!costs?.available) {
        return rollups
    }
    for (const scout of costs.scouts) {
        if (scout.priced_run_count === 0) {
            continue
        }
        rollups.set(scout.skill_name, {
            spendUsd: scout.spend_usd,
            windowDays: costs.window_days,
            perDay: scout.spend_usd / costs.window_days,
            perRun: scout.spend_usd / scout.priced_run_count,
            perReport: scout.reports_touched > 0 ? scout.spend_usd / scout.reports_touched : null,
            runCount: scout.run_count,
            pricedRunCount: scout.priced_run_count,
            reportsTouched: scout.reports_touched,
        })
    }
    return rollups
}

/** A rate with its unit, e.g. "$0.24/day". Sub-cent rates keep four decimals, as run costs do. */
export function formatCostRate(value: number, unit: 'day' | 'run' | 'report'): string {
    return `${formatRunCost(value)}/${unit}`
}

/** The three rates as one line, e.g. "$0.24/day · $0.12/run · $0.15/report". */
export function scoutCostLineParts(rollup: ScoutCostRollup): string[] {
    return [
        formatCostRate(rollup.perDay, 'day'),
        formatCostRate(rollup.perRun, 'run'),
        // A scout that produced nothing still spent: say so, rather than pricing zero reports.
        rollup.perReport === null ? 'no reports' : formatCostRate(rollup.perReport, 'report'),
    ]
}

/** Window the numbers describe, for the labels and tooltips that name it. */
export function scoutCostWindowLabel(windowDays: number): string {
    return `last ${windowDays} days`
}
