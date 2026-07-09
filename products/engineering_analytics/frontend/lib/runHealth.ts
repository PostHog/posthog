import { isDecisiveFailure } from './lifecycle'

/** Minimal run shape; WorkflowRunRow and PrRunRow both satisfy it. */
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

/** A single run's cost rolled up from its jobs, plus the count of billable jobs still in flight. */
export interface RunCostSummary extends CostSummary {
    unsettledJobs: number
}

/** Minimal job shape the run-cost roll-up needs; WorkflowJobApi satisfies it. */
export interface CostableJob {
    runner_provider: string
    duration_seconds: number | null
    estimated_cost_usd: number | null
}

export type WorkflowState = 'healthy' | 'degraded' | 'failing' | 'unknown'

export interface HealthSummary {
    state: WorkflowState
    totalRuns: number
    completedRuns: number
    passedRuns: number
    failures: number
    running: number
    /** Runs that were a 2nd+ attempt. */
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

// One workflow's row, reduced to what the fleet rollup needs.
export interface FleetRow {
    runCount: number
    successRate: number | null
    /** Most recent completed run failed; null when nothing has completed for that workflow. */
    latestRunFailed: boolean | null
    /** Last decisive failure in the window, or null if there was none — so a low success rate driven by
     *  skips/cancels (not failures) isn't mistaken for flakiness. */
    lastFailureAt?: string | null
    billableMinutes?: number | null
    estimatedCostUsd?: number | null
    /** Per-bucket completed/success counts — the weights behind the fleet-wide pass rate. */
    buckets?: { completed: number; successes: number }[]
    /** Runs in the window that were a 2nd+ attempt. */
    rerunCycles?: number
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
    /** Passes ÷ completed runs across every row's buckets; null when nothing has completed. */
    passRate: number | null
    /** Re-runs (attempt > 1) summed across workflows. */
    rerunCycles: number
    billableMinutes: number | null
    estimatedCostUsd: number | null
}

/** Nearest-rank percentile over an ascending-sorted sample. */
export function percentileSorted(sortedAsc: number[], q: number): number | null {
    if (sortedAsc.length === 0) {
        return null
    }
    return sortedAsc[Math.min(sortedAsc.length - 1, Math.max(0, Math.ceil(q * sortedAsc.length) - 1))]
}

/**
 * Verdict + headline stats for one workflow's runs. Durations and rates are over completed runs only —
 * an unsettled run is excluded, never counted as a failure.
 */
export function computeHealthSummary(runs: HealthRun[]): HealthSummary {
    const completed = runs.filter((run) => run.conclusion !== null)
    const running = runs.length - completed.length
    // Strictly 'success' (not skipped/neutral), mirroring the endpoint's success_rate so surfaces agree.
    const passed = completed.filter((run) => run.conclusion === 'success').length
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

/** Fleet verdict + rollups across all workflows: every settled workflow red → "failing"; any red or
 *  flaky → "degraded"; else "healthy". */
export function computeFleetSummary(rows: FleetRow[]): FleetSummary {
    const workflowCount = rows.length
    const settledWorkflows = rows.filter((row) => row.latestRunFailed != null).length
    const failingNow = rows.filter((row) => row.latestRunFailed === true).length
    // Flaky = currently green, below the success-rate floor, AND actually failed in the window. The
    // lastFailureAt gate keeps a low success rate from skips/cancels (no real failures) reading as flaky.
    const flakyNow = rows.filter(
        (row) =>
            row.latestRunFailed === false &&
            row.successRate != null &&
            row.successRate < FLAKY_SUCCESS_RATE &&
            row.lastFailureAt != null
    ).length
    const totalRuns = rows.reduce((sum, row) => sum + row.runCount, 0)

    // Completed-run-weighted, so a 3-run workflow can't move the fleet as much as a 3,000-run one.
    let completedRuns = 0
    let passedRuns = 0
    for (const row of rows) {
        for (const bucket of row.buckets ?? []) {
            completedRuns += bucket.completed
            passedRuns += bucket.successes
        }
    }
    const passRate = completedRuns > 0 ? passedRuns / completedRuns : null
    const rerunCycles = rows.reduce((sum, row) => sum + (row.rerunCycles ?? 0), 0)

    // Free runners report null — a bare sum would turn "no cost data" into a misleading $0.00.
    const hasBillable = rows.some((row) => row.billableMinutes != null)
    const hasEstimatedCost = rows.some((row) => row.estimatedCostUsd != null)
    const billableMinutes = hasBillable ? rows.reduce((sum, row) => sum + (row.billableMinutes ?? 0), 0) : null
    const estimatedCostUsd = hasEstimatedCost ? rows.reduce((sum, row) => sum + (row.estimatedCostUsd ?? 0), 0) : null

    let state: WorkflowState
    if (workflowCount === 0 || settledWorkflows === 0) {
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
        passRate,
        rerunCycles,
        billableMinutes,
        estimatedCostUsd,
    }
}

/**
 * Roll a run's jobs up to one cost figure, mirroring the backend cost model (logic/cost.py): only
 * self-hosted runners are billable, and a job contributes once settled. Returns null when there's
 * nothing to show, so the caller omits the tile.
 */
export function summarizeRunCost(jobs: CostableJob[]): RunCostSummary | null {
    const billable = jobs.filter((job) => job.runner_provider === 'self_hosted')
    const costed = billable.filter((job) => job.estimated_cost_usd != null)
    // Null cost on a finished job = unpriced tier, not "still running" — only no-duration jobs are unsettled.
    const unsettledJobs = billable.filter((job) => job.duration_seconds == null).length
    if (costed.length === 0 && unsettledJobs === 0) {
        return null
    }
    if (costed.length === 0) {
        // Billable jobs still running, none settled — keep the tile rather than report a misleading $0.00.
        return { billableMinutes: null, estimatedCostUsd: null, unsettledJobs }
    }
    const billableMinutes = costed.reduce((sum, job) => sum + (job.duration_seconds ?? 0) / 60, 0)
    const estimatedCostUsd = costed.reduce((sum, job) => sum + (job.estimated_cost_usd ?? 0), 0)
    return { billableMinutes, estimatedCostUsd, unsettledJobs }
}
