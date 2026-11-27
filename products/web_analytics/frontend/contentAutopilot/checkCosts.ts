import type { CheckFrequencyEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

export interface CheckCost {
    median: number
    p90: number | null
}

// Per-check costs measured in production: the gateway's $ai_total_cost_usd per check, US, the 7 days to 2026-11-25.
// Estimates: a check costs more when the answer is long or the engine searches more. Engines without a figure here
// show as not priced.
export const CHECK_COSTS: Record<string, CheckCost> = {
    'claude-web-search': { median: 0.083, p90: 0.089 },
    'openai-web-search': { median: 0.139, p90: 0.226 },
    'exa-answer': { median: 0.005, p90: null },
}

const RUNS_PER_MONTH: Record<CheckFrequencyEnumApi, number> = { daily: 30, every_3_days: 10, weekly: 52 / 12 }

export interface CostRange {
    low: number
    high: number
}

export interface EngineCost {
    engine: string
    frequency: CheckFrequencyEnumApi
    checks: number
    perRun: CostRange | null
}

export interface CostEstimate {
    checksPerRun: number
    engines: EngineCost[]
    perRun: CostRange
    perMonth: CostRange
    unpriced: string[]
}

export const estimateCost = (
    prompts: number,
    engines: { engine: string; frequency: CheckFrequencyEnumApi }[],
    costs: Record<string, CheckCost> = CHECK_COSTS
): CostEstimate => {
    const rows = engines.map(({ engine, frequency }): EngineCost => {
        const cost = costs[engine]
        return {
            engine,
            frequency,
            checks: prompts,
            perRun: cost ? { low: prompts * cost.median, high: prompts * (cost.p90 ?? cost.median) } : null,
        }
    })
    const sum = (pick: (row: EngineCost) => number): number =>
        rows.reduce((total, row) => (row.perRun ? total + pick(row) : total), 0)
    return {
        checksPerRun: prompts * engines.length,
        engines: rows,
        perRun: { low: sum((row) => row.perRun!.low), high: sum((row) => row.perRun!.high) },
        perMonth: {
            low: sum((row) => row.perRun!.low * RUNS_PER_MONTH[row.frequency]),
            high: sum((row) => row.perRun!.high * RUNS_PER_MONTH[row.frequency]),
        },
        unpriced: rows.filter((row) => !row.perRun).map((row) => row.engine),
    }
}
