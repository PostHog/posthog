// Rolls a flat list of one workflow's runs up into the health facts the verdict header renders. Kept
// separate from the kea logic so both the workflow-runs page and (later) the PR page can derive the same
// summary, and so the math is unit-testable without a logic harness.

import { isDecisiveFailure, isPassingConclusion } from './lifecycle'

// The minimum a run needs to score its health. Both WorkflowRunRow and PrRunRow satisfy this.
export interface HealthRun {
    conclusion: string | null
    startedAt: string | null
    durationSeconds: number | null
    /** Re-run attempt (1 for the first); a 2nd+ attempt is a re-run. */
    runAttempt?: number | null
}

/** Billable minutes + estimated cost rolled up across the window; null fields when jobs aren't synced. */
export interface CostSummary {
    billableMinutes: number | null
    estimatedCostUsd: number | null
}

export type WorkflowState = 'healthy' | 'degraded' | 'failing' | 'unknown'

export interface HealthSummary {
    state: WorkflowState
    totalRuns: number
    completedRuns: number
    passedRuns: number
    failures: number
    running: number
    /** Runs that were a 2nd+ attempt — re-runs, a flakiness signal the chart doesn't show. */
    reruns: number
    /** Passes ÷ completed runs (null when nothing has settled). */
    passRate: number | null
    medianSeconds: number | null
    p95Seconds: number | null
    lastFailureAt: string | null
    latestConclusion: string | null
}

// At or above this decisive-failure rate a workflow whose latest run still passed reads as "degraded".
// Keyed off failures, not pass rate, so cancellations (neither pass nor failure) don't drag the verdict.
const DEGRADED_FAILURE_RATE = 0.1
// Below this success rate a currently-green workflow counts as flaky in the fleet rollup.
const FLAKY_SUCCESS_RATE = 0.9

// One workflow's row in the all-workflows table, reduced to what the fleet rollup needs.
export interface FleetRow {
    runCount: number
    successRate: number | null
    /** Most recent completed run failed; null when nothing has completed for that workflow. */
    latestRunFailed: boolean | null
    billableMinutes?: number | null
    estimatedCostUsd?: number | null
}

export interface FleetSummary {
    state: WorkflowState
    workflowCount: number
    /** Workflows whose latest run has settled (so they're either green or red right now). */
    settledWorkflows: number
    failingNow: number
    /** Currently green but below the success-rate floor — flaky. */
    flakyNow: number
    totalRuns: number
    billableMinutes: number | null
    estimatedCostUsd: number | null
}

/** Nearest-rank percentile over an ascending-sorted sample. */
function percentileSorted(sortedAsc: number[], q: number): number | null {
    if (sortedAsc.length === 0) {
        return null
    }
    return sortedAsc[Math.min(sortedAsc.length - 1, Math.max(0, Math.ceil(q * sortedAsc.length) - 1))]
}

/**
 * Verdict + headline stats for one workflow's runs. State mirrors the run tables: the latest settled run
 * failing is "failing"; an otherwise-passing workflow whose decisive-failure rate is elevated is
 * "degraded"; everything else is "healthy". Durations and rates are over completed runs only — a run that
 * hasn't settled is excluded, never counted as a failure.
 */
export function computeHealthSummary(runs: HealthRun[]): HealthSummary {
    const completed = runs.filter((run) => run.conclusion !== null)
    const running = runs.length - completed.length
    const passed = completed.filter((run) => isPassingConclusion(run.conclusion as string)).length
    const failures = completed.filter((run) => isDecisiveFailure(run.conclusion)).length
    const reruns = runs.filter((run) => (run.runAttempt ?? 1) > 1).length
    const passRate = completed.length ? passed / completed.length : null

    const durations = completed
        .map((run) => run.durationSeconds)
        .filter((d): d is number => d != null)
        .sort((a, b) => a - b)

    const byStartDesc = [...completed].sort((a, b) => (b.startedAt ?? '').localeCompare(a.startedAt ?? ''))
    const latestConclusion = byStartDesc[0]?.conclusion ?? null
    const lastFailureAt =
        completed
            .filter((run) => isDecisiveFailure(run.conclusion))
            .map((run) => run.startedAt)
            .filter((at): at is string => !!at)
            .sort()
            .at(-1) ?? null

    let state: WorkflowState
    if (completed.length === 0) {
        state = 'unknown'
    } else if (isDecisiveFailure(latestConclusion)) {
        state = 'failing'
    } else if (failures / completed.length >= DEGRADED_FAILURE_RATE) {
        state = 'degraded'
    } else {
        state = 'healthy'
    }

    return {
        state,
        totalRuns: runs.length,
        completedRuns: completed.length,
        passedRuns: passed,
        failures,
        running,
        reruns,
        passRate,
        medianSeconds: percentileSorted(durations, 0.5),
        p95Seconds: percentileSorted(durations, 0.95),
        lastFailureAt,
        latestConclusion,
    }
}

/**
 * Fleet verdict + rollups across all workflows in the window (the all-workflows page). State is the
 * worst the fleet is right now: every settled workflow red is "failing"; any red or flaky is "degraded";
 * otherwise "healthy". Runs and cost are summed across workflows; cost is null until any row carries it.
 */
export function computeFleetSummary(rows: FleetRow[]): FleetSummary {
    const workflowCount = rows.length
    const settledWorkflows = rows.filter((row) => row.latestRunFailed != null).length
    const failingNow = rows.filter((row) => row.latestRunFailed === true).length
    const flakyNow = rows.filter(
        (row) => row.latestRunFailed === false && row.successRate != null && row.successRate < FLAKY_SUCCESS_RATE
    ).length
    const totalRuns = rows.reduce((sum, row) => sum + row.runCount, 0)

    const hasCost = rows.some((row) => row.billableMinutes != null || row.estimatedCostUsd != null)
    const billableMinutes = hasCost ? rows.reduce((sum, row) => sum + (row.billableMinutes ?? 0), 0) : null
    const estimatedCostUsd = hasCost ? rows.reduce((sum, row) => sum + (row.estimatedCostUsd ?? 0), 0) : null

    let state: WorkflowState
    if (workflowCount === 0) {
        state = 'unknown'
    } else if (failingNow > 0 && failingNow === settledWorkflows) {
        state = 'failing'
    } else if (failingNow > 0 || flakyNow > 0) {
        state = 'degraded'
    } else {
        state = 'healthy'
    }

    return {
        state,
        workflowCount,
        settledWorkflows,
        failingNow,
        flakyNow,
        totalRuns,
        billableMinutes,
        estimatedCostUsd,
    }
}
